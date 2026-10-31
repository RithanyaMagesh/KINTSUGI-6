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
from cubesat import ground
from cubesat.benchmark import (
    CUBESAT_TANK_DV_MPS,
    _policies_summary,
    _scenario_for_policy,
    _write_log,
    enumerate_pairs,
    metrics_from_log,
    run_one,
    scenario_for_pair,
    wait_for_ground_plan,
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


# --- wait_for_ground ---------------------------------------------------------

ORBIT_S = 2 * math.pi / mean_motion(500_000.0)


def test_wait_for_ground_delay_from_ground_model(base):
    sc = scenario_for_pair(base, (1, 2), TIMES)
    out = _scenario_for_policy(sc, "wait_for_ground")
    delay = ground.wait_to_next_pass(1200.0)
    assert out.recovery_delay_s == pytest.approx(delay)
    assert out.recovery_enabled is True
    assert out.duration_s >= 1200.0 + delay + 3 * ORBIT_S - 2.0
    assert round(out.duration_s / out.dt_s) + 1 <= 100_000
    assert wait_for_ground_plan(sc)["truncated"] is False


def test_wait_for_ground_truncation_is_capped_and_flagged(base, monkeypatch):
    monkeypatch.setattr(ground, "wait_to_next_pass", lambda *a, **k: 80_000.0)
    sc = scenario_for_pair(base, (1, 2), TIMES)
    plan = wait_for_ground_plan(sc)
    assert plan["truncated"] is True
    assert round(plan["duration_s"] / sc.dt_s) + 1 <= 100_000
    assert plan["duration_s"] <= 86_400.0
    assert _scenario_for_policy(sc, "wait_for_ground").duration_s == plan["duration_s"]


def test_wait_for_ground_holds_in_failure_detected_until_delay(base):
    sc = scenario_for_pair(base, (0, 5), TIMES)
    lines = run_one(sc, "wait_for_ground")
    ticks = [ln for ln in lines if ln["state"] not in ("INIT", "SUMMARY")]
    delay = ground.wait_to_next_pass(1200.0)
    t_detect = next(t["t"] for t in ticks if t["state"] == "FAILURE_DETECTED")
    t_replan = next(t["t"] for t in ticks if t["state"] == "REPLANNING")
    assert t_replan >= t_detect + delay - 1e-9
    held = [t["state"] for t in ticks if t_detect <= t["t"] < t_detect + delay - 1e-9]
    assert held and set(held) == {"FAILURE_DETECTED"}


def test_wait_for_ground_vacancy_at_least_delay(base, tmp_path):
    sc = scenario_for_pair(base, (0, 5), TIMES)  # leader AND downlink die
    out = _scenario_for_policy(sc, "wait_for_ground")
    path = tmp_path / "wfg.jsonl"
    _write_log(run_one(sc, "wait_for_ground"), path)
    m = metrics_from_log(path, first_failure_t=1200.0, dead_ids=[0, 5], duration_s=out.duration_s)
    delay = ground.wait_to_next_pass(1200.0)
    assert m["critical_roles_held_end"] is True
    assert m["critical_vacancy_s"] >= delay


# --- dv budget fields --------------------------------------------------------

def _dv_log(tmp_path, dvs):
    ticks = [
        {"v": 1, "t": float(t), "state": "NOMINAL", "coverage": 0.3, "min_sep": 5000.0,
         "sats": [{"id": i, "role": "imager", "status": "NOMINAL", "r": [0.0, 0.0, 0.0],
                   "v": [0.0, 0.0, 0.0], "dv_used": dv * t / 2.0} for i, dv in enumerate(dvs)]}
        for t in (0, 2)
    ]
    lines = [{"v": 1, "t": 0.0, "state": "INIT", "scenario": "x", "seed": 0, "n_sats": len(dvs)}]
    lines += ticks + [{"v": 1, "t": 2.0, "state": "SUMMARY", "coverage_mean_last_orbit": 0.3}]
    path = tmp_path / "dv.jsonl"
    _write_log(lines, path)
    return path


def test_cubesat_tank_constant_value():
    assert CUBESAT_TANK_DV_MPS == pytest.approx(40 * 9.80665 * math.log(4 / 3.8))
    assert CUBESAT_TANK_DV_MPS == pytest.approx(20.12, abs=0.01)


def test_dv_budget_fields_synthetic(tmp_path):
    path = _dv_log(tmp_path, [0.0, 10.0, 50.0])  # worst 50 m/s
    m = metrics_from_log(
        path, first_failure_t=0.0, dead_ids=[], duration_s=2.0, dv_budget_mps=200.0
    )
    assert m["dv_pct_of_scenario_budget"] == pytest.approx(25.0)
    assert m["dv_within_scenario_budget"] is True
    assert m["dv_pct_of_cubesat_tank"] == pytest.approx(100.0 * 50.0 / CUBESAT_TANK_DV_MPS)
    assert m["dv_within_cubesat_tank"] is False
    ok = metrics_from_log(
        _dv_log(tmp_path, [5.0]), first_failure_t=0.0, dead_ids=[], duration_s=2.0,
        dv_budget_mps=4.0,
    )
    assert ok["dv_within_scenario_budget"] is False  # 5 > 4
    assert ok["dv_within_cubesat_tank"] is True


def test_dv_summary_rollups():
    def row(policy, scen, tank):
        return {
            "policy": policy, "coverage_mean_last_orbit": 0.27, "total_dv_mps": 1.0,
            "per_sat_dv_mps": [0.5], "min_sep_survivor_dead_m": 3000.0,
            "gain_vs_do_nothing_pts": 0.0, "critical_roles_held_end": True,
            "critical_seat_frac": 1.0, "critical_vacancy_s": 0.0, "imagers_end": 2,
            "dv_within_scenario_budget": scen, "dv_within_cubesat_tank": tank,
        }
    rows = [row("hungarian", True, False), row("hungarian", False, False),
            row("hungarian", True, True)]
    s = _policies_summary(rows, ["hungarian"])["hungarian"]
    assert s["pairs_within_scenario_budget"] == 2
    assert s["pairs_within_cubesat_tank"] == 1
