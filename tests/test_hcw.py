"""HCW linear relative-motion tests (docs/MASTER_PROMPT.md sections 3.1 and 3.8, gate G1).

Tests-first: cubesat/hcw.py does not exist yet, so this file fails collection with
ModuleNotFoundError until G1 implements it. Required contract:

    cubesat.hcw.stm_propagate(state0, t, n) -> np.ndarray

    state0 : array-like shape (6,) -- [x, y, z, vx, vy, vz] at t=0, SI (m, m/s),
             LVLH frame: x radial, y along-track, z cross-track (AGENTS.md 3, 4).
    t      : float or 1D array of times [s]; t=0 allowed.
    n      : chief mean motion [rad/s] of the circular chief orbit.
    returns: shape (6,) for scalar t, else (len(t), 6); row k is the unforced state
             at t[k] from the analytic CW STM (docs/MASTER_PROMPT.md section 3.1).

All quantities SI internally (AGENTS.md invariant 3); no wall-clock, no RNG
(invariant 2). mu = 3.986004418e14 m^3/s^2, Earth radius 6378.137e3 m, chief
altitude 500 km -> a = 6.878137e6 m and n ~ 1.1068e-3 rad/s.
"""

import math

import numpy as np
import pytest
from scipy.integrate import solve_ivp

from cubesat.hcw import stm_propagate

MU = 3.986004418e14  # Earth gravitational parameter, m^3/s^2
R_EARTH = 6378.137e3  # m
A_CHIEF = R_EARTH + 500e3  # m, 500 km altitude
N = math.sqrt(MU / A_CHIEF**3)  # rad/s, ~1.1068e-3
PERIOD = 2.0 * math.pi / N  # s, ~5677 s

# Hardcoded initial states [x, y, z, vx, vy, vz] (no RNG, invariant 2): position
# offsets of order 1 km, velocity offsets of order 1 m/s, mixed signs/components.
INITIAL_STATES = [
    np.array([1000.0, 0.0, 500.0, 0.5, 1.0, -0.5]),
    np.array([-750.0, 2000.0, -300.0, -0.75, 0.5, 0.25]),
    np.array([1500.0, -1000.0, 800.0, 0.25, -1.0, 0.75]),
]


def _cw_rhs(_t, state, n):
    """Unforced CW ODEs (MASTER_PROMPT 3.1): x''-3n^2*x-2n*y'=0, y''+2n*x'=0, z''+n^2*z=0."""
    x, y, z, vx, vy, vz = state
    return [vx, vy, vz, 3.0 * n * n * x + 2.0 * n * vy, -2.0 * n * vx, -n * n * z]


def _ode_propagate(state0, t_eval, n):
    sol = solve_ivp(
        _cw_rhs,
        (0.0, float(t_eval[-1])),
        state0,
        args=(n,),
        method="RK45",
        rtol=1e-12,
        atol=1e-9,
        t_eval=t_eval,
    )
    assert sol.success
    return sol.y.T


def test_hcw_stm_vs_ode():
    """Analytic STM matches RK45 integration of the CW ODEs to <=1e-6 relative over 3 orbits."""
    t_grid = np.linspace(0.0, 3.0 * PERIOD, 301)
    worst_pos = worst_vel = 0.0
    for state0 in INITIAL_STATES:
        ref = _ode_propagate(state0, t_grid, N)
        stm = np.asarray(stm_propagate(state0, t_grid, N))
        d_pos = np.linalg.norm(stm[:, :3] - ref[:, :3], axis=1)
        d_vel = np.linalg.norm(stm[:, 3:] - ref[:, 3:], axis=1)
        pos_rel = d_pos / np.linalg.norm(ref[:, :3], axis=1)
        vel_rel = d_vel / np.linalg.norm(ref[:, 3:], axis=1)
        worst_pos = max(worst_pos, float(pos_rel.max()))
        worst_vel = max(worst_vel, float(vel_rel.max()))
    # Gate evidence: the measured errors are printed so GATES.md can record them
    # with the command that produced them (AGENTS.md invariant 1).
    print(
        f"test_hcw_stm_vs_ode: max position relative error = {worst_pos:.3e}, "
        f"max velocity relative error = {worst_vel:.3e}"
    )
    assert worst_pos <= 1e-6, f"max position relative error {worst_pos:.3e} > 1e-6"
    assert worst_vel <= 1e-6, f"max velocity relative error {worst_vel:.3e} > 1e-6"


