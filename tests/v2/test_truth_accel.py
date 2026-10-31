"""Task 1.3: truth accelerations (gravity, J2, drag, thrust rotation, LVLH DCM)."""

import json
import math
from pathlib import Path

import numpy as np

from cubesat import truth
from cubesat.scenario import Scenario

ROOT = Path(__file__).resolve().parents[2]

# Vallado, Fundamentals of Astrodynamics and Applications, Table 8-4 (h0 km, rho0 kg/m3, H km),
# copied from docs/superpowers/plans/2026-10-31-physics-v2-plan.md Task 1.3.
VALLADO = [
    (150, 2.070e-9, 22.523),
    (180, 5.464e-10, 29.740),
    (200, 2.789e-10, 37.105),
    (250, 7.248e-11, 45.546),
    (300, 2.418e-11, 53.628),
    (350, 9.518e-12, 53.298),
    (400, 3.725e-12, 58.515),
    (450, 1.585e-12, 60.828),
    (500, 6.967e-13, 63.822),
    (600, 1.454e-13, 71.835),
    (700, 3.614e-14, 88.667),
    (800, 1.170e-14, 124.64),
    (900, 5.245e-15, 181.05),
    (1000, 3.019e-15, 268.00),
]


def _u_j2(r):
    """J2 part of the geopotential (positive-potential convention), brief PV2 section 4."""
    rn = np.linalg.norm(r)
    sin2 = (r[2] / rn) ** 2
    return -(truth.MU / rn) * truth.J2 * (truth.RE / rn) ** 2 * (3.0 * sin2 - 1.0) / 2.0


def test_j2_matches_potential_gradient():
    r = np.array([4.2e6, -3.1e6, 4.4e6])
    h = 10.0
    grad = np.array([(_u_j2(r + h * e) - _u_j2(r - h * e)) / (2.0 * h) for e in np.eye(3)])
    a = truth.accel_j2(r)
    rel = np.linalg.norm(a - grad) / np.linalg.norm(grad)
    print(f"J2 gradient rel err = {rel:.3e}")
    assert rel < 1e-5


def test_gravity_is_central():
    r = np.array([6.9e6, 1.0e6, -2.0e6])
    a = truth.accel_gravity(r)
    assert np.allclose(a, -truth.MU * r / np.linalg.norm(r) ** 3, rtol=1e-14)


def _polar_circular(alt_m):
    """Polar circular state: v is perpendicular to omega_earth x r, so |v_rel| ~ v."""
    r = truth.RE + alt_m
    return np.array([r, 0.0, 0.0]), np.array([0.0, 0.0, math.sqrt(truth.MU / r)])


def _decay_per_rev(area_m2):
    B = 2.2 * area_m2 / 4.0
    r, v = _polar_circular(500e3)
    a_t = float(truth.accel_drag(r, v, B) @ v / np.linalg.norm(v))  # along-track (negative)
    n = math.sqrt(truth.MU / np.linalg.norm(r) ** 3)
    return 2.0 * a_t / n * (2.0 * math.pi / n)  # Gauss: da/dt = 2 a_T / n (circular)


def test_drag_decay_per_rev_king_hele():
    active, dead = _decay_per_rev(0.010), _decay_per_rev(0.035)
    print(f"King-Hele decay per rev at 500 km: active {active:.4f} m, dead {dead:.4f} m")
    assert abs(active - (-1.14)) / 1.14 < 0.05
    assert abs(dead - (-3.99)) / 3.99 < 0.05


def test_thrust_rotation_roundtrip():
    r_c, v_c = _polar_circular(500e3)
    a_eci = truth.thrust_eci(np.array([0.01, 0.0, 0.0]), r_c, v_c)
    assert np.allclose(a_eci, 0.01 * r_c / np.linalg.norm(r_c), atol=1e-15)
    a_l = np.array([0.003, -0.002, 0.005])
    assert np.allclose(truth.lvlh_dcm(r_c, v_c) @ truth.thrust_eci(a_l, r_c, v_c), a_l, atol=1e-15)


def test_lvlh_dcm_rows_orthonormal_right_handed():
    r_c, v_c = np.array([6.9e6, 1e5, 2e5]), np.array([-100.0, 7.4e3, 800.0])
    c = truth.lvlh_dcm(r_c, v_c)
    assert np.allclose(c @ c.T, np.eye(3), atol=1e-14)
    assert np.allclose(c[0], r_c / np.linalg.norm(r_c))
    assert np.allclose(c[2], np.cross(r_c, v_c) / np.linalg.norm(np.cross(r_c, v_c)))
    assert np.allclose(np.cross(c[0], c[1]), c[2], atol=1e-14)


def test_drag_density_defined_at_schema_extremes():
    lo, hi = truth.density(161e3), truth.density(1999e3)
    assert math.isfinite(lo) and math.isfinite(hi) and lo > 0 and hi > 0
    hs = np.arange(150e3, 2000e3, 500.0)
    rho = np.array([truth.density(h) for h in hs])
    assert np.all(np.isfinite(rho)) and np.all(rho > 0)
    assert np.all(np.diff(rho) <= 0)


def test_density_table_matches_vallado_rows():
    assert len(VALLADO) == 14
    for h0, rho0, _H in VALLADO:
        assert truth.density(h0 * 1e3) == rho0
    # row selection: largest h0 <= h, and the 1000 km row above 1000 km
    h0, rho0, H = VALLADO[8]  # 500 km row
    assert math.isclose(truth.density(550e3), rho0 * math.exp(-50.0 / H), rel_tol=1e-12)
    h0, rho0, H = VALLADO[-1]
    assert math.isclose(truth.density(1500e3), rho0 * math.exp(-500.0 / H), rel_tol=1e-12)


def test_density_factor_scales_drag_linearly():
    r, v = _polar_circular(500e3)
    base = truth.accel_drag(r, v, 0.0055)
    assert np.allclose(truth.accel_drag(r, v, 0.0055, density_factor=3.0), 3.0 * base, rtol=1e-14)
    assert np.all(truth.accel_drag(r, v, 0.0055, density_factor=0.0) == 0.0)


def test_truth_block_defaults_are_illustrative_and_v1_neutral():
    payload = json.loads((ROOT / "data" / "scenarios" / "nominal.json").read_text())
    t = Scenario.model_validate(payload).truth
    assert (t.cd, t.area_active_m2, t.area_dead_m2, t.mass_kg, t.density_factor) == (
        2.2,
        0.010,
        0.035,
        4.0,
        1.0,
    )
    assert t.j2_enabled is True
