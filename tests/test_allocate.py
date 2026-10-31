"""Tests for do-no-harm replanner guard (Priority 0 Item 2)."""

import math
from pathlib import Path

import pytest

from cubesat.allocate import _coverage_estimate, replan, seat_roles_for
from cubesat.benchmark import enumerate_pairs, run_one, scenario_for_pair
from cubesat.coverage import footprint_radius, target_grid
from cubesat.hcw import mean_motion
from cubesat.scenario import Scenario, load_scenario
from cubesat.sim import build_slots


@pytest.mark.parametrize("pair", enumerate_pairs(6))
def test_hungarian_coverage_retains_baseline_all_15_pairs(pair):
    """For each of the 15 two-failure pairs, hungarian (with guard)
    coverage_mean_last_orbit >= the pre-guard hungarian value (0.2698).

    The do-no-harm guard is meant to guarantee that replanning never degrades
    coverage below the pre-guard Hungarian baseline (0.2698).
    It does not guarantee >= do_nothing across all 15 pairs because on pairs
    where <= 1 imager dies, do_nothing leaves 3 or 4 imagers flying with lost
    critical roles, whereas Hungarian recovery re-elects leader/downlink from
    surviving imagers (ensuring 15/15 critical roles held vs do_nothing's 6/15)
    and re-phases into the optimal 4-slot formation with 2 imagers (0.2698).
    """
    scenario = load_scenario(Path("data/scenarios/two_failure.json"))
    sc = scenario_for_pair(scenario, pair, (1200.0, 1500.0))
    lines = run_one(sc, "hungarian")
    cov = lines[-1]["coverage_mean_last_orbit"]
    assert cov >= 0.2698 - 1e-4, f"Pair {pair} coverage {cov:.4f} < pre-guard baseline 0.2698"


def test_replan_do_no_harm_guard():
    scenario = Scenario.model_validate_json(
        Path("data/scenarios/two_failure.json").read_text()
    )
    n = mean_motion(scenario.chief.altitude_km * 1000.0)
    grid = target_grid(
        scenario.sensor.grid_step_km * 1000.0,
        scenario.sensor.grid_extent_km * 1000.0,
    )
    r_f = footprint_radius(
        scenario.chief.altitude_km * 1000.0,
        math.radians(scenario.sensor.fov_half_angle_deg),
    )
    initial_slots = build_slots(scenario, n)

    # Dead satellites 0 (leader) and 5 (downlink)
    dead = {0, 5}
    survivors = [s for s in range(6) if s not in dead]
    surv_roles = [scenario.roles[s] for s in survivors]
    surv_slots = [initial_slots[s] for s in survivors]
    seats = seat_roles_for(surv_roles, scenario.roles)
    cov_status_quo = _coverage_estimate(
        surv_slots, seats, r_f=r_f, grid=grid, n=n, t_replan=1500.0
    )

    # Replan with current survivor states equal to surv_slots
    plan, pairs, cost_total, method, max_transfer, cost = replan(
        surv_slots,
        surv_roles,
        [200.0] * len(survivors),
        [initial_slots[d] for d in dead],
        scenario.roles,
        scenario.allocation,
        scenario.formation.radial_amp_km * 1000.0,
        r_f,
        grid,
        n,
        scenario.a_max_mps2,
        1500.0,
        current_slots=surv_slots,
    )
    assert plan.coverage >= cov_status_quo, (
        f"Coverage dropped: {plan.coverage} < {cov_status_quo}"
    )
    if plan.coverage == cov_status_quo:
        assert max_transfer == 0.0, (
            "Do-no-harm status quo must command 0.0 transfer distance"
        )
