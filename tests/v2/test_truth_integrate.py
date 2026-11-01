"""Task 1.4: RK4 step, chief initial state, ECI<->LVLH transforms."""

import math
import time

import numpy as np
from scipy.integrate import solve_ivp

from cubesat import truth

ALT = 500e3


def _grav_j2(r, v):
    return truth.accel_gravity(r) + truth.accel_j2(r)


def _f_grav_j2(_t, s):
    return np.concatenate([s[3:], _grav_j2(s[:3], s[3:])])


def test_chief_initial_is_circular_with_requested_plane():
    s = truth.chief_initial(ALT, 97.4, 30.0)
    r, v = s[:3], s[3:]
    assert math.isclose(np.linalg.norm(r), truth.RE + ALT, rel_tol=1e-14)
    assert math.isclose(np.linalg.norm(v), math.sqrt(truth.MU / (truth.RE + ALT)), rel_tol=1e-14)
    assert abs(r @ v) < 1e-6
    h = np.cross(r, v)
    assert math.isclose(math.degrees(math.acos(h[2] / np.linalg.norm(h))), 97.4, abs_tol=1e-9)
    # RAAN: node direction (z of r = 0 at the node) is at 30 deg
    assert math.isclose(math.degrees(math.atan2(r[1], r[0])), 30.0, abs_tol=1e-9)


def test_lvlh_roundtrip_under_1e6_m():
    c = truth.chief_initial(ALT, 97.4, 30.0)
    # advance the chief a quarter orbit so the frame is generic
    for _ in range(700):
        c = truth.rk4_step(c, 2.0, _grav_j2)
    rng = np.random.default_rng(0)
    worst = 0.0
    for _ in range(20):
        rho6 = np.concatenate([rng.uniform(-8e3, 8e3, 3), rng.uniform(-10, 10, 3)])
        r_d, v_d = truth.lvlh_to_eci(rho6, c[:3], c[3:])
        back = truth.eci_to_lvlh(r_d, v_d, c[:3], c[3:])
        worst = max(worst, float(np.max(np.abs(back - rho6))))
        r2, v2 = truth.lvlh_to_eci(back, c[:3], c[3:])
        worst = max(worst, float(np.max(np.abs(np.concatenate([r2 - r_d, v2 - v_d])))))
    print(f"LVLH round trip worst abs error = {worst:.3e}")
    assert worst < 1e-6


def test_lvlh_batch_matches_single():
    c = truth.chief_initial(ALT, 97.4, 0.0)
    rho = np.array([[1000.0, 0, 0, 0, 0, 0], [0, 5000.0, 200.0, 0.1, -0.2, 0.3]])
    r, v = truth.lvlh_to_eci(rho, c[:3], c[3:])
    for k in range(2):
        r1, v1 = truth.lvlh_to_eci(rho[k], c[:3], c[3:])
        assert np.allclose(r[k], r1, atol=1e-9) and np.allclose(v[k], v1, atol=1e-12)
    assert np.allclose(truth.eci_to_lvlh(r, v, c[:3], c[3:]), rho, atol=1e-6)


def test_lvlh_matches_cw_for_small_offsets():
    """Chief circular, deputy 100 m radial: eci_to_lvlh gives that offset in LVLH (frame sanity)."""
    c = truth.chief_initial(ALT, 97.4, 10.0)
    r_d = c[:3] + 100.0 * c[:3] / np.linalg.norm(c[:3])
    out = truth.eci_to_lvlh(r_d, c[3:], c[:3], c[3:])
    assert np.allclose(out[:3], [100.0, 0, 0], atol=1e-9)


