"""cubesat/geo_v2.py: Earth-view helpers (GMST, geodetic, sun, orbit ring, ground track, station).

Every expectation is derived inside the test from an independent source (published constants,
hand-written inverses, the engine's own chief trajectory)."""

import json
import math
from pathlib import Path

import numpy as np
import pytest

from cubesat import geo_v2, ground, truth
from cubesat.scenario import Scenario
from cubesat.sim_v2 import EngineV2

ROOT = Path(__file__).resolve().parents[2]
RE = 6378.137e3


def _scn(**kw) -> Scenario:
    base = json.loads((ROOT / "data" / "scenarios" / "two_failure.json").read_text())
    base.update(engine="v2", sensor={"fov_half_angle_deg": 1.5, "grid_step_km": 5.0,
                                     "grid_extent_km": 5.0})
    base.update(kw)
    return Scenario.model_validate(base)


def _period(s: Scenario) -> float:
    return 2.0 * math.pi * math.sqrt((RE + s.chief.altitude_km * 1e3) ** 3 / truth.MU)


# --- (a) GMST -----------------------------------------------------------------------------------
def test_gmst_j2000_constant():
    assert math.degrees(geo_v2.gmst_rad("2000-01-01T12:00:00Z", 0.0)) == pytest.approx(
        280.46061837, abs=1e-6
    )


def test_gmst_meeus_example_12b():
    # Meeus, Astronomical Algorithms ex. 12.b: 1987-04-10 19:21:00 UT, GMST = 8h34m57.0896s.
    expect = (8 + 34 / 60 + 57.0896 / 3600) * 15.0
    got = math.degrees(geo_v2.gmst_rad("1987-04-10T19:21:00Z", 0.0))
    assert got == pytest.approx(expect, abs=1e-4)


def test_gmst_advances_at_earth_rate_and_wraps_to_2pi():
    e = "2026-03-20T12:00:00Z"
    g0, g1 = geo_v2.gmst_rad(e, 0.0), geo_v2.gmst_rad(e, 100.0)
    assert (g1 - g0) % (2 * math.pi) == pytest.approx(7.2921159e-5 * 100.0, abs=1e-9)
    assert 0.0 <= geo_v2.gmst_rad(e, 12345.0) < 2 * math.pi
    # one sidereal day returns to the same angle
    sid = 2 * math.pi / 7.2921159e-5
    assert geo_v2.gmst_rad(e, sid) == pytest.approx(g0, abs=1e-9)


def test_gmst_epoch_without_zone_is_utc():
    naive, utc = "2026-03-20T12:00:00", "2026-03-20T12:00:00Z"
    assert geo_v2.gmst_rad(naive, 0.0) == geo_v2.gmst_rad(utc, 0.0)


# --- (b) geodetic -------------------------------------------------------------------------------
def test_geodetic_axes():
    assert geo_v2.eci_to_geodetic([RE + 500e3, 0, 0], 0.0) == pytest.approx((0.0, 0.0, 500e3))
    lat, lon, alt = geo_v2.eci_to_geodetic([0, RE + 500e3, 0], 0.0)
    assert (lat, lon, alt) == pytest.approx((0.0, 90.0, 500e3))
    lat, lon, alt = geo_v2.eci_to_geodetic([0, 0, RE + 500e3], 0.0)
    assert (lat, alt) == pytest.approx((90.0, 500e3))


def test_geodetic_gmst_shifts_longitude_and_wraps():
    # at GMST = 90 deg the +x axis sits at longitude -90
    assert geo_v2.eci_to_geodetic([RE, 0, 0], math.pi / 2)[1] == pytest.approx(-90.0)
    # +y axis at GMST = -170 deg is 90 + 170 = 260 -> -100
    assert geo_v2.eci_to_geodetic([0, RE, 0], math.radians(-170))[1] == pytest.approx(-100.0)
    for g in np.linspace(-7, 7, 29):
        assert -180.0 <= geo_v2.eci_to_geodetic([1e7, 2e6, 1e6], float(g))[1] <= 180.0


def test_geodetic_round_trip_with_test_side_inverse():
    rng = np.random.default_rng(3)
    for _ in range(50):
        lat, lon, alt, g = rng.uniform(-89, 89), rng.uniform(-179, 179), rng.uniform(1e5, 1e6), \
            rng.uniform(0, 2 * math.pi)
        la, lo = math.radians(lat), math.radians(lon) + g  # inverse written here
        r = (RE + alt) * np.array([math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo),
                                   math.sin(la)])
        assert geo_v2.eci_to_geodetic(r, g) == pytest.approx((lat, lon, alt), abs=1e-6)


# --- (c) sun ------------------------------------------------------------------------------------
def _ra_dec(v):
    return math.degrees(math.atan2(v[1], v[0])), math.degrees(math.asin(v[2]))


def test_sun_unit_length():
    v = geo_v2.sun_direction_eci("2026-10-31T00:00:00Z", 12345.0)
    assert math.sqrt(sum(c * c for c in v)) == pytest.approx(1.0, abs=1e-12)


def test_sun_at_march_equinox_points_to_plus_x():
    v = geo_v2.sun_direction_eci("2000-03-20T07:35:00Z")
    ang = math.degrees(math.acos(max(-1.0, min(1.0, v[0]))))
    assert ang < 0.5


