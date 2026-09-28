"""Two-step allocation tests (docs/MASTER_PROMPT.md sections 3.3 and 3.8, gate G4).

Tests-first: cubesat.allocate does not exist yet, so this file fails collection with
ModuleNotFoundError until G4 implements it. Required contract:

    cubesat.allocate.seat_roles_for(survivor_roles, original_roles) -> list[str]
        k seat roles: survivors' roles, with critical (unique in original_roles)
        roles whose holder died re-elected onto seats taken from the majority
        role; imager seats interleaved onto even indices so the coverage-bearing
        seats are as spread as the k evenly-spaced slots allow.
    cubesat.allocate.build_cost_matrix(survivor_pos, seat_pos, fuel,
        survivor_roles, seat_roles, *, w1, w2, w3) -> np.ndarray (k, m)
        C[i,j] = w1*dist_norm + w2*dist_norm/fuel_i + w3*role_mismatch; the first
        two terms normalized to [0, 1] across the matrix; tiny index-based
        epsilon for tie-breaking (rows = survivors, cols = seats).
    cubesat.allocate.solve_assignment(cost, method="hungarian")
        -> (pairs [(row, col)], cost_total, method_used)
        Rectangular (k x m); deterministic; "greedy" = nearest-seat fallback.
    cubesat.allocate.replan(survivor_states, survivor_roles, survivor_fuel,
        obstacle_states, original_roles, allocation, base_amp_m, r_f, grid,
        n, a_max, t_replan)
        -> (FormationPlan, pairs, cost_total, method, max_transfer_m, cost)
        Step 1: survivor-formation sweep over (amplitude multiplier, phase
        offset), feasible iff min separation (obstacles included) and a perfect
        delta-v-reachable matching exist; maximizes measured coverage. Step 2:
        the assignment above.

Required test names (MASTER_PROMPT 3.8): test_hungarian_deterministic,
test_rectangular_assignment, test_leader_reelection, test_greedy_fallback_not_better.

All quantities SI (AGENTS.md 3), LVLH frame (AGENTS.md 4); no wall clock, no RNG
(AGENTS.md 2).
"""

import json
import math
from pathlib import Path

import numpy as np
import pytest

from cubesat.allocate import (
    build_cost_matrix,
    replan,
    seat_roles_for,
    solve_assignment,
)
from cubesat.coverage import footprint_radius, target_grid
from cubesat.hcw import mean_motion, propagate
from cubesat.scenario import load_scenario
from cubesat.sim import build_slots, run_scenario

ROOT = Path(__file__).resolve().parents[1]
NOMINAL = ROOT / "data" / "scenarios" / "nominal.json"
TWO_FAILURE = ROOT / "data" / "scenarios" / "two_failure.json"

T_REPLAN = 1510.0  # s, just after the 2nd two_failure detection (1504 s + 1 tick)


def _replan_inputs():
    """Real replan inputs for two_failure just after the 2nd failure is detected:
    sats 1, 2 (imagers) dead and coasting; survivors 0 (leader), 3, 4 (imagers),
    5 (downlink) hold their original slots."""
    scenario = load_scenario(TWO_FAILURE)
    n = mean_motion(scenario.chief.altitude_km * 1000.0)
    slots = build_slots(scenario, n)
    survivors = [0, 3, 4, 5]
    survivor_states = [np.asarray(propagate(slots[i], T_REPLAN, n)) for i in survivors]
    obstacle_states = [np.asarray(propagate(slots[i], T_REPLAN, n)) for i in (1, 2)]
    fuel = [scenario.allocation.dv_budget_mps] * len(survivors)
    return scenario, n, survivor_states, obstacle_states, fuel


def _cost_via_replan():
    """Cost matrix produced by the real step-1 + step-2 pipeline on the geometry
    above (also exercises the formation sweep and its feasibility gates)."""
    scenario, n, surv, obs, fuel = _replan_inputs()
    r_f = footprint_radius(
        scenario.chief.altitude_km * 1000.0,
        math.radians(scenario.sensor.fov_half_angle_deg),
    )
    grid = target_grid(
        scenario.sensor.grid_step_km * 1000.0, scenario.sensor.grid_extent_km * 1000.0
    )
    plan, _pairs, _total, _method, _max_transfer, cost = replan(
        surv,
        [scenario.roles[i] for i in (0, 3, 4, 5)],
        fuel,
        obs,
        scenario.roles,
        scenario.allocation,
        scenario.formation.radial_amp_km * 1000.0,
        r_f,
        grid,
        n,
        scenario.a_max_mps2,
        T_REPLAN,
    )
    return plan, cost


