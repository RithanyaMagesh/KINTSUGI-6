"""Task 1.5: CW-vs-truth report module (cubesat/cw_truth.py, own main(), not benchmark.py)."""

import json
import math

from cubesat import cw_truth


def test_report_has_every_case_and_finite_numbers():
    rep = cw_truth.build_report(orbits=0.1, command="test")
    assert rep["command"] == "test"
    keys = {(c["radial_amp_km"], c["j2"], c["drag"]) for c in rep["cases"]}
    assert keys == {(a, j, d) for a in (1.0, 8.0) for j in (False, True) for d in (False, True)}
    assert all(math.isfinite(c["max_pos_diff_m"]) for c in rep["cases"])
    assert rep["g1_state"]["orbits"] == 0.1


def test_main_writes_report_with_command_field(tmp_path):
    out = tmp_path / "r.json"
    assert cw_truth.main(["--report", str(out), "--orbits", "0.05"]) == 0
    rep = json.loads(out.read_text())
    assert rep["command"] == f"uv run python -m cubesat.cw_truth --report {out} --orbits 0.05"