def test_drift_free_ellipse_closes():
    """Drift-free state (vy0 = -2*n*x0) returns to itself after one period; 2:1 ellipse."""
    x0 = 1000.0
    state0 = np.array([x0, 0.0, 500.0, 0.0, -2.0 * N * x0, 0.0])
    final = np.asarray(stm_propagate(state0, PERIOD, N))
    pos_rel = np.linalg.norm(final[:3] - state0[:3]) / np.linalg.norm(state0[:3])
    vel_rel = np.linalg.norm(final[3:] - state0[3:]) / np.linalg.norm(state0[3:])
    assert pos_rel <= 1e-6, f"closure position relative error {pos_rel:.3e} > 1e-6"
    assert vel_rel <= 1e-6, f"closure velocity relative error {vel_rel:.3e} > 1e-6"
    # 2:1 ellipse: at a quarter period the along-track excursion is 2*x0
    # (analytically y = -2*x0*sin(nt), so exactly -2000 m at nt = pi/2).
    y_quarter = float(np.asarray(stm_propagate(state0, math.pi / (2.0 * N), N))[1])
    assert abs(abs(y_quarter) - 2.0 * x0) <= 1e-9 * 2.0 * x0


@pytest.mark.slow
def test_cw_vs_kepler_error_report():
    """Nonlinear check (MASTER_PROMPT 3.1c): CW/STM vs independent two-body propagation.

    Chief and chaser start on the same circular inertial orbit, the chaser offset by
    the passive-ellipse initial state (radial amplitude 1 km, drift-free vy0, z0=500 m).
    The max position error over the sampled times is printed in metres; only a loose
    sanity bound (<10 km) is asserted -- the measured value is recorded, not tuned.
    """
    x0 = 1000.0
    rho0 = np.array([x0, 0.0, 500.0])  # LVLH position offset
    nu0 = np.array([0.0, -2.0 * N * x0, 0.0])  # drift-free LVLH velocity
    r_chief0 = np.array([A_CHIEF, 0.0, 0.0])
    v_chief0 = np.array([0.0, N * A_CHIEF, 0.0])
    # At t=0 the LVLH axes coincide with the inertial axes. Rotating-frame velocity
    # maps to inertial via the transport theorem: drho/dt|inertial = nu + omega x rho.
    omega = np.array([0.0, 0.0, N])
    r_chaser0 = r_chief0 + rho0
    v_chaser0 = v_chief0 + nu0 + np.cross(omega, rho0)

    t_end = 3.0 * PERIOD
    t_grid = np.linspace(0.0, t_end, 601)

    def two_body(_t, state):
        r = state[:3]
        return np.concatenate([state[3:], -MU * r / np.linalg.norm(r) ** 3])

    chief = solve_ivp(
        two_body,
        (0.0, t_end),
        np.concatenate([r_chief0, v_chief0]),
        rtol=1e-12,
        atol=1e-9,
        t_eval=t_grid,
    )
    chaser = solve_ivp(
        two_body,
        (0.0, t_end),
        np.concatenate([r_chaser0, v_chaser0]),
        rtol=1e-12,
        atol=1e-9,
        t_eval=t_grid,
    )
    assert chief.success and chaser.success

    cw = np.asarray(stm_propagate(np.concatenate([rho0, nu0]), t_grid, N))

    max_err = 0.0
    for k in range(t_grid.size):
        r_c = chief.y[:3, k]
        v_c = chief.y[3:, k]
        dr = chaser.y[:3, k] - r_c  # chaser minus the chief the CW frame is anchored to
        x_hat = r_c / np.linalg.norm(r_c)
        h_hat = np.cross(r_c, v_c)
        h_hat = h_hat / np.linalg.norm(h_hat)
        y_hat = np.cross(h_hat, x_hat)
        rho_kepler = np.array([dr @ x_hat, dr @ y_hat, dr @ h_hat])
        max_err = max(max_err, float(np.linalg.norm(rho_kepler - cw[k, :3])))

    print(f"test_cw_vs_kepler_error_report: max position error over 3 orbits = {max_err:.3f} m")
    assert max_err < 10_000.0, f"CW-vs-Kepler sanity bound exceeded: {max_err:.3f} m"
