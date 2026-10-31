"""Session state and concurrency (BACKEND_SPEC v1.1 sections 5.3, 9).

ZERO FastAPI imports -- unit-testable without HTTP (section 5.3). The Session
driver is the ONLY pacing loop (section 9.2): wall-clock is used for pacing and
the compute timeout, never inside message content. The server never writes logs
(section 9.6); the sim runs in asyncio.to_thread touching no shared state
(section 9.1), so determinism is structurally safe.
"""

from __future__ import annotations

import asyncio
import threading
from bisect import bisect_right
from pathlib import Path
from typing import Literal

import cubesat.sim as sim_module
from cubesat.benchmark_policies import even_split_replan, hungarian_keepout_replan
from cubesat.replay import ReplayLog, index_at, load_jsonl
from cubesat.scenario import Failure, FailureMode, Scenario, load_scenario
from cubesat.sim import RunCancelled, run_scenario
from cubesat.wire import POLICY_VALUES, SessionEnrich, to_event, to_messages, to_sim_state


class SessionError(Exception):
    """Domain error; the API layer maps status_code/detail to HTTP (section 7.1)."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# The replan seam (docs/ENDGAME_PLAN.md 3.2-3.3): sim.py resolves the module-global
# `replan` at its call site (cubesat/sim.py:265), so rebinding cubesat.sim.replan
# in-process switches the recovery algorithm with ZERO core diffs -- the exact
# mechanism cubesat.benchmark.run_one uses. "hungarian" is NOT in this map: the
# default never rebinds, so a default start is byte-identical to the pre-policy
# core (the golden determinism pin stays untouched).
_POLICY_REPLANNERS = {
    "even_split": even_split_replan,
    "hungarian_keepout": hungarian_keepout_replan,
}


class Hub:
    """One queue per WS client (section 9.5). publish is sync and O(1)-bounded:
    a full queue drops the oldest queued sim_state; event / role_reassignment
    messages queued in the hub are never dropped (section 9.4)."""

    def __init__(self, maxsize: int = 128) -> None:
        self.maxsize = maxsize
        self._queues: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self.maxsize)
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        for i, known in enumerate(self._queues):
            if known is q:
                del self._queues[i]
                return

    def publish(self, msg: dict) -> None:
        for q in list(self._queues):
            if not q.full():
                q.put_nowait(msg)
                continue
            # Full: drop the oldest queued sim_state, order-preserving.
            buffered = [q.get_nowait() for _ in range(q.qsize())]
            oldest_state = next(
                (i for i, m in enumerate(buffered) if m.get("type") == "sim_state"), None
            )
            if oldest_state is not None:
                del buffered[oldest_state]
                buffered.append(msg)
            # else: the queue holds only events (never happens with real event
            # rates) -- the incoming message is discarded rather than ever
            # blocking the driver or dropping an already-queued event.
            for m in buffered:
                q.put_nowait(m)


class LiveSource:
    """run_scenario output as a cursor-able frame source (section 4)."""

    def __init__(self, scenario: Scenario, lines: list[dict]) -> None:
        self.scenario = scenario
        self.header = lines[0] if lines and lines[0].get("state") == "INIT" else None
        self.summary = next((line for line in lines if line.get("state") == "SUMMARY"), None)
        self.frames = [line for line in lines if line.get("state") not in ("INIT", "SUMMARY")]
        self.times = [float(frame["t"]) for frame in self.frames]
        self.skipped = 0

    @property
    def scenario_name(self) -> str | None:
        return self.scenario.name

    @property
    def seed(self) -> int | None:
        return self.scenario.seed

    @classmethod
    def with_failure(
        cls, base: Scenario, sat_display_id: str, mode: str, t_now: float,
        degrade_s: float = 0.0, cancel_event: threading.Event | None = None,
    ) -> LiveSource:
        """Failure injection = recompute (section 4, consequence 2): the only
        change is one failure scheduled at t_now, so for DEAD and THRUSTER_OUT
        injections the recomputed prefix is byte-identical (pinned by
        test_inject_prefix_byte_identical).
        degrade_s only matters for EPS_DEGRADE (Addendum v1.2): the injected sat
        then fades to DEGRADED over degrade_s before dying at t_now. With
        degrade_s > 0 the fade fires at max(t_now - degrade_s, 0) -- inside the
        prefix -- so that recomputed prefix carries DEGRADED status and a
        DEGRADE_START event instead of matching byte for byte (self-consistent
        recompute, same run_scenario output either way).
        cancel_event passes through to run_scenario (compute-timeout
        cooperative cancellation, same contract as start_live)."""
        idx = _parse_sat_id(sat_display_id)
        failures = sorted(
            list(base.failures)
            + [
                Failure(
                    t=t_now, sat_id=idx, mode=FailureMode(mode), degrade_s=degrade_s
                )
            ],
            key=lambda f: (f.t, f.sat_id),
        )
        augmented = base.model_copy(update={"failures": failures})
        return cls(augmented, run_scenario(augmented, cancel_event))


class ReplaySource:
    """A committed JSONL log as a frame source -- same surface as LiveSource."""

    def __init__(self, log: ReplayLog) -> None:
        self.log = log
        self.header = log.header
        self.summary = log.summary
        self.frames = log.frames
        self.times = log.times
        self.skipped = log.skipped

    @property
    def scenario_name(self) -> str | None:
        return self.log.header.get("scenario") if self.log.header else None

    @property
    def seed(self) -> int | None:
        return self.log.header.get("seed") if self.log.header else None


def _parse_sat_id(sat_display_id: str) -> int:
    try:
        idx = int(sat_display_id.strip().split("-")[1]) - 1
    except (IndexError, ValueError, AttributeError):
        raise SessionError(409, f"unknown satellite {sat_display_id!r}") from None
    if idx < 0:
        raise SessionError(409, f"unknown satellite {sat_display_id!r}")
    return idx


class Session:
    """All mutable run state. pause/resume/speed/seek/inject = cancel driver ->
    mutate cursor/anchor/source -> respawn (section 9.2)."""

    def __init__(
        self,
        scenario_dir: Path,
        log_dir: Path,
        hub: Hub,
        *,
        min_emit_interval: float = 1.0 / 30.0,
        run_timeout_s: float = 60.0,
    ) -> None:
        self.scenario_dir = Path(scenario_dir)
        self.log_dir = Path(log_dir)
        self.hub = hub
        self.min_emit_interval = min_emit_interval  # WS cadence cap (section 10)
        self.run_timeout_s = run_timeout_s
        self.mode: Literal["stopped", "live", "replay"] = "stopped"
        self.paused = False
        self.speed = 100.0
        self.finished = False
        self.enrich = SessionEnrich()
        self._source: LiveSource | ReplaySource | None = None
        self._cursor = 0  # frame cursor into source.frames
        self._driver: asyncio.Task | None = None
        self._snapshot = to_sim_state({"state": "INIT", "t": 0.0}, self.enrich)
        self._last_frame_t: float | None = None
        self._anchor_t = 0.0
        self._anchor_wall = 0.0
        self._last_emit_wall: float | None = None
        self._seam_original = None  # cubesat.sim.replan before the policy seam rebind
        # Mutation serialization (audit B-1/B-2/B-3). start/replay/inject/reset hold
        # _mutex for their whole duration. _epoch identifies the current RUN: start,
        # replay and reset bump it BEFORE queueing for the lock, so anything queued
        # or computing for an older run sees the change and gives up with 409.
        self._epoch = 0
        self._cancel: threading.Event | None = None  # cancel flag of the in-flight compute
        self._lock: asyncio.Lock | None = None
        self._lock_loop: asyncio.AbstractEventLoop | None = None
        # Display-only predictor risk map (see _install_predictor): t_s -> sat_id -> [0,1].
        self._risk_by_t: dict[float, dict[int, float]] | None = None
        self._risk_times: list[float] = []  # sorted _risk_by_t keys, for bisect carry-forward
        self._predictor_note: str | None = None

    # ---- read-only view (hello / snapshot / health) -----------------------

    @property
    def sim_time(self) -> float | None:
        return self._last_frame_t

    @property
    def predictor_active(self) -> bool:
        """True when the display-only predictor risk map is installed."""
        return self._risk_by_t is not None

    def hello(self) -> dict:
        msg = {
            "type": "hello",
            "mode": self.mode,
            "scenario": self.enrich.scenario,
            "seed": self.enrich.seed,
            "sim_time": self._last_frame_t,
            "skipped": self._source.skipped if self._source else 0,
        }
        # Policy echo, known-only: live runs always carry the session's active
        # policy (including the default "hungarian"); stopped and replay omit
        # the key -- a replayed log records no policy field, and the committed
        # benchmark logs under data/eval/benchmark include even_split and
        # do_nothing runs, so claiming "hungarian" for a replay would be a
        # fabrication (AGENTS.md invariant 1). Absence = unknown: the frontend
        # defaults to "hungarian" (every pre-policy committed data/logs log IS
        # a hungarian run by construction).
        if self.enrich.policy is not None:
            msg["policy"] = self.enrich.policy
        # Predictor echo, deviation-only, same pattern as the policy echo: the
        # key is carried ONLY when the display-only risk map is active and
        # omitted otherwise, so predictor-off hellos keep their byte shape.
        if self.predictor_active:
            msg["predictor"] = True
        return msg

    def snapshot(self) -> dict:
        """Current sim_state for WS hello / late joiners (section 5.3)."""
        return dict(self._snapshot)

    # ---- lifecycle ---------------------------------------------------------

    def _mutex(self) -> asyncio.Lock:
        # ponytail: one lock per Session, re-made per event loop (TestClient runs a
        # loop per request); upgrade to per-session locks lives with the L1 rewrite.
        loop = asyncio.get_running_loop()
        if self._lock_loop is not loop:
            self._lock, self._lock_loop = asyncio.Lock(), loop
        return self._lock

    def _supersede(self) -> int:
        """New run identity: older queued/in-flight work gives up, and the thread
        computing for it is told to stop at its next tick (B-5)."""
        self._epoch += 1
        self._cancel_compute()
        return self._epoch

    def _cancel_compute(self) -> None:
        if self._cancel is not None:
            self._cancel.set()
            self._cancel = None

    def _announce_stopped(self) -> None:
        """Tell every viewer the run is gone (B-19): hello(mode=stopped) then the
        empty sim_state. Both are existing message types -- no new wire shape; the
        console treats the empty state as "no satellites"."""
        self.hub.publish(self.hello())
        self.hub.publish(self.snapshot())

    def shutdown(self) -> None:
        """Server stop: drop the run and cancel any in-flight compute thread."""
        self._supersede()
        self._teardown()

    def _check_epoch(self, epoch: int) -> None:
        if epoch != self._epoch:
            raise SessionError(409, "superseded by a newer start, load or reset")

    def _load_scenario(self, scenario_name: str | None, seed: int | None) -> Scenario:
        """Resolve + parse the requested scenario WITHOUT touching session state, so
        a bad request never tears down the running session (B-17)."""
        name = scenario_name
        if name is None:
            found = sorted(self.scenario_dir.glob("*.json"))
            if not found:
                raise SessionError(409, "no scenarios available")
            name = found[0].name
        if Path(name).name != name:
            raise SessionError(404, "scenario not found")
        path = self.scenario_dir / name
        if not path.is_file():
            raise SessionError(404, "scenario not found")
        try:
            scenario = load_scenario(path)
        except ValueError:
            raise SessionError(422, f"scenario file {name} is not a valid scenario") from None
        if seed is not None and seed != scenario.seed:
            scenario = scenario.model_copy(update={"seed": seed})
        return scenario

    async def start_live(
        self,
        scenario_name: str | None = None,
        seed: int | None = None,
        speed: float = 100.0,
        policy: str = "hungarian",
        predictor: bool = False,
    ) -> None:
        """Last accepted start wins: an earlier or queued start is cancelled and
        fails 409 "superseded" (B-1)."""
        # Input validation before any state change: a bad policy never clobbers
        # a running session. The API's pydantic Literal already 422s at the
        # boundary; this mirrors it for direct session callers (section 5.3).
        if policy not in POLICY_VALUES:
            raise SessionError(
                422, f"unknown policy {policy!r}; expected one of: {', '.join(POLICY_VALUES)}"
            )
        scenario = self._load_scenario(scenario_name, seed)  # 404/409/422 before any teardown
        epoch = self._supersede()
        async with self._mutex():
            self._check_epoch(epoch)
            self._teardown()
            self.mode = "live"
            self.speed = speed
            self._prepare(
                SessionEnrich(scenario=scenario.name, seed=scenario.seed, policy=policy)
            )
            # Cooperative cancellation for the timeout below: wait_for cancels only
            # the await -- without the event the run_scenario thread would keep
            # running to completion as an orphan, pinning CPU in the shared server
            # process (audit, medium). The event is set on timeout and the thread
            # exits at its next tick (sim.run_scenario contract, zero effect on any
            # canonical run).
            cancel = self._cancel = threading.Event()
            try:
                lines = await asyncio.wait_for(
                    asyncio.to_thread(run_scenario, scenario, cancel), self.run_timeout_s
                )
            except TimeoutError:
                cancel.set()  # the abandoned thread stops at its next tick
                self._teardown()  # also closes the policy seam
                self._announce_stopped()
                raise SessionError(504, "scenario computation timed out") from None
            except RunCancelled:
                self._restore_seam()
                raise SessionError(409, "superseded by a newer start, load or reset") from None
            except BaseException:
                # Never leak the process-global replan seam on a failed start
                # (the abandoned thread's output is discarded either way).
                cancel.set()  # client abort / any failure: stop the thread
                self._restore_seam()
                if epoch == self._epoch:
                    self._teardown()  # no zombie "live" session without a source
                raise
            self._check_epoch(epoch)  # a newer start/reset arrived during the compute
            self._source = LiveSource(scenario, lines)
            if predictor:
                # DISPLAY-only scoring against the run's own scenario + seed (the
                # source holds both); failure -> exactly one warning, run unaffected.
                self._install_predictor(self._source.scenario, self._source.seed)
                self._warn_predictor_down()
            await self._spawn_driver()

    async def load_replay(
        self, filename: str, speed: float = 100.0, predictor: bool = False
    ) -> int:
        """Returns the skipped (unparseable) line count (section 7.1)."""
        path = self.log_dir / Path(filename).name  # section 7.2 path safety
        if not path.is_file():  # before any teardown (B-17)
            raise SessionError(404, "replay file not found")
        epoch = self._supersede()
        async with self._mutex():
            self._check_epoch(epoch)
            log = await asyncio.to_thread(load_jsonl, path)
            self._check_epoch(epoch)
            self._teardown()
            self.mode = "replay"
            self.speed = speed
            self._prepare(
                SessionEnrich(
                    scenario=log.header.get("scenario") if log.header else None,
                    seed=log.header.get("seed") if log.header else None,
                )
            )
            if log.skipped:
                self.hub.publish(
                    to_event(
                        "warning", 0.0, f"{log.skipped} unparseable lines skipped in {filename}"
                    )
                )
            if not log.frames:
                self.hub.publish(
                    to_event("critical", 0.0, f"replay file {filename} has no usable frames")
                )
            self._source = ReplaySource(log)
            if predictor:
                self._install_replay_predictor()
                self._warn_predictor_down()
            await self._spawn_driver()
            return log.skipped

    async def pause(self) -> None:
        self._require_running()
        self.paused = True
        self._cancel_driver()

    async def resume(self) -> None:
        self._require_running()
        if self.paused:
            self.paused = False
            if not self.finished:
                await self._spawn_driver()

    async def reset(self) -> None:
        epoch = self._supersede()
        async with self._mutex():
            if epoch == self._epoch:  # a start queued after this reset keeps the floor
                was_running = self.mode != "stopped"
                self._teardown()
                if was_running:
                    self._announce_stopped()

    async def set_speed(self, speed: float) -> None:
        self._require_running()
        if speed <= 0:
            raise SessionError(409, "speed must be positive")
        self.speed = speed
        if not self.paused and not self.finished:
            await self._spawn_driver()  # re-anchor: pacing restarts from the cursor

    async def seek(self, t: float) -> None:
        self._require_running()
        if self.mode != "replay":
            raise SessionError(409, "seek is replay-only")
        self._cancel_driver()
        if self._source is not None:
            self._cursor = index_at(self._source, t)
            if self._cursor < len(self._source.frames):
                # Same display-only augmentation as _advance, so seeked clients
                # (and late joiners reading this snapshot) see risk too.
                self._snapshot = to_sim_state(
                    self._frame_with_risk(self._source.frames[self._cursor]), self.enrich
                )
        self.finished = False
        if not self.paused:
            await self._spawn_driver()

    async def inject_failure(
        self, sat_display_id: str, mode: str, degrade_s: float = 600.0
    ) -> None:
        """Live only (section 5.3). 409: not live / run finished / unknown sat /
        already failed / the run was replaced or reset meanwhile (section 7.1).
        Injects are serialized: a second one waits and recomputes on top of the
        first. Playback is HELD for the recompute (no frames stream from the
        pre-injection source), so the cursor never moves backwards (B-3). The
        recompute (LiveSource.with_failure -> run_scenario) replans under the
        session's active policy: the replan seam opened in _prepare is still
        installed across the live lifetime. degrade_s is the EPS_DEGRADE fade
        length (Addendum v1.2); other modes ignore it."""
        epoch = self._epoch
        async with self._mutex():
            self._check_epoch(epoch)
            if self.mode != "live":
                raise SessionError(409, "failure injection requires a live run")
            source = self._source
            if source is None or self.finished or self._cursor >= len(source.frames):
                raise SessionError(409, "run finished")
            idx = _parse_sat_id(sat_display_id)
            if idx >= source.scenario.n_sats:
                raise SessionError(409, f"unknown satellite {sat_display_id!r}")
            if any(f.sat_id == idx for f in source.scenario.failures):
                raise SessionError(409, f"{sat_display_id} already failed")
            t_now = self._last_frame_t if self._last_frame_t is not None else 0.0
            self._cancel_driver()  # hold playback at t_now until the recompute lands
            self.hub.publish(
                to_event(
                    "warning", t_now,
                    f"{sat_display_id} {mode} failure injected; recomputing trajectory...",
                )
            )
            cancel = self._cancel = threading.Event()  # same guard as start_live
            applied = False
            try:
                new_source = await asyncio.wait_for(
                    asyncio.to_thread(
                        LiveSource.with_failure, source.scenario, sat_display_id,
                        mode, t_now, degrade_s, cancel,
                    ),
                    self.run_timeout_s,
                )
                self._check_epoch(epoch)  # stale recompute: its run was replaced
                applied = True
            except TimeoutError:
                cancel.set()  # the abandoned recompute thread stops at its next tick
                raise SessionError(504, "failure recomputation timed out") from None
            except RunCancelled:
                raise SessionError(409, "superseded by a newer start, load or reset") from None
            except BaseException:
                cancel.set()
                raise
            finally:
                if not applied and epoch == self._epoch and not self.paused:
                    self._start_driver()  # failed inject: the old run plays on
            self._source = new_source
            # frames up to t_now already streamed and are byte-identical: resume
            # strictly AFTER t_now (bisect_right); the driver was held, so this is
            # exactly where the cursor already stood
            self._cursor = min(bisect_right(new_source.times, t_now), len(new_source.times))
            self.finished = False
            if not self.paused:
                await self._spawn_driver()

    # ---- internals ---------------------------------------------------------

    def _require_running(self) -> None:
        if self.mode == "stopped":
            raise SessionError(409, "no simulation running")

    def _install_seam(self) -> None:
        """Open the replan seam for the selected policy, scoped to the run (set
        up here in _prepare, restored in _teardown -- the same rebind
        cubesat.benchmark.run_one performs with try/finally, but held open
        across the session's whole live lifetime so that failure-injection
        RECOMPUTES replan under the same policy). "hungarian" never rebinds:
        a default start runs the untouched core, byte-identical to the golden
        pin. Process-global by nature -- safe under the API's one-Session-per-
        process model (section 9.1), the same assumption cubesat.benchmark makes.
        """
        replanner = _POLICY_REPLANNERS.get(self.enrich.policy or "")
        if replanner is None:
            return
        self._seam_original = sim_module.replan
        sim_module.replan = replanner

    def _restore_seam(self) -> None:
        """Close the replan seam (idempotent; no-op when never opened)."""
        if self._seam_original is not None:
            sim_module.replan = self._seam_original
            self._seam_original = None

    def _install_predictor(self, scenario: Scenario, seed: int) -> None:
        """Score the sealed LightGBM predictor over this scenario and build the
        display-only risk map t_s -> sat_id -> [0,1] (boundary: see _advance).
        Rows are STRIDE=10 scored ticks apart; frames between scored ticks carry
        forward the most recent earlier score at lookup time (_frame_with_risk),
        never by pre-filling. ood rows (past the pipeline's T_TICKS training
        range) are excluded. Any failure -- missing model file, lightgbm import,
        scoring -- leaves the map OFF and records the reason in _predictor_note,
        so a broken predictor can never break a run."""
        try:
            from predictor.runtime import score_run, telemetry_from_schedule

            rows = score_run(telemetry_from_schedule(scenario, seed))
            risk: dict[float, dict[int, float]] = {}
            for row in rows:
                if row.ood:
                    continue
                risk.setdefault(row.t_s, {})[row.sat_id] = min(1.0, max(0.0, row.score))
            self._risk_by_t = risk
            self._risk_times = sorted(risk)  # explicit order: no dict-order reliance
            self._predictor_note = None
        except Exception as exc:  # noqa: BLE001 -- the predictor is strictly optional
            self._risk_by_t = None
            self._risk_times = []
            self._predictor_note = f"{type(exc).__name__}: {exc}"

    def _install_replay_predictor(self) -> None:
        """Resolve the replay's Scenario from scenarios_dir by the log's INIT
        scenario name + seed; a missing file (or a header without scenario/seed)
        leaves the predictor off with the reason recorded."""
        name = self._source.scenario_name if self._source else None
        seed = self._source.seed if self._source else None
        if not name or seed is None:
            self._predictor_note = "log header lacks scenario/seed"
            return
        fname = name if name.endswith(".json") else f"{name}.json"
        path = self.scenario_dir / Path(fname).name  # basename: traversal-safe
        if not path.is_file():
            self._predictor_note = f"scenario file {path.name} not found"
            return
        self._install_predictor(load_scenario(path), seed)

    def _warn_predictor_down(self) -> None:
        """Publish the ONE predictor-unavailable warning when an install failed."""
        if self._predictor_note is not None:
            self.hub.publish(
                to_event("warning", 0.0, "Predictor unavailable: " + self._predictor_note)
            )

    def _frame_with_risk(self, frame: dict) -> dict:
        """Display-only predictor overlay for one source frame. Sats scored at
        the most recent scored t <= frame t (bisect carry-forward) get a 'risk'
        key in [0,1]; unscored sats keep NO key (wire.py:146 passes risk through
        only when present, never synthesizes). Returns the frame UNCHANGED when
        the predictor is off or nothing is scored yet, so predictor-off wire
        bytes stay byte-identical to the pre-predictor stream."""
        risk_by_t = self._risk_by_t
        if not risk_by_t:
            return frame
        idx = bisect_right(self._risk_times, frame.get("t", 0.0))
        if idx == 0:
            return frame
        scored = risk_by_t[self._risk_times[idx - 1]]
        sats = frame.get("sats")
        if not scored or not isinstance(sats, list) or not sats:
            return frame
        return {
            **frame,
            "sats": [
                {**s, "risk": scored[s["id"]]}
                if isinstance(s, dict) and s.get("id") in scored
                else s
                for s in sats
            ],
        }

    def _prepare(self, enrich: SessionEnrich) -> None:
        self.enrich = enrich
        self.paused = False
        self.finished = False
        self._cursor = 0
        self._last_frame_t = None
        self._last_emit_wall = None
        self._snapshot = to_sim_state({"state": "INIT", "t": 0.0}, self.enrich)
        self._install_seam()

    def _teardown(self) -> None:
        self._cancel_compute()
        self._cancel_driver()
        self._restore_seam()
        self.mode = "stopped"
        self.paused = False
        self.finished = False
        self._source = None
        self._cursor = 0
        self._last_frame_t = None
        self._last_emit_wall = None
        self._risk_by_t = None  # display-only risk map never outlives its run
        self._risk_times = []
        self._predictor_note = None
        self.enrich = SessionEnrich()
        self._snapshot = to_sim_state({"state": "INIT", "t": 0.0}, self.enrich)

    def _cancel_driver(self) -> None:
        if self._driver is not None:
            self._driver.cancel()
            self._driver = None

    def _start_driver(self) -> None:
        self._cancel_driver()
        if self.mode == "stopped" or self._source is None:
            return
        self._driver = asyncio.get_running_loop().create_task(self._drive())

    async def _spawn_driver(self) -> None:
        self._start_driver()
        if self._driver is None:
            return
        # Yield one loop slice so the driver's first (synchronous) frames are
        # published before the caller's response returns. Deterministic under
        # per-request TestClient portals (section 14.3): a run paced to emit
        # instantly has fully broadcast by the time load/start/seek returns,
        # instead of racing the portal shutdown.
        await asyncio.sleep(0)

    def _re_anchor(self, loop: asyncio.AbstractEventLoop) -> None:
        source = self._source
        times = source.times if source else []
        if self._cursor < len(times):
            self._anchor_t = times[self._cursor]
        elif times:
            self._anchor_t = times[-1]
        else:
            self._anchor_t = 0.0
        self._anchor_wall = loop.time()

    def _emit(self, msg: dict) -> None:
        self.hub.publish(msg)
        if msg.get("type") == "sim_state":
            self._snapshot = msg

    def _advance(self, i: int, loop: asyncio.AbstractEventLoop) -> None:
        """Pure/sync frame building for frame i (section 14.3); wall-clock only
        for the emit-cadence decision, never in content (section 9.2)."""
        frame = self._source.frames[i]
        # DISPLAY-ONLY predictor seam (the one injection site). _frame_with_risk
        # attaches sats[].risk to a THROWAWAY COPY of the frame so the UI can
        # render it (RiskPanel / Suspect labels). NOTHING in the sim, allocation
        # or replan consumes it: the kill-switch verdict cutting the predictor's
        # CONTROL use (triggering earlier reassignment) stays cut. The source
        # frames -- and therefore the committed log bytes -- are never touched;
        # with the predictor off the wire bytes are identical to today's.
        msgs = to_messages(self._frame_with_risk(frame), self.enrich)
        carries_event = any(m.get("type") in ("event", "role_reassignment") for m in msgs)
        now = loop.time()
        due = (
            self.min_emit_interval <= 0
            or self._last_emit_wall is None
            or now - self._last_emit_wall >= self.min_emit_interval
        )
        if due or carries_event or i + 1 >= len(self._source.frames):
            for msg in msgs:  # always emit event lines immediately (section 10)
                self._emit(msg)
            self._last_emit_wall = now
        else:
            for msg in msgs:  # decimated: late joiners still get the freshest state
                if msg.get("type") == "sim_state":
                    self._snapshot = msg
        self._last_frame_t = frame["t"]

    async def _drive(self) -> None:
        """Task body. A dead driver is never silent (section 7.1): any exception
        escapes as a critical event, and the run is marked finished (terminal --
        no more frames will ever come; reset/load remain available)."""
        try:
            await self._drive_steps()
        except Exception as exc:  # noqa: BLE001 -- the point is never-silent
            self.finished = True
            t = self._last_frame_t if self._last_frame_t is not None else 0.0
            self.hub.publish(
                to_event("critical", t, f"stream stopped: {type(exc).__name__}: {exc}")
            )

    async def _drive_steps(self) -> None:
        loop = asyncio.get_running_loop()
        source = self._source
        if source is None:
            return
        if self._cursor == 0 and source.header is not None:
            for msg in to_messages(source.header, self.enrich):
                self._emit(msg)
        self._re_anchor(loop)
        frames, times = source.frames, source.times
        while self._cursor < len(frames):
            if self.paused:
                return
            i = self._cursor
            delay = (self._anchor_wall + (times[i] - self._anchor_t) / self.speed) - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
                if self.paused:
                    return
            self._advance(i, loop)
            self._cursor = i + 1
        if source.summary is not None:
            for msg in to_messages(source.summary, self.enrich):
                self._emit(msg)
        self.finished = True  # driver idles holding the last frame (section 6.3)
