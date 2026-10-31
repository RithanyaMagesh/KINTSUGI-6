"""Failure scheduling, per-sat status and heartbeat detection for EngineV2.

Failures fire at their tick and act as resource damage on the per-sat SatState
(cubesat/spacecraft.py); detection is the v1 heartbeat rule (K missed ticks) for every silent
sat; there is no recovery, so the mission state stays FAILURE_DETECTED once anything is
detected. Self-reported (THRUSTER_OUT, PAYLOAD_FAIL): the sat tells ground at once if its radio
works. PARTIAL_THRUST and THRUSTER_STUCK_OPEN are silent faults (status DEGRADED, no event):
only a motion residual can see them (Phase 4).
"""

from __future__ import annotations

import numpy as np

from cubesat.scenario import Failure, FailureMode, Scenario
from cubesat.sim import (
    STATE_FAILURE_DETECTED,
    STATE_NOMINAL,
    STATUS_DEAD,
    STATUS_DEGRADED,
    STATUS_NOMINAL,
    STATUS_THRUSTER_OUT,
)
from cubesat.spacecraft import SatState, apply_failure

STATUS_REENTERED = "REENTERED"
STATUS_PAYLOAD_FAILED = "PAYLOAD_FAILED"  # still flies, no imaging
STATUS_RADIO_SILENT = "RADIO_SILENT"  # flies, silent heartbeat
STATUS_FUEL_DEPLETED = "FUEL_DEPLETED"  # flies and images, cannot thrust (tank empty)
_EPS = 1e-9
# A new failure only ever raises the label; DEAD and REENTERED are terminal.
_RANK = {
    STATUS_NOMINAL: 0,
    STATUS_DEGRADED: 1,
    STATUS_PAYLOAD_FAILED: 2,
    STATUS_THRUSTER_OUT: 3,
    STATUS_FUEL_DEPLETED: 4,
    STATUS_RADIO_SILENT: 5,
    STATUS_DEAD: 6,
    STATUS_REENTERED: 7,
}
_TERMINAL = (STATUS_DEAD, STATUS_REENTERED)
_MODE_STATUS = {
    FailureMode.THRUSTER_OUT: STATUS_THRUSTER_OUT,
    FailureMode.PARTIAL_THRUST: STATUS_DEGRADED,
    FailureMode.THRUSTER_STUCK_OPEN: STATUS_DEGRADED,
    FailureMode.PAYLOAD_FAIL: STATUS_PAYLOAD_FAILED,
    FailureMode.RADIO_FAIL: STATUS_RADIO_SILENT,
}  # DEAD and EPS_DEGRADE map to STATUS_DEAD


def _order(f: Failure) -> tuple[float, int]:
    return (f.t, f.sat_id)


