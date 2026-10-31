"""E1 item 2: EngineV2 tick lines carry `chief` (ECI + geodetic) and `station` (Bengaluru pass)."""

import json
import math
from pathlib import Path

import numpy as np
import pytest

from cubesat import geo_v2, truth
from cubesat.scenario import Scenario
from cubesat.sim import run_scenario
from cubesat.sim_v2 import EngineV2, run_scenario_v2

ROOT = Path(__file__).resolve().parents[2]


def _scn(**kw) -> Scenario:
    base = json.loads((ROOT / "data" / "scenarios" / "two_failure.json").read_text())
    base.update(engine="v2", duration_s=120.0,
                sensor={"fov_half_angle_deg": 1.5, "grid_step_km": 5.0, "grid_extent_km": 5.0})
    base.update(kw)
    return Scenario.model_validate(base)


def _ticks(lines):
    return [x for x in lines if x["state"] not in ("INIT", "SUMMARY")]


def test_v2_ticks_carry_chief_and_station_keys():
    for line in _ticks(run_scenario_v2(_scn())):
        assert set(line["chief"]) == {"r_eci", "lat_deg", "lon_deg", "alt_m"}
        assert len(line["chief"]["r_eci"]) == 3
        assert set(line["station"]) == {"elevation_deg", "visible"}


def test_v1_ticks_do_not_gain_the_keys():
    lines = run_scenario(_scn().model_copy(update={"engine": "v1"}))
    assert all("chief" not in x and "station" not in x for x in lines)


def test_chief_radius_is_re_plus_alt_for_a_circular_start():
    s = _scn()
    line = _ticks(run_scenario_v2(s))[0]
    r = np.linalg.norm(line["chief"]["r_eci"])
    assert r == pytest.approx(truth.RE + s.chief.altitude_km * 1e3, abs=1e-6)
    assert line["chief"]["alt_m"] == pytest.approx(s.chief.altitude_km * 1e3, abs=1e-6)


def test_chief_geodetic_matches_eci_to_geodetic_at_every_tick():
    s = _scn()
    for line in _ticks(run_scenario_v2(s)):
        g = geo_v2.gmst_rad(s.chief.epoch_utc, line["t"])
        c = line["chief"]
        assert (c["lat_deg"], c["lon_deg"], c["alt_m"]) == pytest.approx(
            geo_v2.eci_to_geodetic(c["r_eci"], g), abs=1e-9
        )
        assert line["station"] == geo_v2.station_pass(c["r_eci"], g)


def test_chief_position_is_the_engines_own_trajectory():
    s = _scn(duration_s=60.0)
    ring = geo_v2.chief_states(s, [k * s.dt_s for k in range(5)])
    lines = _ticks(run_scenario_v2(s))
    for k in range(5):
        assert np.max(np.abs(np.array(lines[k]["chief"]["r_eci"]) - ring[k, :3])) < 1e-6


def test_v2_ticks_are_deterministic_bytes():
    a = json.dumps(run_scenario_v2(_scn()), sort_keys=True)
    b = json.dumps(run_scenario_v2(_scn()), sort_keys=True)
    assert a == b


def test_snapshot_restore_continues_identically_including_earth_keys():
    s = _scn()
    a = EngineV2(s)
    for _ in range(20):
        a.step()
    blob = a.snapshot()
    tail_a = list(a.run())
    b = EngineV2(s)
    b.restore(blob)
    tail_b = list(b.run())
    assert json.dumps(tail_a, sort_keys=True) == json.dumps(tail_b, sort_keys=True)
    assert "chief" in tail_b[0] and math.isfinite(tail_b[0]["chief"]["lat_deg"])
