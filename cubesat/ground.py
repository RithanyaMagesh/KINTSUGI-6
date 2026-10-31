"""Ground-pass model: how long until a single ground station can see the swarm.

Feeds the `wait_for_ground` baseline (cubesat/benchmark.py) and the
ground-pass statistics artifact. Pure numpy, deterministic: no wall clock, no
RNG (AGENTS.md invariant 2). SI internally (m, s, rad); degrees only at the
API edge where named `_deg`.

Model (replan-and-judge kit section 6, implemented as specified):
  * circular orbit, altitude 500 km (a = 6378.137 km + 500 km), inclination 97.4 deg;
  * RAAN drifts at the J2 secular rate dOmega/dt = -1.5 n J2 (Re/a)^2 cos i,
    with n = sqrt(mu/a^3), J2 = 1.08262668e-3, mu = 3.986004418e14 m^3/s^2;
  * the argument of latitude advances at n; Earth rotates at 7.2921159e-5 rad/s,
    GMST = 0 at t = 0;
  * ground station Bengaluru 13.03 N, 77.51 E; a pass is elevation >= 10 deg;
    elevation = asin(((r_sat - r_gs) . u_gs) / |r_sat - r_gs|), u_gs the
    station's local vertical;
  * horizon 7 days, sample step 10 s; 12 RAAN starts (k * 30 deg) x 4
    argument-of-latitude starts (k * 90 deg) = 48 starts; waits are measured
    from failure instants every 600 s: 0 if a pass is in progress at the
    instant, else the time to the next pass start.

Simplifications (each is a deliberate corner, not a claim of realism):
  * spherical Earth (station radius = equatorial radius, local vertical =
    radial direction, no geodetic flattening);
  * the satellite's mean motion ignores the J2 correction to n and the
    apsidal/nodal-period difference; only the RAAN drift is J2-corrected;
  * no drag, no third-body, no atmosphere (elevation threshold is purely
    geometric, no refraction, no terrain mask);
  * pass edges are resolved to the 10 s sample grid (up to 10 s optimistic or
    pessimistic per edge): a window is [first sample >= 10 deg, last sample >= 10 deg];
  * failure instants are drawn only from the first (horizon - 1 day) so every
    wait resolves inside the horizon (the longest gap is far below one day;
    this is asserted, not assumed);
  * a pass in progress at t = 0 counts as a window starting at 0 (edge effect
    on the per-start pass count, at most one pass in seven days);
  * the 48 starts are a deterministic grid, not a random sample, and the
    statistic is a mean over starts of per-start quantities pooled over
    instants (waits pooled across all starts);
  * percentiles use numpy's default linear interpolation;
  * ONE station, so the numbers describe a single Indian ground station and
    nothing else (illustrative, depends on the station network).
"""

from __future__ import annotations

import math
from functools import cache

import numpy as np

# --- model parameters (named constants; the artifact echoes them) -----------
EARTH_RADIUS_M = 6_378_137.0
MU_M3_S2 = 3.986004418e14
J2 = 1.08262668e-3
EARTH_ROT_RAD_S = 7.2921159e-5
ALTITUDE_M = 500_000.0
INCLINATION_DEG = 97.4
STATION_LAT_DEG = 13.03  # Bengaluru
STATION_LON_DEG = 77.51
MIN_ELEVATION_DEG = 10.0
HORIZON_S = 7 * 86400.0
DT_S = 10.0
FAILURE_STEP_S = 600.0
N_RAAN_STARTS = 12  # k * 30 deg
N_PHASE_STARTS = 4  # k * 90 deg

_A = EARTH_RADIUS_M + ALTITUDE_M
_N = math.sqrt(MU_M3_S2 / _A**3)
_COS_I = math.cos(math.radians(INCLINATION_DEG))
_SIN_I = math.sin(math.radians(INCLINATION_DEG))
RAAN_RATE_RAD_S = -1.5 * _N * J2 * (EARTH_RADIUS_M / _A) ** 2 * _COS_I


def station_eci(t) -> np.ndarray:
    """Station ECI position(s), m; t scalar -> shape (3,), array -> shape (len, 3).
    Spherical Earth, GMST = 0 at t = 0."""
    t = np.asarray(t, dtype=float)
    lat = math.radians(STATION_LAT_DEG)
    lon = math.radians(STATION_LON_DEG) + EARTH_ROT_RAD_S * t
    up = np.full_like(lon, math.sin(lat))
    return EARTH_RADIUS_M * np.stack(
        [math.cos(lat) * np.cos(lon), math.cos(lat) * np.sin(lon), up], axis=-1
    )


def satellite_eci(t, raan0: float, phase0: float) -> np.ndarray:
    """Satellite ECI position(s), m, for a circular orbit with J2 RAAN drift.
    raan0/phase0 in radians (RAAN and argument of latitude at t = 0)."""
    t = np.asarray(t, dtype=float)
    raan = raan0 + RAAN_RATE_RAD_S * t
    u = phase0 + _N * t
    cu, su, cr, sr = np.cos(u), np.sin(u), np.cos(raan), np.sin(raan)
    return _A * np.stack(
        [cr * cu - sr * _COS_I * su, sr * cu + cr * _COS_I * su, _SIN_I * su], axis=-1
    )


