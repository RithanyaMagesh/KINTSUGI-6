"""P1 Pareto sweep tests (docs/ENDGAME_PLAN.md section 4, test-first).

The two required names:
    test_pareto_sweep_points_deterministic
    test_pareto_coverage_monotone_in_dv_budget

Zero core diff: the sweep only produces allocation.model_copy variants through
the P0 driver's run_one seam. No RNG, no wall clock (AGENTS.md invariant 2).
"""

import math
from pathlib import Path

import pytest

from cubesat.allocate import _reachability_ok
from cubesat.benchmark import FAILURE_TIMES, run_one, scenario_for_pair
from cubesat.hcw import mean_motion, slot_initial_state
from cubesat.pareto import (
    W1_FIXED,
    W3_FIXED,
    enumerate_grid_points,
    scenario_for_point,
)
from cubesat.scenario import load_scenario

ROOT = Path(__file__).resolve().parents[1]
TWO_FAILURE = ROOT / "data" / "scenarios" / "two_failure.json"


@pytest.fixture(scope="module")
def scenario():
    return load_scenario(TWO_FAILURE)


def test_pareto_sweep_points_deterministic(scenario):
    """ENDGAME_PLAN 4: every sweep point is its own deterministic scenario
    variant through the P0 driver -- one grid point (w2=1.0, dv=100) replayed
    twice in-process gives byte-identical logs (the P0 double-replay pattern).
    Also pins the 12-point grid itself (4 w2 x 3 dv, fixed w1/w3)."""
    points = enumerate_grid_points()
    assert points == [
        (0.1, 50.0), (0.1, 100.0), (0.1, 200.0),
        (0.5, 50.0), (0.5, 100.0), (0.5, 200.0),
        (1.0, 50.0), (1.0, 100.0), (1.0, 200.0),
        (2.0, 50.0), (2.0, 100.0), (2.0, 200.0),
    ]
    assert W1_FIXED == 1.0 and W3_FIXED == 2.0
    variant = scenario_for_point(scenario, 1.0, 100.0)
    assert variant.allocation.w1 == 1.0
    assert variant.allocation.w2 == 1.0
    assert variant.allocation.w3 == 2.0
    assert variant.allocation.dv_budget_mps == 100.0
    pair_scenario = scenario_for_pair(variant, (0, 1), FAILURE_TIMES)
    first = run_one(pair_scenario, "hungarian")
    second = run_one(pair_scenario, "hungarian")
    assert first == second


def test_pareto_coverage_monotone_in_dv_budget(scenario):
    """ENDGAME_PLAN 4 (weakly monotone): a larger budget only enlarges the
    feasible sweep set -- the filters at allocate.py (_reachability_ok) are
    conjunctions of threshold checks, so feasibility at 50 m/s implies
    feasibility at 200 m/s for every formation candidate; end-to-end, pair
    (0,1) hungarian coverage at dv=50 must not exceed coverage at dv=200."""
    n = mean_motion(scenario.chief.altitude_km * 1000.0)
    amp = scenario.formation.radial_amp_km * 1000.0
    survivors = [slot_initial_state(amp, amp, 2.0 * math.pi * j / 6.0, n) for j in (2, 3, 4, 5)]
    t_replan = 1210.0
    for phi0_deg in scenario.allocation.phase_sweep_deg:
        phi0 = math.radians(phi0_deg)
        slots = [
            slot_initial_state(amp, amp, phi0 + 2.0 * math.pi * j / 4.0, n) for j in range(4)
        ]
        feasible_50 = _reachability_ok(
            survivors, slots, a_max=scenario.a_max_mps2,
            dv_budget_mps=50.0, n=n, t_replan=t_replan,
        )
        feasible_200 = _reachability_ok(
            survivors, slots, a_max=scenario.a_max_mps2,
            dv_budget_mps=200.0, n=n, t_replan=t_replan,
        )
        assert not (feasible_50 and not feasible_200), f"budget 50 feasible, 200 not: {phi0_deg}"
    pair = (0, 1)
    outcomes = {}
    for dv in (50.0, 200.0):
        variant = scenario_for_point(scenario, scenario.allocation.w2, dv)
        try:
            lines = run_one(scenario_for_pair(variant, pair, FAILURE_TIMES), "hungarian")
        except RuntimeError as exc:
            assert "no feasible survivor formation" in str(exc)
            outcomes[dv] = None  # measured infeasibility: feasible set smaller
        else:
            summary = [ln for ln in lines if ln["state"] == "SUMMARY"]
            outcomes[dv] = float(summary[-1]["coverage_mean_last_orbit"])
    if outcomes[50.0] is not None:
        assert outcomes[50.0] <= outcomes[200.0]
    else:
        # Infeasible at 50 m/s but run at 200 m/s: the larger budget strictly
        # enlarged the feasible set -- the weak-monotone property, measured.
        assert outcomes[200.0] is not None