def test_hungarian_deterministic():
    """MASTER_PROMPT 3.3 must-verify: same input -> identical assignment over 100 runs
    (scipy docs are silent on ties; research patch keeps this test). The cost matrix
    comes from the real two_failure geometry, so the guard covers the cost pipeline;
    a hand-tied matrix additionally pins the index-epsilon behavior."""
    _plan, cost = _cost_via_replan()
    first_pairs, first_total, first_method = solve_assignment(cost)
    assert first_method == "hungarian"
    for _ in range(99):
        pairs, total, method = solve_assignment(cost)
        assert pairs == first_pairs
        assert total == first_total  # exact float identity, not approx
        assert method == first_method

    # Fully tied 2x2 matrix: the assignment is still returned deterministically.
    tied = np.ones((2, 2))
    for _ in range(100):
        pairs, total, _ = solve_assignment(tied)
        assert pairs == [(0, 0), (1, 1)]
        assert total == pytest.approx(2.0)


def test_rectangular_assignment():
    """MASTER_PROMPT 3.3: rectangular case returns k assignments for a k x m matrix
    (k survivors, m > k seats); rows all matched, columns distinct."""
    surv_pos = np.array([[0.0, 0.0, 0.0], [1000.0, 0.0, 0.0], [2000.0, 0.0, 0.0]])
    seat_pos = np.array(
        [
            [0.0, 0.0, 0.0],
            [500.0, 0.0, 0.0],
            [1500.0, 0.0, 0.0],
            [2500.0, 0.0, 0.0],
            [3000.0, 0.0, 0.0],
        ]
    )
    cost = build_cost_matrix(
        surv_pos,
        seat_pos,
        [100.0, 100.0, 100.0],
        ["imager", "imager", "downlink"],
        ["imager", "imager", "imager", "downlink", "leader"],
        w1=1.0,
        w2=0.5,
        w3=2.0,
    )
    assert cost.shape == (3, 5)
    pairs, total, method = solve_assignment(cost)
    assert method == "hungarian"
    assert len(pairs) == 3
    assert sorted(r for r, _ in pairs) == [0, 1, 2]
    assert len({c for _, c in pairs}) == 3
    # Hand-checkable optimum: survivors 0/1 take their nearest imager seats, and
    # survivor 2 (downlink) ties on distance between seats 2/3 and role_mismatch
    # (w3) resolves it onto the downlink seat.
    assert pairs == [(0, 0), (1, 1), (2, 3)]
    assert total == pytest.approx(float(cost[0, 0] + cost[1, 1] + cost[2, 3]))


def test_leader_reelection(tmp_path):
    """MASTER_PROMPT 3.3: leader-failure scenario re-elects a leader -- after the
    replanning cycle exactly one assigned sat carries the leader role and it is
    not the dead sat (MASTER_PROMPT 3.8)."""
    payload = json.loads(NOMINAL.read_text(encoding="utf-8"))
    payload["name"] = "leader_death"
    payload["duration_s"] = 600.0
    payload["failures"] = [{"t": 100.0, "sat_id": 0, "mode": "DEAD"}]
    path = tmp_path / "leader_death.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    lines = run_scenario(load_scenario(path))

    assignments = [
        line["event"]["payload"]["assignments"]
        for line in lines
        if "event" in line and line["event"]["type"] == "ASSIGNMENT"
    ]
    assert len(assignments) == 1
    leaders = [a for a in assignments[0] if a["role"] == "leader"]
    assert len(leaders) == 1
    assert leaders[0]["sat_id"] != 0
    assert 0 not in [a["sat_id"] for a in assignments[0]]


def test_greedy_fallback_not_better():
    """MASTER_PROMPT 3.3: the greedy nearest-seat fallback is worse-or-equal in cost
    to the Hungarian optimum on the same cost matrix."""
    _plan, cost = _cost_via_replan()
    _, hungarian_total, _ = solve_assignment(cost)
    _, greedy_total, greedy_method = solve_assignment(cost, method="greedy")
    assert greedy_method == "greedy"
    assert greedy_total >= hungarian_total - 1e-12


def test_seat_roles_reelects_critical_roles():
    """Critical (unique) roles whose holder died take seats from the majority role;
    surviving critical roles keep theirs; imager seats land on even indices."""
    # Leader + one imager dead, downlink alive: re-elect leader, keep downlink.
    assert seat_roles_for(["imager", "imager", "imager", "downlink"],
                         ["leader", "imager", "imager", "imager", "imager", "downlink"]) == [
        "imager", "leader", "imager", "downlink"]
    # Two imagers dead, leader + downlink alive: no re-election needed.
    assert seat_roles_for(["leader", "imager", "imager", "downlink"],
                          ["leader", "imager", "imager", "imager", "imager", "downlink"]) == [
        "imager", "leader", "imager", "downlink"]
    # Leader + downlink dead, four imagers survive: both critical roles re-elected.
    assert seat_roles_for(["imager", "imager", "imager", "imager"],
                          ["leader", "imager", "imager", "imager", "imager", "downlink"]) == [
        "imager", "leader", "imager", "downlink"]