def elevation_deg(r_sat, r_gs) -> np.ndarray:
    """Elevation (deg) of r_sat above the local horizon at r_gs (both ECI, m,
    last axis 3): asin(((r_sat - r_gs) . u_gs) / |r_sat - r_gs|), u_gs = r_gs/|r_gs|."""
    r_sat = np.asarray(r_sat, dtype=float)
    r_gs = np.asarray(r_gs, dtype=float)
    up = r_gs / np.linalg.norm(r_gs, axis=-1, keepdims=True)
    rel = r_sat - r_gs
    sin_el = np.sum(rel * up, axis=-1) / np.linalg.norm(rel, axis=-1)
    return np.degrees(np.arcsin(np.clip(sin_el, -1.0, 1.0)))


@cache
def _windows(raan0: float, phase0: float, horizon_s: float, dt: float) -> tuple:
    t = np.arange(0.0, horizon_s + 0.5 * dt, dt)
    visible = elevation_deg(satellite_eci(t, raan0, phase0), station_eci(t)) >= MIN_ELEVATION_DEG
    edges = np.diff(np.concatenate(([0], visible.astype(np.int8), [0])))
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1) - 1  # last visible sample of each run
    return tuple((float(t[s]), float(t[e])) for s, e in zip(starts, ends, strict=True))


def pass_windows(
    raan0: float, phase0: float, horizon_s: float = HORIZON_S, dt: float = DT_S
) -> list[tuple[float, float]]:
    """(start_s, end_s) of every pass above MIN_ELEVATION_DEG, sorted, over the horizon."""
    return list(_windows(float(raan0), float(phase0), float(horizon_s), float(dt)))


def _waits(windows, t_fail: np.ndarray) -> np.ndarray:
    starts = np.array([w[0] for w in windows])
    ends = np.array([w[1] for w in windows])
    idx = np.searchsorted(starts, t_fail, side="right")  # first window starting after t
    nxt = np.where(idx < len(starts), starts[np.minimum(idx, len(starts) - 1)], np.nan)
    in_pass = (idx > 0) & (t_fail <= ends[np.maximum(idx - 1, 0)])
    return np.where(in_pass, 0.0, nxt - t_fail)


def wait_to_next_pass(t_fail_s: float, raan0: float = 0.0, phase0: float = 0.0) -> float:
    """Seconds from a failure at t_fail_s to the next pass start (0 if a pass is
    in progress). Default start: RAAN 0, argument of latitude 0. Raises if no pass
    starts inside the 7-day horizon after t_fail_s."""
    wait = float(_waits(_windows(float(raan0), float(phase0), HORIZON_S, DT_S),
                        np.array([float(t_fail_s)]))[0])
    if math.isnan(wait):
        raise ValueError(f"no pass after t={t_fail_s} s inside the {HORIZON_S} s horizon")
    return wait


def pass_statistics() -> dict:
    """Pass statistics over the 48-start grid (see module docstring) plus the
    model parameters. Pooled waits over all starts; max_gap_s = longest
    end-of-pass -> start-of-next-pass interval over every start."""
    t_fail = np.arange(0.0, HORIZON_S - 86400.0 + 0.5 * FAILURE_STEP_S, FAILURE_STEP_S)
    waits, per_day, max_gap = [], [], 0.0
    for k_raan in range(N_RAAN_STARTS):
        for k_phase in range(N_PHASE_STARTS):
            w = _windows(math.radians(30.0 * k_raan), math.radians(90.0 * k_phase), HORIZON_S, DT_S)
            per_day.append(len(w) / (HORIZON_S / 86400.0))
            max_gap = max([max_gap] + [b[0] - a[1] for a, b in zip(w, w[1:], strict=False)])
            waits.append(_waits(w, t_fail))
    waits = np.concatenate(waits)
    assert not np.isnan(waits).any() and max_gap < 86400.0  # every wait resolved in-horizon
    return {
        "passes_per_day": float(np.mean(per_day)),
        "wait_mean_s": float(np.mean(waits)),
        "wait_median_s": float(np.median(waits)),
        "wait_p90_s": float(np.percentile(waits, 90)),
        "max_gap_s": float(max_gap),
        "n_starts": N_RAAN_STARTS * N_PHASE_STARTS,
        "n_waits": int(waits.size),
        "altitude_km": ALTITUDE_M / 1000.0,
        "inclination_deg": INCLINATION_DEG,
        "raan_rate_deg_per_day": math.degrees(RAAN_RATE_RAD_S) * 86400.0,
        "station": "Bengaluru",
        "station_lat_deg": STATION_LAT_DEG,
        "station_lon_deg": STATION_LON_DEG,
        "min_elevation_deg": MIN_ELEVATION_DEG,
        "horizon_s": HORIZON_S,
        "dt_s": DT_S,
        "failure_step_s": FAILURE_STEP_S,
        "failure_instants_per_start": int(t_fail.size),
        "raan_starts_deg": [30.0 * k for k in range(N_RAAN_STARTS)],
        "phase_starts_deg": [90.0 * k for k in range(N_PHASE_STARTS)],
        "j2": J2,
        "mu_m3_s2": MU_M3_S2,
        "earth_rot_rad_s": EARTH_ROT_RAD_S,
        "earth_radius_m": EARTH_RADIUS_M,
    }
