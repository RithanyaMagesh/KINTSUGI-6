"""Session state and concurrency (BACKEND_SPEC v1.1 sections 5.3, 9).

ZERO FastAPI imports -- unit-testable without HTTP (section 5.3). The Session
driver is the ONLY pacing loop (section 9.2): wall-clock is used for pacing and
the compute timeout, never inside message content. The server never writes logs
(section 9.6); the sim runs in asyncio.to_thread touching no shared state
(section 9.1), so determinism is structurally safe.
"""

from __future__ import annotations

import asyncio
from bisect import bisect_right
from pathlib import Path
from typing import Literal

import cubesat.sim as sim_module
from cubesat.benchmark_policies import even_split_replan, hungarian_keepout_replan
from cubesat.replay import ReplayLog, index_at, load_jsonl
from cubesat.scenario import Failure, FailureMode, Scenario, load_scenario
from cubesat.sim import run_scenario
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
        cls, base: Scenario, sat_display_id: str, mode: str, t_now: float
    ) -> LiveSource:
        """Failure injection = recompute (section 4, consequence 2): the only
        change is one failure scheduled at t_now, so the recomputed prefix is
        byte-identical (pinned by test_inject_prefix_byte_identical)."""
        idx = _parse_sat_id(sat_display_id)
        failures = sorted(
            list(base.failures) + [Failure(t=t_now, sat_id=idx, mode=FailureMode(mode))],
            key=lambda f: (f.t, f.sat_id),
        )
        augmented = base.model_copy(update={"failures": failures})
        return cls(augmented, run_scenario(augmented))


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

    # ---- read-only view (hello / snapshot / health) -----------------------

    @property
    def sim_time(self) -> float | None:
        return self._last_frame_t

    def hello(self) -> dict:
        return {
            "type": "hello",
            "mode": self.mode,
            "scenario": self.enrich.scenario,
            "seed": self.enrich.seed,
            "sim_time": self._last_frame_t,
            "skipped": self._source.skipped if self._source else 0,
        }

    def snapshot(self) -> dict:
        """Current sim_state for WS hello / late joiners (section 5.3)."""
        return dict(self._snapshot)

    # ---- lifecycle ---------------------------------------------------------

    async def start_live(
        self, scenario_name: str | None = None, seed: int | None = None, speed: float = 100.0
    ) -> None:
        self._teardown()
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
        scenario = load_scenario(path)
        if seed is not None and seed != scenario.seed:
            scenario = scenario.model_copy(update={"seed": seed})
        self.mode = "live"
        self.speed = speed
        self._prepare(SessionEnrich(scenario=scenario.name, seed=scenario.seed))
        try:
            lines = await asyncio.wait_for(
                asyncio.to_thread(run_scenario, scenario), self.run_timeout_s
            )
        except TimeoutError:
            self._teardown()
            raise SessionError(504, "scenario computation timed out") from None
        self._source = LiveSource(scenario, lines)
        await self._spawn_driver()

    async def load_replay(self, filename: str, speed: float = 100.0) -> int:
        """Returns the skipped (unparseable) line count (section 7.1)."""
        self._teardown()
        path = self.log_dir / Path(filename).name  # section 7.2 path safety
        if not path.is_file():
            raise SessionError(404, "replay file not found")
        log = await asyncio.to_thread(load_jsonl, path)
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
                to_event("warning", 0.0, f"{log.skipped} unparseable lines skipped in {filename}")
            )
        if not log.frames:
            self.hub.publish(
                to_event("critical", 0.0, f"replay file {filename} has no usable frames")
            )
        self._source = ReplaySource(log)
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
        self._teardown()

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
                self._snapshot = to_sim_state(self._source.frames[self._cursor], self.enrich)
        self.finished = False
        if not self.paused:
            await self._spawn_driver()

    async def inject_failure(self, sat_display_id: str, mode: str) -> None:
        """Live only (section 5.3). 409: not live / run finished / unknown sat /
        already failed (section 7.1)."""
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
        self.hub.publish(
            to_event(
                "warning", t_now,
                f"{sat_display_id} {mode} failure injected; recomputing trajectory...",
            )
        )
        try:
            new_source = await asyncio.wait_for(
                asyncio.to_thread(LiveSource.with_failure, source.scenario,
                                  sat_display_id, mode, t_now),
                self.run_timeout_s,
            )
        except TimeoutError:
            raise SessionError(504, "failure recomputation timed out") from None
        self._cancel_driver()
        self._source = new_source
        # frames before t_now already streamed and are byte-identical: resume
        # strictly AFTER t_now (bisect_right)
        self._cursor = min(bisect_right(new_source.times, t_now), len(new_source.times))
        self.finished = False
        if not self.paused:
            await self._spawn_driver()

    # ---- internals ---------------------------------------------------------

    def _require_running(self) -> None:
        if self.mode == "stopped":
            raise SessionError(409, "no simulation running")

    def _prepare(self, enrich: SessionEnrich) -> None:
        self.enrich = enrich
        self.paused = False
        self.finished = False
        self._cursor = 0
        self._last_frame_t = None
        self._last_emit_wall = None
        self._snapshot = to_sim_state({"state": "INIT", "t": 0.0}, self.enrich)

    def _teardown(self) -> None:
        self._cancel_driver()
        self.mode = "stopped"
        self.paused = False
        self.finished = False
        self._source = None
        self._cursor = 0
        self._last_frame_t = None
        self._last_emit_wall = None
        self.enrich = SessionEnrich()
        self._snapshot = to_sim_state({"state": "INIT", "t": 0.0}, self.enrich)

    def _cancel_driver(self) -> None:
        if self._driver is not None:
            self._driver.cancel()
            self._driver = None

    async def _spawn_driver(self) -> None:
        self._cancel_driver()
        if self.mode == "stopped" or self._source is None:
            return
        self._driver = asyncio.get_running_loop().create_task(self._drive())
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
        msgs = to_messages(frame, self.enrich)
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
