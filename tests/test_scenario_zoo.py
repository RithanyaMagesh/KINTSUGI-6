"""Scenario-zoo structural tests: single-failure N=4, cascading N=8, and the
EPS_DEGRADE smoke scenario.

Structural assertions only (detection counts, state-machine transitions, leader
re-election, coasting hazards, min separation) -- the >= 15-point coverage drop
target stays pinned to data/scenarios/two_failure.json in tests/test_fault.py
(research patch #2) and is deliberately not duplicated here.

Run data comes from data/scenarios/single_failure_n4.json (leader sat 0 goes
DEAD), data/scenarios/cascading_n8.json (cascading failures: two DEAD fires
drive two heartbeat replanning cycles, and sat 7 self-reports THRUSTER_OUT at
t = 2400 s -- Addendum v1.2), and data/scenarios/eps_leader_6sat.json (the
leader fades to DEGRADED from t = 600 and dies at t = 2400) via
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
EPS_LEADER_6SAT = ROOT / "data" / "scenarios" / "eps_leader_6sat.json"


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


@pytest.fixture(scope="module")
def eps_lines():
    return run_scenario(load_scenario(EPS_LEADER_6SAT))


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
    """Two DEAD fires are caught by heartbeat monitoring and sat 7 announces its
    own THRUSTER_OUT (Addendum v1.2 self-report, zero detection latency), so it
    triggers a third replan cycle at t = 2400 and its downlink role is
    re-elected onto a healthy sat while its own status stays THRUSTER_OUT (its
    stale role label on the log line is pre-existing behavior shared with DEAD
    sats). The second reconfiguration is still in progress at 2400, so the
    machine re-enters FAILURE_DETECTED from RECONFIGURING: two heartbeat cycles
    + one self-report cycle drive three replanning cycles into one final
    RECOVERED. Sat 7 keeps coasting ballistically after t = 2400 s (never
    frozen, AGENTS.md 5) and every sat stays a min-separation hazard
    throughout, including during reconfiguration transfers."""
    detected = _events(n8_lines, "FAILURE_DETECTED")
    assert len(detected) == 3
    assert detected[-1] == (
        2400.0,
        {"sat_id": 7, "mode": "THRUSTER_OUT", "t_fail": 2400.0, "t_detect": 2400.0,
         "self_report": True},
    )
    assignments = _events(n8_lines, "ASSIGNMENT")
    assert len(assignments) == 3
    transitions = _events(n8_lines, "STATE")
    assert [p["to"] for _t, p in transitions].count("RECOVERED") == 1

    # The self-report replan (t = 2402 recompute -> assignment at 2404):
    # sat 7 is excluded from assignable and the downlink role it loses is
    # re-elected onto a healthy sat.
    third_t, third = assignments[2]
    assert third_t == 2404.0
    assert 7 not in [a["sat_id"] for a in third["assignments"]]
    holder = next(a for a in third["assignments"] if a["role"] == "downlink")
    assert holder["sat_id"] != 7

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


def test_eps_leader_6sat_smoke_parses_and_runs(eps_lines):
    """Addendum v1.2 smoke: the committed EPS_DEGRADE scenario parses through
    the real schema and runs end to end -- sat 0 enters DEGRADED at t = 600
    (fade = 2400 - 1800, one DEGRADE_START event), keeps reporting and holding
    its seat until it dies at t = 2400 exactly like DEAD, and the leader role
    is re-elected onto a healthy sat by the recovery arc."""
    assert eps_lines[0]["state"] == "INIT"
    assert eps_lines[-1]["state"] == "SUMMARY"

    starts = _events(eps_lines, "DEGRADE_START")
    assert starts == [(600.0, {"sat_id": 0, "t_fail": 2400.0, "degrade_s": 1800.0})]

    ticks = _tick_lines(eps_lines)
    window = [line for line in ticks if 600.0 <= line["t"] < 2400.0]
    assert window
    assert all(line["sats"][0]["status"] == "DEGRADED" for line in window)
    assert all(line["state"] == "NOMINAL" for line in window)  # still reporting
    assert next(line for line in ticks if line["t"] == 2400.0)["sats"][0]["status"] == "DEAD"

    assignments = _events(eps_lines, "ASSIGNMENT")
    assert assignments
    reelected = [a for a in assignments[-1][1]["assignments"] if a["role"] == "leader"]
    assert len(reelected) == 1 and reelected[0]["sat_id"] != 0
    assert all(a["sat_id"] != 0 for _t, p in assignments for a in p["assignments"])
    assert "RECOVERED" in [line["state"] for line in ticks]


@pytest.mark.slow
def test_cascading_n8_run_is_byte_deterministic(n8_scenario):
    """AGENTS.md invariant 2: same scenario + seed => byte-identical log. Full
    double replay of the cascading run; slow because it runs the 8-sat scenario
    twice (excluded from the fast loop)."""
    first = run_scenario(n8_scenario)
    second = run_scenario(n8_scenario)
    assert first == second
