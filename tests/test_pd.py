"""PD control tests (docs/MASTER_PROMPT.md sections 3.2 and 3.8, gate G2).

Tests-first: cubesat/pd.py and the controlled propagator in cubesat/hcw.py do not
exist yet, so this file fails collection with ModuleNotFoundError/ImportError until
G2 implements them. Required contract:

    cubesat.hcw.propagate_controlled(state0, accel, t, n) -> np.ndarray (6,)
        state after t [s] under CW dynamics with a constant LVLH acceleration
        accel [m/s^2] held over [0, t] (the zero-order-hold step of the controller).

    cubesat.pd.PDController(wn, zeta=1.0, a_max=A_MAX_DEFAULT)
        .command(r, v, r_ref, v_ref) -> saturated u [m/s^2], ||u|| <= a_max
        .step(state, r_ref, v_ref, dt, n) -> (state_next, u)
        .dv_used : per-satellite delta-v [m/s], sum of |u|*dt (feeds log field dv_used)

    cubesat.pd.bang_bang_time_lower_bound(d_m, a_max) -> 2*sqrt(d_m/a_max) [s]
    cubesat.pd.A_MAX_DEFAULT == 1e-2  (research patch #1 overrides the master
    prompt's 1e-4; cold-gas class, ASSUMED ~8 kg / ~150 mN -- labelled assumption)

Required test names (MASTER_PROMPT 3.8): test_pd_step_response, test_saturation_respected,
test_passive_slot_low_dv. test_forced_propagator_matches_ode additionally verifies the
new controlled propagator against RK45 of the forced CW ODEs, same discipline as G1's
STM-vs-ODE check.

All quantities SI (AGENTS.md 3), LVLH frame (AGENTS.md 4); no wall clock, no RNG
(AGENTS.md 2). Chief altitude 500 km -> n ~ 1.1068e-3 rad/s (as in tests/test_hcw.py).
"""

import math

import numpy as np
from scipy.integrate import solve_ivp

from cubesat.hcw import drift_free_state, propagate, propagate_controlled
from cubesat.pd import A_MAX_DEFAULT, PDController, bang_bang_time_lower_bound

MU = 3.986004418e14  # Earth gravitational parameter, m^3/s^2
R_EARTH = 6378.137e3  # m
A_CHIEF = R_EARTH + 500e3  # m, 500 km altitude
N = math.sqrt(MU / A_CHIEF**3)  # rad/s, ~1.1068e-3
PERIOD = 2.0 * math.pi / N  # s, ~5677 s

WN = 0.01  # rad/s, natural frequency -- matches data/scenarios/nominal.json gains
ZETA = 1.0  # damping ratio (MASTER_PROMPT 3.2: zeta ~ 1)
DT = 2.0  # s, fixed step -- matches data/scenarios/nominal.json dt_s


def _forced_cw_rhs(_t, state, accel, n):
    """Forced CW ODEs (MASTER_PROMPT 3.1 with constant LVLH acceleration rows)."""
    x, y, z, vx, vy, vz = state
    ax, ay, az = accel
    return [
        vx,
        vy,
        vz,
        3.0 * n * n * x + 2.0 * n * vy + ax,
        -2.0 * n * vx + ay,
        -n * n * z + az,
    ]


def _run_chaser(ctrl, state0, ref0, dt, n_steps):
    """Step a chaser under `ctrl` toward the moving slot ref0 (propagated unforced).

    Returns (errors, u_norms): errors[k] = ||r - r_ref|| sampled at t = k*dt (row 0 is
    t = 0), u_norms[k] = ||u|| commanded over [k*dt, (k+1)*dt).
    """
    state = np.asarray(state0, dtype=float)
    ref0 = np.asarray(ref0, dtype=float)
    errors = np.empty(n_steps + 1)
    u_norms = np.empty(n_steps)
    errors[0] = float(np.linalg.norm(state[:3] - ref0[:3]))
    for k in range(n_steps):
        ref = np.asarray(propagate(ref0, k * dt, N))
        state, u = ctrl.step(state, ref[:3], ref[3:], dt, N)
        ref_next = np.asarray(propagate(ref0, (k + 1) * dt, N))
        errors[k + 1] = float(np.linalg.norm(state[:3] - ref_next[:3]))
        u_norms[k] = float(np.linalg.norm(u))
    return errors, u_norms


def _settling(errors, dt):
    """(t_settle, overshoot_frac) for the 5% band of errors[0].

    t_settle: first time after which the error never leaves the 5% band again.
    overshoot: worst error after first entering the band, relative to errors[0] --
    the 5%-overshoot criterion adapted to a moving reference via the error norm
    (critically damped approach from one side gives overshoot <= 5% by construction).
    """
    band = 0.05 * errors[0]
    inside = errors <= band
    assert inside.any(), "position error never entered the 5% band"
    first = int(np.argmax(inside))
    outside = np.nonzero(~inside[first:])[0]
    last_outside = first + int(outside[-1]) if outside.size else first - 1
    return (last_outside + 1) * dt, float(errors[first:].max()) / errors[0]


def test_forced_propagator_matches_ode():
    """G2's controlled step (STM + constant-acceleration forcing integral) matches RK45
    of the forced CW ODEs (same verify-don't-trust discipline as G1's STM-vs-ODE)."""
    state0 = np.array([500.0, -300.0, 200.0, 0.05, -0.02, 0.01])
    accel = np.array([1e-3, -5e-4, 2e-4])
    t = 300.0
    sol = solve_ivp(
        _forced_cw_rhs,
        (0.0, t),
        state0,
        args=(accel, N),
        method="RK45",
        rtol=1e-12,
        atol=1e-9,
    )
    assert sol.success
    ref = sol.y[:, -1]
    got = propagate_controlled(state0, accel, t, N)
    pos_rel = float(np.linalg.norm(got[:3] - ref[:3]) / np.linalg.norm(ref[:3]))
    vel_rel = float(np.linalg.norm(got[3:] - ref[3:]) / np.linalg.norm(ref[3:]))
    print(
        f"test_forced_propagator_matches_ode: position relative error = {pos_rel:.3e}, "
        f"velocity relative error = {vel_rel:.3e}"
    )
    assert pos_rel <= 1e-8, f"forced-propagator position relative error {pos_rel:.3e} > 1e-8"
    assert vel_rel <= 1e-8, f"forced-propagator velocity relative error {vel_rel:.3e} > 1e-8"


