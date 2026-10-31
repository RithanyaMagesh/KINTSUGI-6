"""Phase 5c.3: the committed LP-vs-PD table and fuzz artifacts (data/eval/)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cubesat.transfer_report import main

ART = Path("data/eval/lp_vs_pd_dv_table.json")
REF, F2K = "reference_8km_leader", "formation_2km_slot0_to_slot1"


def _rows():
    return json.loads(ART.read_text())["rows"]


def _row(case, a, orbits):
    return next(
        r for r in _rows() if r["case"] == case and r["a_max_mps2"] == a and r["T_orbits"] == orbits
    )


def test_artifact_has_command_and_every_cell():
    rep = json.loads(ART.read_text())
    assert rep["command"] == "uv run python -m cubesat.transfer_report --report " + ART.as_posix()
    assert len(rep["rows"]) == 2 * 3 * 3  # 2 cases x 3 a_max x 3 T
    assert {len(c["N"]) for c in rep["convergence"]} == {4}
    assert rep["convergence"][0]["N"] == [12, 24, 48, 96]


def test_lp_beats_pd_on_same_transfer():
    r = _row(REF, 0.1, 1.0)  # a_max 0.1 = the demo scenario's value; PD settles there
    assert r["pd_status"] == "settled"
    assert r["lp_total_l2_mps"] < r["pd_dv_l2_mps"] / 5.0


def test_pd_diverges_at_low_a_max_where_lp_still_feasible():
    r = _row(REF, 0.01, 1.0)
    assert r["pd_status"] == "diverged" and r["pd_residual_m"] > 1e4
    assert r["feasible"] and r["lp_total_l2_mps"] < 20.0


def test_measured_values_pinned():
    # measured 2026-10-31 (N=48); regressions in the LP, caps or reference extraction move these
    assert _row(REF, 0.01, 1.0)["lp_total_l1_mps"] == pytest.approx(16.3095, abs=0.01)
    assert _row(F2K, 0.002, 1.0)["lp_total_l1_mps"] == pytest.approx(4.5460, abs=0.01)
    assert _row(REF, 0.002, 1.0)["feasible"] is False  # a_max too small for 8 km in 1 orbit


def test_two_impulse_is_singular_at_the_swept_T():
    # T = k*pi/n: the fixed-time two-impulse solve is singular, LP is not
    assert all(r["two_impulse_same_T_singular"] for r in _rows())
    assert any(r["feasible"] for r in _rows())


def test_converged_in_N():
    for c in json.loads(ART.read_text())["convergence"]:
        assert c["rel_change_on_halving"][-1] < 0.01  # 48 -> 96 changes the total < 1%


def _rep():
    return json.loads(ART.read_text())


def test_every_mixed_metric_column_is_labelled_l1_or_l2():
    r = _rows()[0]
    for key in r:
        if key.endswith("_mps"):
            assert "_l1_" in key or "_l2_" in key, key


def test_reference_rows_show_both_start_states():
    r = _row(REF, 0.01, 1.0)
    assert r["lp_total_l1_mps"] == pytest.approx(16.3095, abs=0.01)  # t = 1208 s (post PD step)
    assert r["lp_alt_start_t_replan_l1_mps"] == pytest.approx(16.3977, abs=0.01)  # t = 1206 s
    assert "lp_alt_start_t_replan_l1_mps" not in _row(F2K, 0.01, 1.0)
    ref = _rep()["reference_case"]
    assert ref["t0"] == 1208.0 and ref["t_replan"] == 1206.0 and ref["dv_already_spent_mps"] > 0


def test_l2_optimum_check_gaps_are_consistent_and_certified():
    chk = _rep()["l2_optimum_check"]
    assert [c["a_max_mps2"] for c in chk] == [0.1, 0.01]
    for c in chk:
        assert c["N"] == 48 and c["T_orbits"] == 1.0
        assert (
            c["slsqp_sphere_l2_mps"] <= c["slsqp_box_l2_mps"] + 1e-6
        )  # box cap lies inside sphere
        assert c["slsqp_box_l2_mps"] <= c["lp_l2_mps"] + 1e-6  # LP plan is box-feasible
        assert c["dual_lower_bound_uncapped_l2_mps"] <= c["slsqp_sphere_l2_mps"] + 1e-6
        assert c["gap_box_pct"] == pytest.approx(
            100 * (c["lp_l2_mps"] / c["slsqp_box_l2_mps"] - 1.0), abs=1e-6
        )
        assert (
            c["slsqp_box_landing_residual_m"] < 1e-3 and c["slsqp_sphere_landing_residual_m"] < 1e-3
        )


def test_cap_shape_comparison_orders_the_feasible_sets():
    cmp = _rep()["cap_shape_comparison"]
    mins = cmp["min_feasible_a_max_mps2"]
    assert mins["sphere_slsqp"] <= min(mins["box"], mins["octahedron"]) * (1 + 1e-6)
    assert mins["box_cap_dt_T_over_N_minus_1"] < mins["box"]  # node-spacing note: about 2 percent
    tot = cmp["totals_at_a_max_0.01"]
    assert tot["box"]["l1_mps"] is not None and tot["octahedron"]["l1_mps"] is not None
    assert tot["sphere_slsqp"]["l2_mps"] <= tot["box"]["l2_mps"] + 1e-6  # nested feasible sets


def test_landing_fuzz_artifact_never_ships_a_bad_landing():
    f = json.loads(Path("data/eval/lp_landing_fuzz.json").read_text())
    assert f["command"].endswith("--landing-fuzz data/eval/lp_landing_fuzz.json")
    assert f["cases"] == f["feasible"] + f["none"] and f["feasible"] > 100
    assert f["worst_rel_residual"] <= 1e-6  # the post-check tolerance


def test_keepout_fuzz_artifact_reports_the_between_grid_residual():
    f = json.loads(Path("data/eval/lp_keepout_fuzz.json").read_text())
    assert f["command"].endswith("--keepout-fuzz data/eval/lp_keepout_fuzz.json")
    assert f["cases"] == 100 and f["planned"] + f["none"] == 100 and f["planned"] > 50
    assert f["free_plan_collides_cases"] >= f["planned"] // 2  # the crossings are real
    # shortfall below d_safe between grid points is bounded by v_rel * 0.5 s
    assert f["worst_shortfall_over_half_vrel"] <= 1.0 + 1e-6
    assert f["worst_verified_grid_shortfall_m"] <= 1e-6


def test_head_on_block_has_all_eight_combos_planned_and_clear():
    f = json.loads(Path("data/eval/lp_keepout_fuzz.json").read_text())["head_on"]
    assert len(f["rows"]) == 8
    best_off = min(r["offset_150m_x"]["l1_mps"] for r in f["rows"])
    for r in f["rows"]:
        h = r["head_on"]
        assert h["planned"] and h["verified_clearance_m"] >= r["d_safe_m"] - 1e-6
        assert h["true_min_distance_m"] >= r["d_safe_m"] - 0.5 * 60.0  # v_rel * 0.5 s
        assert h["l1_mps"] <= 1.02 * best_off


def _strip(o):
    if isinstance(o, dict):
        return {
            k: _strip(v) for k, v in o.items() if "machine_dependent" not in k and k != "command"
        }
    return [_strip(v) for v in o] if isinstance(o, list) else o


@pytest.mark.slow
def test_report_regenerates_identically(tmp_path):
    out = tmp_path / "t.json"
    assert main(["--report", str(out)]) == 0
    assert _strip(json.loads(out.read_text())) == _strip(json.loads(ART.read_text()))


@pytest.mark.slow
def test_fuzz_artifacts_regenerate_identically(tmp_path):
    for flag, name in (
        ("--landing-fuzz", "lp_landing_fuzz"),
        ("--keepout-fuzz", "lp_keepout_fuzz"),
    ):
        out = tmp_path / f"{name}.json"
        assert main([flag, str(out)]) == 0
        new = _strip(json.loads(out.read_text()))
        old = _strip(json.loads(Path(f"data/eval/{name}.json").read_text()))
        assert new == old
