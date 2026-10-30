"""Tests for do-no-harm replanner guard (Priority 0 Item 2)."""

import math
from pathlib import Path

from cubesat.allocate import _coverage_estimate, replan
from cubesat.coverage import footprint_radius, target_grid
from cubesat.hcw import mean_motion
from cubesat.scenario import Scenario
from cubesat.sim import build_slots


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
    cov_status_quo = _coverage_estimate(
        surv_slots, surv_roles, r_f=r_f, grid=grid, n=n, t_replan=1500.0
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
