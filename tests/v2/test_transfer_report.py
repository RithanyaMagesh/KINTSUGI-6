"""Phase 5c.3: the committed LP-vs-PD table (data/eval/lp_vs_pd_dv_table.json)."""

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
    return next(r for r in _rows() if r["case"] == case and r["a_max_mps2"] == a
                and r["T_orbits"] == orbits)


def test_artifact_has_command_and_every_cell():
    rep = json.loads(ART.read_text())
    assert rep["command"] == "uv run python -m cubesat.transfer_report --report " + ART.as_posix()
    assert len(rep["rows"]) == 2 * 3 * 3  # 2 cases x 3 a_max x 3 T
    assert {len(c["N"]) for c in rep["convergence"]} == {4}
    assert rep["convergence"][0]["N"] == [12, 24, 48, 96]


def test_lp_beats_pd_on_same_transfer():
    r = _row(REF, 0.1, 1.0)  # a_max 0.1 = the demo scenario's value; PD settles there
    assert r["pd_status"] == "settled"
    assert r["lp_total_l2_mps"] < r["pd_dv_mps"] / 5.0


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


@pytest.mark.slow
def test_report_regenerates_identically(tmp_path):
    out = tmp_path / "t.json"
    assert main(["--report", str(out)]) == 0

    def strip(o):
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if "machine_dependent" not in k
                    and k != "command"}
        return [strip(v) for v in o] if isinstance(o, list) else o

    assert strip(json.loads(out.read_text())) == strip(json.loads(ART.read_text()))
