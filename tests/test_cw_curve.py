"""P3 test (docs/ENDGAME_PLAN.md section 6, written before cubesat/cw_curve.py).

The factored CW-vs-Kepler cross-check must reproduce the recorded G1 evidence
at the 1 km passive ellipse (the initial state of
tests/test_hcw.py::test_cw_vs_kepler_error_report, GATES.md G1 row: 3.101 m).
The G3-era 11/22 km slot max is pinned to the recorded GATES.md:26 constant
(2984.5 m, README command of record); the current 8 km radial / 16 km
along-track max is pinned to the value measured fresh at P3 execution. The two
large-scale maxes are recorded constants, NOT auto-checked against test_hcw
(the existing slow test is left untouched -- it is G1 evidence).

Marked slow: it runs the same rtol=1e-12 two-body cross-check family as
test_cw_vs_kepler_error_report ("Kepler cross-check" in the slow marker).
"""

import csv
from pathlib import Path

import numpy as np
import pytest

from cubesat.cw_curve import (
    CURRENT_8KM_RECORDED_MAX_M,
    G3ERA_RECORDED_MAX_M,
    ONEKM_RECORDED_MAX_M,
    T_GRID,
    N,
    cw_curve_report,
    state_1km_passive_ellipse,
    write_csv,
)

# The exact initial state of tests/test_hcw.py:112-113 (1 km radial, 500 m
# cross-track, drift-free vy0) -- the auto-pinned state, asserted literally.
ONEKM_STATE = np.array([1000.0, 0.0, 500.0, 0.0, -2.0 * N * 1000.0, 0.0])


@pytest.mark.slow
def test_cw_vs_kepler_error_curve_matches_report_max(tmp_path):
    """The (t, error) curves' maxima match the recorded constants (1 km /
    G3-era / current 8 km), and the written CSV's per-column maxima match the
    report (the curve IS the evidence, ENDGAME_PLAN 6)."""
    assert np.array_equal(state_1km_passive_ellipse(), ONEKM_STATE)
    report = cw_curve_report(command="tests/test_cw_curve.py (in-process)")
    maxes = report["max_err_m"]
    # Recorded G1 constant (GATES.md G1 row: 3.101 m over 3 orbits).
    assert abs(maxes["err_1km"] - ONEKM_RECORDED_MAX_M) <= 0.01
    # Recorded G3-era constant (GATES.md:26 / README command of record).
    assert abs(maxes["err_g3era_11km"] - G3ERA_RECORDED_MAX_M) <= 0.5
    # Current two_failure scale: pinned to the fresh P3 measurement constant.
    assert abs(maxes["err_current_8km"] - CURRENT_8KM_RECORDED_MAX_M) <= 0.01
    # CSV round-trip: the emitted curve's column maxima equal the report maxes.
    out = write_csv(report, Path(tmp_path) / "cw_error_curve.csv")
    with out.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0].keys()) == ["t", "err_1km", "err_g3era_11km", "err_current_8km"]
    assert len(rows) == len(T_GRID)
    for col in ("err_1km", "err_g3era_11km", "err_current_8km"):
        col_max = max(float(r[col]) for r in rows)
        assert abs(col_max - maxes[col]) <= 5e-6
