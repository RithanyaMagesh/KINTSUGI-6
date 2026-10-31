"""Earth-view geometry for engine v2: GMST, geodetic, sun, orbit ring, ground track, station pass.

Pure functions, no wall clock, no RNG (AGENTS.md invariant 2). SI internally (m, s, rad); degrees
only where named `_deg`. Frames: ECI with +z = rotation axis, +x = vernal equinox direction at
J2000-like epoch (mean equator and equinox of date is NOT distinguished: precession/nutation are
ignored, < 0.4 deg over the 2026 epoch, invisible at globe scale).

Simplifications (each a deliberate corner, documented in docs/PHYSICS_V2.md):
  * spherical Earth of radius 6378.137 km: no flattening, so geodetic latitude is geocentric
    latitude (max 0.19 deg difference at mid-latitudes, same model as cubesat/ground.py);
  * UT1 = UTC (|UT1 - UTC| < 0.9 s, 0.004 deg of Earth rotation); polar motion ignored;
  * the Earth rotates at the constant 7.2921159e-5 rad/s from the epoch on (cubesat/truth.py);
  * sun direction is the low-precision Astronomical Almanac formula (~0.01 deg), geometric,
    no aberration/refraction.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from functools import lru_cache

import numpy as np

from cubesat import ground, truth
from cubesat.hcw import mean_motion
from cubesat.scenario import Scenario

TWO_PI = 2.0 * math.pi
_J2000 = datetime(2000, 1, 1, 12, tzinfo=UTC)
STATION_NAME = "Bengaluru"


@lru_cache(maxsize=64)
def _days_since_j2000(epoch_utc: str) -> float:
    dt = datetime.fromisoformat(epoch_utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return (dt - _J2000).total_seconds() / 86400.0


def gmst_rad(epoch_utc: str, t_s: float) -> float:
    """Greenwich mean sidereal angle at epoch + t_s, in [0, 2 pi).

    IAU-1982 polynomial (Meeus 12.4) at the epoch with UT1 = UTC (error < 0.9 s of rotation),
    then the constant rate OMEGA_E = 7.2921159e-5 rad/s for t_s."""
    d = _days_since_j2000(epoch_utc)
    tc = d / 36525.0
    deg = 280.46061837 + 360.98564736629 * d + 0.000387933 * tc**2 - tc**3 / 38710000.0
    return (math.radians(deg) + truth.OMEGA_E * t_s) % TWO_PI


def eci_to_geodetic(r_eci, gmst: float) -> tuple[float, float, float]:
    """(lat_deg, lon_deg in [-180, 180], alt_m) on a spherical Earth of radius truth.RE."""
    x, y, z = (float(c) for c in r_eci)
    r = math.sqrt(x * x + y * y + z * z)
    lat = math.degrees(math.asin(max(-1.0, min(1.0, z / r))))
    lon = (math.degrees(math.atan2(y, x) - gmst) + 180.0) % 360.0 - 180.0
    return lat, lon, r - truth.RE


def sun_direction_eci(epoch_utc: str, t_s: float = 0.0) -> list[float]:
    """Unit vector to the Sun in ECI (Astronomical Almanac low-precision formula, ~0.01 deg)."""
    n = _days_since_j2000(epoch_utc) + t_s / 86400.0
    mean_lon = 280.460 + 0.9856474 * n
    g = math.radians(357.528 + 0.9856003 * n)
    lam = math.radians(mean_lon + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g))
    eps = math.radians(23.439 - 0.0000004 * n)
    return [math.cos(lam), math.cos(eps) * math.sin(lam), math.sin(eps) * math.sin(lam)]


def chief_period_s(scenario: Scenario) -> float:
    return TWO_PI / mean_motion(scenario.chief.altitude_km * 1000.0)


def chief_states(scenario: Scenario, times) -> np.ndarray:
    """Chief ECI [r, v] (len(times), 6) at `times` (s from t=0), integrated with the engine's own
    chief dynamics (gravity + J2 if truth.j2_enabled, no drag, RK4 at scenario.dt_s).

    `times` must be sorted away from 0 (increasing for t >= 0, decreasing for t <= 0). A gap is
    covered by whole steps of +-dt_s and one fractional remainder step, so times that are
    multiples of dt_s reproduce the engine's chief bit for bit; negative times integrate
    backwards with a negative step."""
    cfg, dt = scenario.chief, scenario.dt_s
    j2 = scenario.truth.j2_enabled

    def accel(r, v):
        a = truth.accel_gravity(r)
        return a + truth.accel_j2(r) if j2 else a

    s = truth.chief_initial(cfg.altitude_km * 1000.0, cfg.inclination_deg, cfg.raan_deg)
    t, out = 0.0, []
    for target in times:
        gap = target - t
        step = math.copysign(dt, gap) if gap else dt
        for _ in range(int(abs(gap) / dt + 1e-9)):
            s = truth.rk4_step(s, step, accel)
        rest = gap - step * int(abs(gap) / dt + 1e-9)
        if abs(rest) > 1e-9:
            s = truth.rk4_step(s, rest, accel)
        t = target
        out.append(s)
    return np.array(out)


def orbit_ring(scenario: Scenario, n: int = 256, span_s: float | None = None) -> list[list[float]]:
    """n ECI points (m) at t = k * span / n, k = 0..n-1, span = one chief period by default
    (span_s exists so a test can align the samples with engine ticks)."""
    span = chief_period_s(scenario) if span_s is None else span_s
    return chief_states(scenario, [k * span / n for k in range(n)])[:, :3].tolist()


def ground_track(scenario: Scenario, n_per_side: int = 128) -> list[list[float]]:
    """[lat_deg, lon_deg] at t = k * T / n_per_side, k = -n..n (2n + 1 samples, +-1 period).
    Longitude uses GMST(epoch, t), so the track is the true Earth-fixed path."""
    n, period = n_per_side, chief_period_s(scenario)
    fwd = chief_states(scenario, [k * period / n for k in range(1, n + 1)])
    back = chief_states(scenario, [-k * period / n for k in range(1, n + 1)])
    first = chief_states(scenario, [0.0])
    ks = list(range(-n, n + 1))
    states = np.vstack([back[::-1], first, fwd])
    epoch = scenario.chief.epoch_utc
    return [
        list(eci_to_geodetic(states[i, :3], gmst_rad(epoch, k * period / n))[:2])
        for i, k in enumerate(ks)
    ]


def station_pass(
    chief_eci,
    gmst: float,
    lat_deg: float = ground.STATION_LAT_DEG,
    lon_deg: float = ground.STATION_LON_DEG,
    min_el_deg: float = ground.MIN_ELEVATION_DEG,
) -> dict:
    """Elevation of the chief above the station's horizon and the pass flag (elevation >= min).
    Same elevation formula and constants as cubesat/ground.py; the station sits at longitude
    lon_deg + GMST in ECI (spherical Earth)."""
    la, lo = math.radians(lat_deg), math.radians(lon_deg) + gmst
    r_gs = truth.RE * np.array([math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo),
                                math.sin(la)])
    el = float(ground.elevation_deg(np.asarray(chief_eci, dtype=float), r_gs))
    return {"elevation_deg": el, "visible": bool(el >= min_el_deg)}


def tick_fields(r_eci, epoch_utc: str, t_s: float) -> dict:
    """The v2 tick-line keys `chief` and `station` for the chief at ECI position r_eci, time t_s."""
    g = gmst_rad(epoch_utc, t_s)
    lat, lon, alt = eci_to_geodetic(r_eci, g)
    return {
        "chief": {"r_eci": [float(c) for c in r_eci], "lat_deg": lat, "lon_deg": lon, "alt_m": alt},
        "station": station_pass(r_eci, g),
    }

