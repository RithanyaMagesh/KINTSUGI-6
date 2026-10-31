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
