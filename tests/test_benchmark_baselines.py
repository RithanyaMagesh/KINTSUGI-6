"""Baseline policies for the benchmark (GATES.md 2026-10-31 pre-registration):
`role_swap_only` (zero-Δv in-place re-election) and `wait_for_ground`
(hungarian held until the first ground pass), plus the Δv budget fields.
"""

import math
from pathlib import Path

import numpy as np
import pytest

import cubesat.allocate as allocate
import cubesat.sim as sim_module
from cubesat.benchmark import (
    enumerate_pairs,
    run_one,
    scenario_for_pair,
)
from cubesat.benchmark_policies import role_swap_only_replan
from cubesat.canon import canonical_log_hash
from cubesat.coverage import footprint_radius, target_grid
from cubesat.hcw import mean_motion, slot_initial_state
from cubesat.scenario import load_scenario

ROOT = Path(__file__).resolve().parents[1]
TWO_FAILURE = ROOT / "data" / "scenarios" / "two_failure.json"
TIMES = (1200.0, 1500.0)


@pytest.fixture(scope="module")
def base():
    return load_scenario(TWO_FAILURE)


def _final_tick(lines):
    return [ln for ln in lines if ln["state"] not in ("INIT", "SUMMARY")][-1]


@pytest.fixture(scope="module")
def swap_runs(base):
    """All 15 pairs under role_swap_only, run once and shared."""
    out = {}
    for pair in enumerate_pairs(6):
        out[pair] = run_one(scenario_for_pair(base, pair, TIMES), "role_swap_only")
    return out


def test_role_swap_only_holds_critical_roles_on_all_15_pairs(swap_runs):
    assert len(swap_runs) == 15
    for pair, lines in swap_runs.items():
        nominal = {s["role"] for s in _final_tick(lines)["sats"] if s["status"] == "NOMINAL"}
        assert {"leader", "downlink"} <= nominal, pair


def test_role_swap_only_spends_zero_dv(swap_runs):
    for pair, lines in swap_runs.items():
        worst = max(float(s["dv_used"]) for s in _final_tick(lines)["sats"])
        assert worst < 1e-6, (pair, worst)


def test_role_swap_only_survivors_keep_roles_except_the_promoted(swap_runs, base):
    for pair, lines in swap_runs.items():
        final = {s["id"]: s for s in _final_tick(lines)["sats"]}
        survivors = [i for i in range(6) if i not in pair]
        lost = [r for r in ("leader", "downlink") if base.roles.index(r) in pair]
        imagers = [i for i in survivors if base.roles[i] == "imager"]
        promoted = dict(zip(imagers, lost, strict=False))  # lowest-id imagers, in order
        for i in survivors:
            expected = promoted.get(i, base.roles[i])
            assert final[i]["role"] == expected, (pair, i)


def test_role_swap_only_deterministic(base):
    sc = scenario_for_pair(base, (0, 5), TIMES)
    first, second = run_one(sc, "role_swap_only"), run_one(sc, "role_swap_only")
    assert canonical_log_hash(first) == canonical_log_hash(second)


def test_role_swap_only_restores_seam(base):
    run_one(scenario_for_pair(base, (0, 1), TIMES), "role_swap_only")
    assert sim_module.replan is allocate.replan


def _replan_kwargs(base, roles):
    n = mean_motion(base.chief.altitude_km * 1000.0)
    amp = base.formation.radial_amp_km * 1000.0
    slots = [slot_initial_state(amp, amp, 2.0 * math.pi * j / 6.0, n) for j in range(len(roles))]
    return {
        "survivor_states": slots,
        "survivor_roles": roles,
        "survivor_fuel": [200.0] * len(roles),
        "obstacle_states": [],
        "original_roles": list(base.roles),
        "allocation": base.allocation,
        "base_amp_m": amp,
        "r_f": footprint_radius(
            base.chief.altitude_km * 1000.0, math.radians(base.sensor.fov_half_angle_deg)
        ),
        "grid": target_grid(base.sensor.grid_step_km * 1000.0, base.sensor.grid_extent_km * 1000.0),
        "n": n,
        "a_max": base.a_max_mps2,
        "t_replan": 1206.0,
        "current_slots": slots,
    }


def test_role_swap_only_rule_unit(base):
    """Leader dead: survivors imager x3 + downlink + imager -> the LOWEST-id imager
    becomes leader; downlink holder untouched; slots are the current slots."""
    roles = ["imager", "imager", "imager", "downlink", "imager"]
    kw = _replan_kwargs(base, roles)
    plan, pairs, total, method, max_transfer, cost = role_swap_only_replan(**kw)
    assert plan.seat_roles == ["leader", "imager", "imager", "downlink", "imager"]
    assert pairs == [(i, i) for i in range(5)]
    assert (total, max_transfer, method) == (0.0, 0.0, "role_swap_only")
    assert cost.shape == (5, 5)
    assert all(np.array_equal(a, b) for a, b in zip(plan.slots, kw["current_slots"], strict=True))


def test_role_swap_only_prefers_duplicated_role_for_promotion(base):
    """Both critical roles lost; survivors hold a unique 'relay' at the lowest id and
    two imagers: the duplicated role (imager) supplies the promotees, relay stays."""
    kw = _replan_kwargs(base, ["relay", "imager", "imager"])
    kw["original_roles"] = ["leader", "relay", "imager", "imager", "downlink"]
    plan, *_ = role_swap_only_replan(**kw)
    assert plan.seat_roles == ["relay", "leader", "downlink"]


def test_role_swap_only_nothing_lost_changes_nothing(base):
    roles = ["leader", "imager", "imager", "downlink"]
    plan, *_ = role_swap_only_replan(**_replan_kwargs(base, roles))
    assert plan.seat_roles == roles