class Faults:
    """Status, failure schedule and detection bookkeeping for n sats (JSON-serialisable).
    `declared[i]` latches only the heartbeat (silence) declaration; a self-report never sets
    it, so a benign self-reported fault cannot hide a later death or radio loss."""

    def __init__(self, scenario: Scenario) -> None:
        n = scenario.n_sats
        self.scenario = scenario
        self.status = [STATUS_NOMINAL] * n
        self.missed = [0] * n
        self.declared = [False] * n
        self.t_fail = [0.0] * n
        self.fail_mode = [""] * n
        self.mission = STATE_NOMINAL
        self.pending = sorted(scenario.failures, key=_order)
        self.fired = 0
        self.injections: list[Failure] = []
        self.sats = [SatState.from_scenario(scenario) for _ in range(n)]
        self.fuel_out = [False] * n  # FUEL_DEPLETED already reported
        self.fade_done = [False] * n  # DEGRADE_START already announced

    def inject(self, failure: Failure, now: float) -> None:
        """Resolve `failure` against `now` and record the RESOLVED failure.

        The failure time is clamped to now, and an EPS_DEGRADE fade onset (t - degrade_s) is
        clamped to now by shortening degrade_s. Replaying `injections` from t=0 therefore takes
        exactly the path the live engine took."""
        if failure.sat_id >= self.scenario.n_sats:
            raise ValueError(f"sat_id={failure.sat_id}, only {self.scenario.n_sats} sats exist")
        t_eff = max(failure.t, now)
        degrade_s = failure.degrade_s
        if failure.mode == FailureMode.EPS_DEGRADE and degrade_s > 0:
            degrade_s = t_eff - max(failure.t - degrade_s, now)
        if (t_eff, degrade_s) != (failure.t, failure.degrade_s):
            failure = failure.model_copy(update={"t": t_eff, "degrade_s": degrade_s})
        self.injections.append(failure)
        # stable sort: scenario failures stay ahead of injections at equal (t, sat_id)
        rest = [*self.pending[self.fired :], failure]
        self.pending, self.fired = sorted(rest, key=_order), 0

    def mark_reentered(self, i: int, t: float, altitude_m: float) -> dict:
        self.status[i] = STATUS_REENTERED
        if self.sats[i].radio_ok:  # a sat that was still talking goes silent because of re-entry
            self.t_fail[i], self.fail_mode[i] = t, "REENTRY"
        return {"type": "REENTRY", "payload": {"sat_id": i, "t": t, "altitude_m": altitude_m}}

    def tick(self, t: float, vel_eci: np.ndarray) -> list[dict]:
        """Fade onsets, failures due at t, heartbeats and detection; returns this tick's events.
        vel_eci (N, 3): sat ECI velocities now; a stuck-open thruster fires along the failing
        sat's velocity direction at that instant (fixed in ECI afterwards)."""
        events: list[dict] = []
        for f in [*self.scenario.failures, *self.injections]:
            fades = f.mode == FailureMode.EPS_DEGRADE and f.degrade_s > 0
            if (
                fades
                and f.t - f.degrade_s <= t + _EPS
                and f.t > t + _EPS
                and not self.fade_done[f.sat_id]
                and _RANK[self.status[f.sat_id]] <= _RANK[STATUS_DEGRADED]  # not yet worse
            ):
                self.fade_done[f.sat_id] = True
                self.status[f.sat_id] = STATUS_DEGRADED
                payload = {"sat_id": f.sat_id, "t_fail": f.t, "degrade_s": f.degrade_s}
                events.append({"type": "DEGRADE_START", "payload": payload})
        while self.fired < len(self.pending) and self.pending[self.fired].t <= t + _EPS:
            f = self.pending[self.fired]
            self.fired += 1
            i = f.sat_id
            sat = self.sats[i]
            if self.status[i] in _TERMINAL:
                continue
            can_thrust, imaging = sat.k > 0.0, sat.payload_ok
            apply_failure(sat, f.mode, vel_eci[i])
            new = _MODE_STATUS.get(f.mode, STATUS_DEAD)
            raised = _RANK[new] > _RANK[self.status[i]]
            if raised:
                self.status[i] = new
            if raised or not self.fail_mode[i]:
                self.t_fail[i], self.fail_mode[i] = f.t, f.mode.value
            lost = (f.mode == FailureMode.THRUSTER_OUT and can_thrust) or (
                f.mode == FailureMode.PAYLOAD_FAIL and imaging
            )
            if sat.radio_ok and lost:  # self-reported, like v1
                self.mission = STATE_FAILURE_DETECTED
                payload = {"sat_id": i, "mode": f.mode.value, "t_fail": f.t, "t_detect": t}
                payload["self_report"] = True
                events.append({"type": "FAILURE_DETECTED", "payload": payload})
        for i, sat in enumerate(self.sats):
            if sat.depleted and not self.fuel_out[i] and self.status[i] not in _TERMINAL:
                self.fuel_out[i] = True  # reported once; an empty tank means no thrust (k = 0)
                sat.k = 0.0
                raised = _RANK[STATUS_FUEL_DEPLETED] > _RANK[self.status[i]]
                if raised:
                    self.status[i] = STATUS_FUEL_DEPLETED
                if raised or not self.fail_mode[i]:
                    self.t_fail[i], self.fail_mode[i] = t, STATUS_FUEL_DEPLETED
                if sat.radio_ok:  # self-reported like THRUSTER_OUT; a silent sat cannot
                    self.mission = STATE_FAILURE_DETECTED
                    payload = {"sat_id": i, "mode": STATUS_FUEL_DEPLETED, "t_fail": t}
                    payload.update(t_detect=t, self_report=True)
                    events.append({"type": "FAILURE_DETECTED", "payload": payload})
                    events.append({"type": "FUEL_DEPLETED", "payload": {"sat_id": i, "t": t}})
        for i, status in enumerate(self.status):
            silent = status == STATUS_REENTERED or not self.sats[i].radio_ok
            self.missed[i] = self.missed[i] + 1 if silent else 0
            if (
                silent
                and not self.declared[i]
                and self.missed[i] >= self.scenario.detection.missed_ticks_k
            ):
                self.declared[i] = True
                self.mission = STATE_FAILURE_DETECTED
                payload = {"sat_id": i, "mode": self.fail_mode[i], "t_fail": self.t_fail[i]}
                payload["t_detect"] = t
                events.append({"type": "FAILURE_DETECTED", "payload": payload})
        return events

    def state(self) -> dict:
        dump = lambda fs: [f.model_dump(mode="json") for f in fs]  # noqa: E731
        return {
            "status": self.status,
            "missed": self.missed,
            "declared": self.declared,
            "t_fail": self.t_fail,
            "fail_mode": self.fail_mode,
            "mission": self.mission,
            "pending": dump(self.pending),
            "fired": self.fired,
            "injections": dump(self.injections),
            "sats": [sat.to_dict() for sat in self.sats],
            "fuel_out": self.fuel_out,
            "fade_done": self.fade_done,
        }

    def load(self, state: dict) -> None:
        """Replace every field from `state`; raises ValueError and leaves self unchanged when
        a key is missing or malformed (old or partial snapshot)."""
        try:
            plain = {
                name: state[name]
                for name in ("status", "missed", "declared", "t_fail", "fail_mode", "mission")
                + ("fired", "fuel_out", "fade_done")
            }
            pending = [Failure.model_validate(f) for f in state["pending"]]
            injections = [Failure.model_validate(f) for f in state["injections"]]
            sats = [SatState.from_dict(d) for d in state["sats"]]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"bad faults state in snapshot: {exc!r}") from exc
        self.__dict__.update(plain, pending=pending, injections=injections, sats=sats)
