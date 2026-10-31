"""Failure scheduling, per-sat status and heartbeat detection for EngineV2.

Phase 1 scope: failures fire at their tick and coast in the truth model; detection is the v1
heartbeat rule (K missed ticks); there is no recovery, so the mission state stays
FAILURE_DETECTED once anything is detected.
"""

from __future__ import annotations

from cubesat.scenario import Failure, FailureMode, Scenario
from cubesat.sim import (
    STATE_FAILURE_DETECTED,
    STATE_NOMINAL,
    STATUS_DEAD,
    STATUS_DEGRADED,
    STATUS_NOMINAL,
    STATUS_THRUSTER_OUT,
)

STATUS_REENTERED = "REENTERED"
_SILENT = (STATUS_DEAD, STATUS_REENTERED)  # no heartbeat
_EPS = 1e-9


def _order(f: Failure) -> tuple[float, int]:
    return (f.t, f.sat_id)


class Faults:
    """Status, failure schedule and detection bookkeeping for n sats (JSON-serialisable)."""

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
        if not self.fail_mode[i]:
            self.t_fail[i], self.fail_mode[i] = t, "REENTRY"
        return {"type": "REENTRY", "payload": {"sat_id": i, "t": t, "altitude_m": altitude_m}}

    def tick(self, t: float) -> list[dict]:
        """Fade onsets, failures due at t, heartbeats and detection; returns this tick's events."""
        events: list[dict] = []
        for f in [*self.scenario.failures, *self.injections]:
            fades = f.mode == FailureMode.EPS_DEGRADE and f.degrade_s > 0
            if (
                fades
                and f.t - f.degrade_s <= t + _EPS
                and f.t > t + _EPS
                and self.status[f.sat_id] == STATUS_NOMINAL
            ):
                self.status[f.sat_id] = STATUS_DEGRADED
                payload = {"sat_id": f.sat_id, "t_fail": f.t, "degrade_s": f.degrade_s}
                events.append({"type": "DEGRADE_START", "payload": payload})
        while self.fired < len(self.pending) and self.pending[self.fired].t <= t + _EPS:
            f = self.pending[self.fired]
            self.fired += 1
            i = f.sat_id
            thruster_out = f.mode == FailureMode.THRUSTER_OUT
            new = STATUS_THRUSTER_OUT if thruster_out else STATUS_DEAD
            if self.status[i] in (STATUS_DEAD, STATUS_REENTERED) or self.status[i] == new:
                continue
            self.status[i] = new
            self.t_fail[i], self.fail_mode[i] = f.t, f.mode.value
            if thruster_out:  # self-reported, like v1: no heartbeat misses needed
                self.declared[i] = True
                self.mission = STATE_FAILURE_DETECTED
                payload = {"sat_id": i, "mode": f.mode.value, "t_fail": f.t, "t_detect": t}
                payload["self_report"] = True
                events.append({"type": "FAILURE_DETECTED", "payload": payload})
        for i, status in enumerate(self.status):
            self.missed[i] = self.missed[i] + 1 if status in _SILENT else 0
            if (
                status in _SILENT
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
        }

    def load(self, state: dict) -> None:
        for name in ("status", "missed", "declared", "t_fail", "fail_mode", "mission", "fired"):
            setattr(self, name, state[name])
        self.pending = [Failure.model_validate(f) for f in state["pending"]]
        self.injections = [Failure.model_validate(f) for f in state["injections"]]
