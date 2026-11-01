"""Engine v2 recovery glue (opt-in `recovery.ladder: true`): trigger, recovery ladder
(cubesat/ladder.py), plan executor. Without the flag `attach` returns None and EngineV2 is
byte-identical to before.

Timeline: a tick with FAILURE_DETECTED arms a replan; the NEXT tick (PLANNING) runs the ladder
from the engine's true state and executes the chosen plan at once: RECOVERY_LEVEL{level,
reason, rejected, ...} and, for every executed plan, CERTIFICATE (certify.event_payload).
Nothing executes without a passed certificate. EXECUTOR = the certificate's own model: seats
set as certify sets them (commandable, non-passive sats), the certified burn schedule
(certify_sim.burn_schedule) flown open loop from the plan tick, then PD capture, every step
through step_v2.advance (the function the certificate simulates). A new failure cancels the
remaining burns and replans from the measured truth (re-certified). No MPC re-solve: the
certificate's model is the truth model, so the open-loop plan lands where certified (tested);
MPC would only pay with sensing noise or model mismatch, neither exists here.
"""

from __future__ import annotations

import numpy as np

from cubesat import ladder
from cubesat.certify import CertificateCancelled, swarm_state_from_engine
from cubesat.certify_checks import DEAD, commandable, passive
from cubesat.certify_sim import burn_schedule
from cubesat.hcw import propagate
from cubesat.roles_v2 import capability, handoff_events
from cubesat.sim import RunCancelled
from cubesat.transfer import Transfer, TransferCancelled


class Recovery:
    def __init__(self) -> None:
        self.armed = False  # a failure was declared: plan on the next tick
        self.k0 = 0  # tick the executing plan started
        self.burns: dict[int, tuple[np.ndarray, int]] = {}  # sat -> (burn per step, PD from)
        self.level: str | None = None
        self.off_plan = False  # a burn of the current plan was not delivered (replan armed)

    def tick(self, eng, t: float, events: list[dict], cancel=None) -> list[dict]:
        """Events of the recovery step for this tick (after faults and roles)."""
        if any(e["type"] == "FAILURE_DETECTED" for e in events):
            self.armed = True  # the plan in flight keeps flying until the replan
            return []
        if not self.armed:
            return []
        out = self._plan(eng, cancel)
        self.armed = False  # only once planned: a cancelled planning tick leaves it armed
        return out

    def commands(self, k: int) -> dict:
        j = k - self.k0
        return {i: burn[j] for i, (burn, last) in self.burns.items() if j < last}

    def check_delivery(self, cmd, u, faults) -> None:
        """A planned burn that thrust_limited did not deliver (k dropped by a silent
        PARTIAL_THRUST, a stuck valve, a dry tank) makes the certified plan false: arm a replan
        once per plan. Only a sat that still reports can tell (its own accelerometer)."""
        for i, c in (cmd or {}).items():
            st, sat = faults.status[i], faults.sats[i]
            talks = capability(st, True, sat.radio_ok, "leader")
            off = np.linalg.norm(u[i] - c) > 1e-6 * np.linalg.norm(c) + 1e-12
            if talks and off and not self.off_plan:
                self.off_plan = self.armed = True

    def inflight(self, k: int, dt: float) -> dict:
        """The remaining burns from tick k as Transfers (one node per non-zero burn step, dv =
        a dt, so the certificate re-flies them as the same per-step accelerations) plus a zero
        node at the original PD hand-over step, so the coast to it is kept."""
        out, j = {}, k - self.k0
        for i, (burn, last) in sorted(self.burns.items()):
            if j >= last:
                continue
            rest = burn[j:last]
            on = np.flatnonzero(np.linalg.norm(rest, axis=1) > 0.0)
            dv = np.vstack([rest[on] * dt, np.zeros((1, 3))])
            ts = np.append(on, last - j) * dt
            out[i] = Transfer(dv, ts, float(np.abs(dv).sum()), float(last - j) * dt, 1)
        return out

    def _plan(self, eng, cancel) -> list[dict]:
        state = swarm_state_from_engine(eng)
        try:
            dec = ladder.run_ladder(
                state, eng.scenario, cancel, self.inflight(eng.k, eng.dt), eng.believed
            )
        except (CertificateCancelled, TransferCancelled) as exc:
            raise RunCancelled(f"run cancelled while planning at tick {eng.k}") from exc
        self.level = dec.level
        out = [{"type": "RECOVERY_LEVEL", "payload": dec.payload()}]
        if dec.plan is None or dec.cert is None or not dec.cert.passed:
            return out  # nothing certified: nothing executes (the seats and burns stay)
        out.append({"type": "CERTIFICATE", "payload": dec.cert.event_payload()})
        return out + self._execute(eng, dec.plan)

    def _execute(self, eng, plan) -> list[dict]:
        """Apply a CERTIFIED plan exactly as certify.certify simulated it."""
        f, t = eng.faults, eng.k * eng.dt
        items = {it.sat_id: it for it in plan.items}
        for i, it in items.items():
            st = f.status[i]
            if st not in DEAD and commandable(st, f.declared[i]) and not passive(f.sats[i]):
                eng.refs[i] = propagate(it.seat, t, eng.n)
        new = [list(items[i].roles) if i in items else list(r) for i, r in enumerate(eng.roles)]
        priority = [r for r in eng.scenario.role_priority if r in eng.scenario.roles]
        handoffs = handoff_events(eng.roles, new, f.status, priority)
        eng.roles = new
        movers = {i: it.transfer for i, it in items.items() if it.transfer is not None}
        self.k0, self.burns = eng.k, burn_schedule(movers, f.sats, eng.dt)
        self.off_plan = False
        return [{"type": "ROLE_HANDOFF", "payload": p} for p in handoffs]

    def state(self) -> dict:
        burns = {str(i): [b.tolist(), last] for i, (b, last) in sorted(self.burns.items())}
        return {"armed": self.armed, "k0": self.k0, "burns": burns, "level": self.level,
                "off_plan": self.off_plan}

    def load(self, d: dict) -> None:
        burns = {int(i): (np.array(b, dtype=float).reshape(-1, 3), int(last))
                 for i, (b, last) in d["burns"].items()}
        self.armed, self.k0, self.burns = bool(d["armed"]), int(d["k0"]), burns
        self.level = None if d["level"] is None else str(d["level"])
        self.off_plan = bool(d["off_plan"])


def attach(scenario) -> Recovery | None:
    rec = scenario.recovery
    return Recovery() if rec is not None and rec.ladder else None


def snapshot(eng) -> dict:
    return {} if eng.rec is None else {"recovery": eng.rec.state()}


def restore(eng, state: dict) -> Recovery | None:
    """Parsed recovery state (not applied); KeyError / ValueError on a bad snapshot."""
    if eng.rec is None:
        return None
    rec = Recovery()
    rec.load(state["recovery"])
    return rec