def test_rk4_dt2_vs_rk45_two_body_j2_3orbits_500km():
    s0 = truth.chief_initial(ALT, 97.4, 0.0)
    period = 2.0 * math.pi * math.sqrt((truth.RE + ALT) ** 3 / truth.MU)
    n_steps = int(3 * period / 2.0)
    t_eval = np.arange(0, n_steps + 1, 100) * 2.0
    t0 = time.perf_counter()
    ref = solve_ivp(
        _f_grav_j2, (0, t_eval[-1]), s0, method="RK45", rtol=1e-12, atol=1e-9, t_eval=t_eval
    )
    t_ref = time.perf_counter() - t0
    tight = solve_ivp(
        _f_grav_j2, (0, t_eval[-1]), s0, method="DOP853", rtol=1e-13, atol=1e-10, t_eval=t_eval
    )
    s, err, err_tight = s0.copy(), [], []
    t0 = time.perf_counter()
    for k in range(n_steps + 1):
        if k % 100 == 0:
            err.append(np.linalg.norm(s[:3] - ref.y[:3, k // 100]))
            err_tight.append(np.linalg.norm(s[:3] - tight.y[:3, k // 100]))
        s = truth.rk4_step(s, 2.0, _grav_j2)
    t_rk4 = time.perf_counter() - t0
    ref_gap = np.abs(ref.y[:3] - tight.y[:3]).max()
    print(
        f"RK4(dt=2) vs RK45(rtol 1e-12): max position error {max(err):.3e} m over "
        f"{n_steps} steps (RK4 {t_rk4:.1f} s, RK45 {t_ref:.1f} s); vs DOP853 (rtol 1e-13) "
        f"{max(err_tight):.3e} m; RK45-vs-DOP853 reference gap {ref_gap:.3e} m"
    )
    assert max(err) < 1e-2
    assert max(err_tight) < 1e-2


def _decay_one_rev(area_m2, inc_deg=90.0):
    B = 2.2 * area_m2 / 4.0
    s = truth.chief_initial(ALT, inc_deg, 0.0)  # 90: omega_E x r is perpendicular to v

    def sma(x):
        return -truth.MU / (2.0 * (x[3:] @ x[3:] / 2.0 - truth.MU / np.linalg.norm(x[:3])))

    def accel(r, v):
        return truth.accel_gravity(r) + truth.accel_drag(r, v, B)

    a0 = sma(s)
    n = math.sqrt(truth.MU / a0**3)
    for _ in range(round(2.0 * math.pi / n / 2.0)):
        s = truth.rk4_step(s, 2.0, accel)
    return sma(s) - a0


def test_drag_decay_numeric_per_rev():
    active, dead = _decay_one_rev(0.010), _decay_one_rev(0.035)
    print(f"RK4 numeric decay per rev at 500 km: active {active:.4f} m, dead {dead:.4f} m")
    assert abs(active - (-1.14)) / 1.14 < 0.05
    assert abs(dead - (-3.99)) / 3.99 < 0.05


def test_rk4_batch_matches_single():
    c = truth.chief_initial(ALT, 97.4, 0.0)
    batch = np.stack([c, c + np.array([1000.0, 0, 0, 0, 1.0, 0])])
    out = truth.rk4_step(batch, 2.0, _grav_j2)
    for k in range(2):
        assert np.allclose(out[k], truth.rk4_step(batch[k], 2.0, _grav_j2), rtol=0, atol=1e-9)


def test_drag_decay_numeric_per_rev_at_scenario_inclination():
    """97.4 deg (scenario default): the co-rotating atmosphere makes the decay ~1.8% larger than
    the polar value; the ratio check (1.010..1.030) fails if Earth rotation is dropped."""
    active, dead = _decay_one_rev(0.010, 97.4), _decay_one_rev(0.035, 97.4)
    ratio = active / _decay_one_rev(0.010, 90.0)
    print(f"97.4 deg decay per rev: active {active:.4f} m, dead {dead:.4f} m, ratio {ratio:.4f}")
    assert abs(active - (-1.14)) / 1.14 < 0.05
    assert abs(dead - (-3.99)) / 3.99 < 0.05
    assert 1.010 < ratio < 1.030