def test_pd_step_response():
    """MASTER_PROMPT 3.2 must-verify: step response of one chaser onto a moving passive slot.

    Chaser at the chief, at rest; slot = passive 2:1 ellipse with radial amplitude equal
    to the step size d. Overshoot < 5%, settles within 2x the bang-bang lower bound
    (t_target = 4*sqrt(d/a_max), computed, not tuned), commanded acceleration <= a_max.
    """
    a_max = A_MAX_DEFAULT
    d = 1000.0  # m, step size = slot radial amplitude
    ref0 = drift_free_state(d, 0.0, n=N)
    ctrl = PDController(wn=WN, zeta=ZETA, a_max=a_max)
    t_lb = bang_bang_time_lower_bound(d, a_max)
    t_target = 2.0 * t_lb
    errors, u_norms = _run_chaser(ctrl, np.zeros(6), ref0, DT, int(round(4000.0 / DT)))
    t_settle, overshoot = _settling(errors, DT)
    print(
        f"test_pd_step_response: overshoot = {100.0 * overshoot:.2f}% (limit 5%), "
        f"t_settle = {t_settle:.0f} s (target {t_target:.0f} s = 2x bang-bang bound "
        f"{t_lb:.0f} s), max |u| = {u_norms.max():.4f} m/s^2 (a_max = {a_max}), "
        f"dv_used = {ctrl.dv_used:.3f} m/s"
    )
    assert overshoot < 0.05, f"overshoot {100.0 * overshoot:.2f}% >= 5%"
    assert t_settle <= t_target, f"t_settle {t_settle:.0f} s > target {t_target:.0f} s"
    assert u_norms.max() <= a_max * (1 + 1e-9), "commanded acceleration exceeded a_max"


def test_saturation_respected():
    """MASTER_PROMPT 3.2: commanded acceleration never exceeds a_max, and saturation is
    actually exercised (a large reconfiguration starts fully saturated). The bang-bang
    lower bound for the reconfiguration distance is logged with the measured numbers.

    Geometry: chaser and slot on the SAME passive ellipse, a quarter period apart in
    phase (both endpoints drift-free -- the slot-to-slot reassignment case G4 faces).
    A rest-at-origin chase of a large-amplitude slot is NOT used: the slot's along-track
    speed (2*n*A) then exceeds what a_max = 1e-2 m/s^2 can catch (measured during G2: a
    5 km slot at ~11 m/s diverges under permanent saturation), so that setup tests
    actuator limits, not the controller."""
    a_max = A_MAX_DEFAULT
    assert A_MAX_DEFAULT == 1e-2, "research patch #1: default a_max must be 1e-2 m/s^2"
    amp = 1000.0
    ref0 = drift_free_state(amp, 0.0, n=N)
    chaser0 = np.asarray(propagate(ref0, -PERIOD / 4.0, N))  # same ellipse, earlier phase
    d = float(np.linalg.norm(chaser0[:3] - ref0[:3]))  # initial position error, ~2.24 km
    ctrl = PDController(wn=WN, zeta=ZETA, a_max=a_max)
    errors, u_norms = _run_chaser(ctrl, chaser0, ref0, DT, int(round(8000.0 / DT)))
    t_settle, _ = _settling(errors, DT)
    t_lb = bang_bang_time_lower_bound(d, a_max)
    print(
        f"test_saturation_respected: max |u| = {u_norms.max():.6f} m/s^2 (a_max = {a_max}), "
        f"bang-bang lower bound for d = {d:.1f} m: t >= {t_lb:.1f} s, "
        f"t_settle = {t_settle:.0f} s, dv_used = {ctrl.dv_used:.3f} m/s"
    )
    assert u_norms.max() <= a_max * (1 + 1e-9), "commanded acceleration exceeded a_max"
    assert u_norms.max() >= 0.999 * a_max, "saturation never engaged; test would be vacuous"


def test_passive_slot_low_dv():
    """MASTER_PROMPT 3.2 must-verify: a chaser already on its passive slot holds it with
    ~0 steady-state error and near-zero delta-v over a full ellipse period. This
    discriminates the moving-reference (v_ref) form: a static-target form would fight
    the slot's 2:1 motion and burn delta-v every step."""
    ref0 = drift_free_state(1000.0, 500.0, n=N)  # slot with radial + cross-track amplitude
    ctrl = PDController(wn=WN, zeta=ZETA, a_max=A_MAX_DEFAULT)
    errors, u_norms = _run_chaser(ctrl, ref0.copy(), ref0, DT, int(round(PERIOD / DT)))
    max_err = float(errors.max())
    print(
        f"test_passive_slot_low_dv: max position error over one orbit = {max_err:.3e} m, "
        f"dv_used = {ctrl.dv_used:.3e} m/s, max |u| = {u_norms.max():.3e} m/s^2"
    )
    assert max_err < 1e-4, f"steady-state error {max_err:.3e} m not ~0 on an occupied slot"
    assert ctrl.dv_used < 1e-6, f"delta-v {ctrl.dv_used:.3e} m/s not near-zero on an occupied slot"
