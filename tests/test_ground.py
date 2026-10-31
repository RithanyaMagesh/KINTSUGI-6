"""Ground-pass model tests (cubesat/ground.py; replan-and-judge kit section 6).

Geometry is checked on constructed vectors; statistics only against a coarse
sanity range -- the model's numbers are measured, never tuned to a target.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from cubesat import ground
from cubesat.benchmark import main

ROOT = Path(__file__).resolve().parents[1]
TWO_FAILURE = ROOT / "data" / "scenarios" / "two_failure.json"


def test_elevation_is_90_deg_for_satellite_directly_overhead():
    r_gs = ground.station_eci(0.0)
    r_sat = r_gs * (1.0 + 500.0 / 6378.137)  # same direction, 500 km higher
    assert ground.elevation_deg(r_sat, r_gs) == pytest.approx(90.0, abs=1e-9)


def test_elevation_below_horizon_is_under_min_elevation():
    r_gs = ground.station_eci(0.0)
    r_sat = -r_gs * 1.08  # antipodal side of the Earth
    assert ground.elevation_deg(r_sat, r_gs) < 0.0
    # Same altitude, 90 deg of arc away along the equator-ward direction: below 10 deg.
    east = np.cross([0.0, 0.0, 1.0], r_gs)
    east /= np.linalg.norm(east)
    r_far = np.linalg.norm(r_gs) * 1.08 * east
    assert ground.elevation_deg(r_far, r_gs) < ground.MIN_ELEVATION_DEG


def test_pass_windows_sorted_and_non_overlapping():
    windows = ground.pass_windows(0.0, 0.0)
    assert windows
    for start, end in windows:
        assert end >= start
    for (_, prev_end), (next_start, _) in zip(windows, windows[1:], strict=False):
        assert next_start > prev_end
    assert windows == sorted(windows)


def test_wait_zero_inside_pass_and_countdown_before_it():
    windows = ground.pass_windows(0.0, 0.0)
    start, end = windows[2]
    assert ground.wait_to_next_pass((start + end) / 2.0) == 0.0
    assert ground.wait_to_next_pass(start - 100.0) == pytest.approx(100.0)
    # just after the pass ends the wait is to the NEXT pass start
    nxt = windows[3][0]
    assert ground.wait_to_next_pass(end + 10.0) == pytest.approx(nxt - end - 10.0)


def test_deterministic_two_calls_equal():
    assert ground.pass_statistics() == ground.pass_statistics()
    assert ground.pass_windows(0.0, 0.0) == ground.pass_windows(0.0, 0.0)


def test_statistics_coarse_sanity_range():
    s = ground.pass_statistics()
    assert 1.0 < s["passes_per_day"] < 6.0
    assert s["n_starts"] == 48
    assert s["n_waits"] > 1000
    assert 0.0 < s["wait_median_s"] < s["max_gap_s"]
    assert s["wait_mean_s"] <= s["wait_p90_s"] <= s["max_gap_s"]
    for key in ("altitude_km", "inclination_deg", "station_lat_deg", "station_lon_deg",
                "min_elevation_deg", "horizon_s", "dt_s", "raan_rate_deg_per_day"):
        assert key in s
    # sun-synchronous design: J2 drift is about +0.9856 deg/day
    assert s["raan_rate_deg_per_day"] == pytest.approx(0.9856, abs=0.05)


def test_ground_passes_mode_writes_artifact(tmp_path):
    out = ROOT / "data" / "eval" / "_tmp_ground_pass_stats_test.json"
    try:
        rc = main(["--mode", "ground-passes", "--base", str(TWO_FAILURE), "--report", str(out)])
        assert rc == 0
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["command"].startswith("uv run python -m cubesat.benchmark")
        assert report["passes_per_day"] == ground.pass_statistics()["passes_per_day"]
        assert report["min_elevation_deg"] == 10.0
    finally:
        out.unlink(missing_ok=True)
