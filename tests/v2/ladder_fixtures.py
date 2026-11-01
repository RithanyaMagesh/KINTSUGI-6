"""Shared helpers for the recovery-ladder tests (Phase 5d-2). Not a test module."""

from __future__ import annotations

from certify_fixtures import PERIOD, scn

from cubesat.scenario import Scenario
from cubesat.sim_v2 import EngineV2


def ladder_scn(amp_km: float = 2.0, orbits: float = 3.0, **over) -> Scenario:
    """certify_fixtures.scn with the ladder on and `orbits` chief orbits of run."""
    over.setdefault("duration_s", orbits * PERIOD)
    rec = {"ladder": True, **over.pop("recovery", {})}
    return scn(amp_km, recovery=rec, **over)


def run_log(scenario: Scenario, injections=()) -> list[dict]:
    return list(EngineV2(scenario, list(injections)).run())


def events(lines, kind: str) -> list[tuple[float, dict]]:
    return [(ln["t"], e["payload"]) for ln in lines for e in ln.get("events", ())
            if e["type"] == kind]


def assert_every_plan_certified(lines) -> int:
    """The Task 5.G-d invariant: no v2 plan executes without a passed CERTIFICATE for the same
    level in the same tick, and every CERTIFICATE belongs to an executed RECOVERY_LEVEL.
    Returns the number of executed plans."""
    executed = 0
    for ln in lines:
        evs = ln.get("events", ())
        levels = [e["payload"] for e in evs if e["type"] == "RECOVERY_LEVEL"]
        certs = [e["payload"] for e in evs if e["type"] == "CERTIFICATE"]
        assert len(levels) <= 1 and len(certs) <= 1, ln["t"]
        if levels and levels[0]["level"] is not None:
            executed += 1
            assert certs and certs[0]["passed"] is True, (ln["t"], certs)
            assert certs[0]["level"] == levels[0]["level"]
        else:
            assert not certs, (ln["t"], certs)
    return executed