def test_sun_declination_at_june_solstice():
    ra, dec = _ra_dec(geo_v2.sun_direction_eci("2000-06-21T01:48:00Z"))
    assert dec == pytest.approx(23.44, abs=0.1)
    assert ra == pytest.approx(90.0, abs=1.0)


def test_sun_t_offset_equals_later_epoch():
    a = geo_v2.sun_direction_eci("2026-03-20T12:00:00Z", 86400.0 * 30)
    b = geo_v2.sun_direction_eci("2026-04-19T12:00:00Z", 0.0)
    assert a == pytest.approx(b, abs=1e-12)


# --- (d) orbit ring -----------------------------------------------------------------------------
def test_ring_first_point_radius_and_closure():
    s = _scn()
    ring = np.array(geo_v2.orbit_ring(s))
    assert ring.shape == (256, 3)
    c0 = truth.chief_initial(s.chief.altitude_km * 1e3, s.chief.inclination_deg, s.chief.raan_deg)
    assert ring[0] == pytest.approx(c0[:3], abs=1e-9)
    radii = np.linalg.norm(ring, axis=1)
    assert np.all(abs(radii / (RE + 500e3) - 1) < 0.002)
    end = geo_v2.chief_states(s, [_period(s)])[0, :3]
    assert np.linalg.norm(ring[0] - end) < 40e3  # J2 nodal-period phase drift, measured 32.5 km


def test_ring_equals_engine_chief_at_matching_ticks():
    s = _scn()
    n = 40
    ring = geo_v2.orbit_ring(s, n=n, span_s=n * s.dt_s)  # samples land on engine ticks k*dt
    eng = EngineV2(s)
    for k in range(n):
        assert np.max(np.abs(eng.X[0, :3] - ring[k])) < 1e-6
        eng.step()


def test_chief_states_backwards_steps_back_along_the_orbit():
    s = _scn()
    c0 = truth.chief_initial(s.chief.altitude_km * 1e3, s.chief.inclination_deg, s.chief.raan_deg)
    back, fwd = geo_v2.chief_states(s, [-60.0])[0], geo_v2.chief_states(s, [60.0])[0]
    # mirror about the node: opposite z, same radius; before the node the sat is south of it
    assert back[2] < 0.0 < fwd[2]
    assert back[2] == pytest.approx(-fwd[2], rel=1e-3)
    assert np.linalg.norm(back[:3]) == pytest.approx(np.linalg.norm(fwd[:3]), rel=1e-6)
    # position moved against the velocity direction
    assert np.dot(back[:3] - c0[:3], c0[3:]) < 0.0


# --- (e) ground track ---------------------------------------------------------------------------
def test_ground_track_shape_continuity_and_max_latitude():
    s = _scn()
    gt = np.array(geo_v2.ground_track(s))
    assert gt.shape == (257, 2)
    lon = np.unwrap(np.radians(gt[:, 1]))
    lat = np.radians(gt[:, 0])
    step = 2 * math.pi / 128 * 1.2 + 7.2921159e-5 * _period(s) / 128 + 1e-3  # orbit + earth rot
    d = np.hypot(np.diff(lat), np.diff(lon) * np.cos(lat[:-1]) + 0 * lat[:-1])
    assert np.max(d) < step * 1.5  # no jumps (high-lat longitude steps are compressed by cos)
    assert np.max(np.abs(np.diff(lat))) < 2 * math.pi / 128 * 1.1
    assert np.max(np.abs(gt[:, 0])) == pytest.approx(180.0 - s.chief.inclination_deg, abs=0.5)
    # t = 0 sample is the chief's start (ascending node: latitude 0)
    assert gt[128, 0] == pytest.approx(0.0, abs=1e-9)


def test_ground_track_negative_half_precedes_the_start():
    s = _scn()
    gt = np.array(geo_v2.ground_track(s))
    # one sample before the node the satellite is south of the equator (northbound ascending)
    assert gt[127, 0] < 0.0 < gt[129, 0]


# --- (f) station pass ---------------------------------------------------------------------------
def _station_eci(gmst):
    la, lo = math.radians(ground.STATION_LAT_DEG), math.radians(ground.STATION_LON_DEG) + gmst
    return RE * np.array([math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)])


def test_station_overhead_is_90_and_visible():
    g = 0.7
    out = geo_v2.station_pass(_station_eci(g) * (1 + 500e3 / RE), g)
    assert out["elevation_deg"] == pytest.approx(90.0, abs=1e-5)  # asin near 1
    assert out["visible"] is True


def test_station_below_horizon_negative_not_visible():
    g = 0.7
    out = geo_v2.station_pass(-_station_eci(g) * 1.08, g)
    assert out["elevation_deg"] < 0.0
    assert out["visible"] is False


def test_station_threshold_matches_ground_module():
    g = 0.0
    r_gs = ground.station_eci(0.0)  # GMST = 0 at t = 0 in ground.py
    east = np.cross([0, 0, 1.0], r_gs)
    east /= np.linalg.norm(east)
    up = r_gs / np.linalg.norm(r_gs)
    for ang in (0.0, 5.0, 12.0, 20.0):
        a = math.radians(ang)
        r = r_gs + 2e6 * (math.cos(a) * east + math.sin(a) * up)
        out = geo_v2.station_pass(r, g)
        assert out["elevation_deg"] == pytest.approx(float(ground.elevation_deg(r, r_gs)))
        assert out["visible"] == (out["elevation_deg"] >= ground.MIN_ELEVATION_DEG)

