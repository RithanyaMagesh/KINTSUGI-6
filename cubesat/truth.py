"""Truth dynamics for engine v2: ECI two-body + J2 + drag, RK4, LVLH transforms.

Formulas: docs/superpowers/specs/2026-10-31-physics-v2-brief.md section 4 Phase 1 (listed with
sources and validation commands in docs/PHYSICS_V2.md). SI units; ECI/LVLH frames as in
AGENTS.md (LVLH x radial, y along-track, z cross-track). Every acceleration accepts a single
vector (3,) or a batch (N, 3) so the engine can propagate all sats in one call.
"""

from __future__ import annotations

import numpy as np

MU = 3.986004418e14  # m^3/s^2
J2 = 1.08262668e-3
RE = 6378.137e3  # m
OMEGA_E = 7.2921159e-5  # rad/s, Earth rotation about +z

# Vallado, Fundamentals of Astrodynamics and Applications, Table 8-4 exponential atmosphere:
# (h0 km, rho0 kg/m^3, scale height H km); rho = rho0 exp(-(h - h0)/H) on the row with the
# largest h0 <= h; the 1000 km row is used above 1000 km, the 150 km row below 150 km.
_VALLADO = np.array(
    [
        (150, 2.070e-9, 22.523), (180, 5.464e-10, 29.740), (200, 2.789e-10, 37.105),
        (250, 7.248e-11, 45.546), (300, 2.418e-11, 53.628), (350, 9.518e-12, 53.298),
        (400, 3.725e-12, 58.515), (450, 1.585e-12, 60.828), (500, 6.967e-13, 63.822),
        (600, 1.454e-13, 71.835), (700, 3.614e-14, 88.667), (800, 1.170e-14, 124.64),
        (900, 5.245e-15, 181.05), (1000, 3.019e-15, 268.00),
    ]
)  # fmt: skip
_H0, _RHO0, _SH = _VALLADO[:, 0], _VALLADO[:, 1], _VALLADO[:, 2]


def accel_gravity(r: np.ndarray) -> np.ndarray:
    """a = -mu r / |r|^3."""
    rn = np.linalg.norm(r, axis=-1, keepdims=True)
    return -MU * r / rn**3


def accel_j2(r: np.ndarray) -> np.ndarray:
    """a_J2 = -(3/2) J2 mu Re^2 / |r|^5 [x(1-5z^2/r^2), y(1-5z^2/r^2), z(3-5z^2/r^2)]."""
    r = np.asarray(r, dtype=float)
    rn2 = np.sum(r * r, axis=-1, keepdims=True)
    z2 = r[..., 2:3] ** 2 / rn2
    k = -1.5 * J2 * MU * RE**2 / rn2**2.5
    f = np.concatenate([1.0 - 5.0 * z2, 1.0 - 5.0 * z2, 3.0 - 5.0 * z2], axis=-1)
    return k * r * f


def density(h_m):
    """Exponential-atmosphere density [kg/m^3] at altitude h_m [m] (scalar or array)."""
    h_km = np.asarray(h_m, dtype=float) / 1e3
    i = np.clip(np.searchsorted(_H0, h_km, side="right") - 1, 0, len(_H0) - 1)
    rho = _RHO0[i] * np.exp(-(h_km - _H0[i]) / _SH[i])
    return float(rho) if rho.ndim == 0 else rho


def accel_drag(r, v, B, density_factor: float = 1.0) -> np.ndarray:
    """a_D = -1/2 rho(h) B |v_rel| v_rel, v_rel = v - omega_E x r, h = |r| - RE, B = Cd A / m.

    density_factor multiplies rho (storm / density-error knob, truth.density_factor)."""
    r, v = np.asarray(r, dtype=float), np.asarray(v, dtype=float)
    v_rel = v - OMEGA_E * np.stack([-r[..., 1], r[..., 0], np.zeros_like(r[..., 2])], axis=-1)
    rho = np.asarray(density(np.linalg.norm(r, axis=-1) - RE)) * density_factor
    k = 0.5 * rho * np.asarray(B, dtype=float) * np.linalg.norm(v_rel, axis=-1)
    return -k[..., None] * v_rel


def lvlh_dcm(r_c: np.ndarray, v_c: np.ndarray) -> np.ndarray:
    """3x3 ECI->LVLH rotation; rows x=r/|r|, y=z x x, z=(r x v)/|r x v|."""
    x = r_c / np.linalg.norm(r_c)
    h = np.cross(r_c, v_c)
    z = h / np.linalg.norm(h)
    return np.array([x, np.cross(z, x), z])


def thrust_eci(a_lvlh: np.ndarray, r_c: np.ndarray, v_c: np.ndarray) -> np.ndarray:
    """Commanded LVLH acceleration rotated to ECI: a_I = C^T a_LVLH."""
    return lvlh_dcm(r_c, v_c).T @ np.asarray(a_lvlh, dtype=float)


def rk4_step(state: np.ndarray, dt: float, accel_fn) -> np.ndarray:
    """Classical RK4 on s = [r, v] (shape (6,) or (N, 6)); accel_fn(r, v) -> acceleration."""

    def f(s):
        return np.concatenate([s[..., 3:], accel_fn(s[..., :3], s[..., 3:])], axis=-1)

    k1 = f(state)
    k2 = f(state + 0.5 * dt * k1)
    k3 = f(state + 0.5 * dt * k2)
    k4 = f(state + dt * k3)
    return state + dt / 6.0 * (k1 + 2.0 * k2 + 2.0 * k3 + k4)


def chief_initial(altitude_m: float, inc_deg: float, raan_deg: float) -> np.ndarray:
    """Circular ECI [r, v] at the ascending node (argument of latitude 0)."""
    a = RE + altitude_m
    vc = np.sqrt(MU / a)
    i, om = np.radians(inc_deg), np.radians(raan_deg)
    r = a * np.array([np.cos(om), np.sin(om), 0.0])
    v = vc * np.array([-np.sin(om) * np.cos(i), np.cos(om) * np.cos(i), np.sin(i)])
    return np.concatenate([r, v])


def _omega_lvlh(r_c: np.ndarray, v_c: np.ndarray) -> np.ndarray:
    return np.array([0.0, 0.0, np.linalg.norm(np.cross(r_c, v_c)) / (r_c @ r_c)])


def eci_to_lvlh(r_d, v_d, r_c, v_c) -> np.ndarray:
    """LVLH relative state [rho, rho_dot]: rho = C (r_d - r_c), rho_dot = C (v_d - v_c) - w x rho,
    w = (0, 0, |h|/|r_c|^2). r_d, v_d may be (3,) or (N, 3); returns (6,) or (N, 6)."""
    c = lvlh_dcm(r_c, v_c)
    rho = (np.asarray(r_d) - r_c) @ c.T
    rho_dot = (np.asarray(v_d) - v_c) @ c.T - np.cross(_omega_lvlh(r_c, v_c), rho)
    return np.concatenate([rho, rho_dot], axis=-1)


def lvlh_to_eci(rho6, r_c, v_c) -> tuple[np.ndarray, np.ndarray]:
    """Inverse of eci_to_lvlh. rho6 is (6,) or (N, 6); returns (r_d, v_d)."""
    c = lvlh_dcm(r_c, v_c)
    rho6 = np.asarray(rho6, dtype=float)
    rho, rho_dot = rho6[..., :3], rho6[..., 3:]
    return r_c + rho @ c, v_c + (rho_dot + np.cross(_omega_lvlh(r_c, v_c), rho)) @ c
