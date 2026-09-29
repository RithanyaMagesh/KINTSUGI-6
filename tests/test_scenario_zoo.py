"""Scenario-zoo structural tests: single-failure N=4 and cascading N=8 runs.

Structural assertions only (detection counts, state-machine transitions, leader
re-election, coasting hazards, min separation) -- the >= 15-point coverage drop
target stays pinned to data/scenarios/two_failure.json in tests/test_fault.py
(research patch #2) and is deliberately not duplicated here.

Run data comes from data/scenarios/single_failure_n4.json (leader sat 0 goes
DEAD) and data/scenarios/cascading_n8.json (cascading failures: two DEAD fires
drive two replanning cycles, and sat 7 goes THRUSTER_OUT at t = 2400 s) via
cubesat.sim.run_scenario -- no RNG, no wall clock (AGENTS.md 2), so the
module-scoped fixtures are exact replays.
"""

import math
from pathlib import Path

import pytest

from cubesat.scenario import load_scenario
from cubesat.sim import run_scenario

ROOT = Path(__file__).resolve().parents[1]
SINGLE_FAILURE_N4 = ROOT / "data" / "scenarios" / "single_failure_n4.json"
CASCADING_N8 = ROOT / "data" / "scenarios" / "cascading_n8.json"


def _tick_lines(lines):
    return [line for line in lines if line["state"] not in ("INIT", "SUMMARY")]


def _events(lines, event_type):
    return [
        (line["t"], line["event"]["payload"])
        for line in lines
        if "event" in line and line["event"]["type"] == event_type
    ]


@pytest.fixture(scope="module")
def n4_lines():
    return run_scenario(load_scenario(SINGLE_FAILURE_N4))


@pytest.fixture(scope="module")
def n8_scenario():
    return load_scenario(CASCADING_N8)


@pytest.fixture(scope="module")
def n8_lines(n8_scenario):
    return run_scenario(n8_scenario)


def test_leader_death_reelects_leader_n4(n4_lines):
    """The leader (sat 0) is the only failure: one detection, at least one
    replan, RECOVERED reached, and exactly one surviving sat ends the run as
    leader -- a sat that is not the dead one (re-election, MASTER_PROMPT 3.5)."""
    detected = _events(n4_lines, "FAILURE_DETECTED")
    assert len(detected) == 1
    _t, payload = detected[0]
    assert payload["sat_id"] == 0
    assert payload["mode"] == "DEAD"
    assert len(_events(n4_lines, "ASSIGNMENT")) >= 1
    ticks = _tick_lines(n4_lines)
    assert "RECOVERED" in [line["state"] for line in ticks]
    leaders = [
        sat["id"]
        for sat in ticks[-1]["sats"]
        if sat["status"] == "NOMINAL" and sat["role"] == "leader"
    ]
    assert len(leaders) == 1
    assert leaders[0] != 0


def test_cascading_n8_two_replan_cycles_one_recovery(n8_scenario, n8_lines):
    """Two DEAD fires are caught by heartbeat monitoring and drive exactly two
    replanning cycles into one final RECOVERED. The THRUSTER_OUT sat keeps
    reporting its heartbeat, so heartbeat detection can never catch it -- the
    count below is the honest detection count, not a missed failure. Sat 7
    keeps coasting ballistically after t = 2400 s (never frozen, AGENTS.md 5)
    and every sat stays a min-separation hazard throughout, including during
    reconfiguration transfers."""
    assert len(_events(n8_lines, "FAILURE_DETECTED")) == 2
    assert len(_events(n8_lines, "ASSIGNMENT")) == 2
    transitions = _events(n8_lines, "STATE")
    assert [p["to"] for _t, p in transitions].count("RECOVERED") == 1

    ticks = _tick_lines(n8_lines)
    assert ticks[-1]["sats"][7]["status"] == "THRUSTER_OUT"
    r_after_fire = next(line for line in ticks if line["t"] > 2400.0)["sats"][7]["r"]
    r_late = ticks[-1]["sats"][7]["r"]
    assert math.dist(r_after_fire, r_late) > 1000.0

    seps = [(line["t"], line["min_sep"]) for line in ticks]
    worst_t, worst = min(seps, key=lambda x: x[1])
    threshold = n8_scenario.allocation.min_sep_km * 1000.0
    print(
        f"test_cascading_n8_two_replan_cycles_one_recovery: worst min_sep = "
        f"{worst:.1f} m at t = {worst_t:.0f} s (threshold {threshold:.0f} m, "
        f"{len(seps)} ticks incl. reconfiguration transfers)"
    )
    assert worst >= threshold


@pytest.mark.slow
def test_cascading_n8_run_is_byte_deterministic(n8_scenario):
    """AGENTS.md invariant 2: same scenario + seed => byte-identical log. Full
    double replay of the cascading run; slow because it runs the 8-sat scenario
    twice (excluded from the fast loop)."""
    first = run_scenario(n8_scenario)
    second = run_scenario(n8_scenario)
    assert first == second
