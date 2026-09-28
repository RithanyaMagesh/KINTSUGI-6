"""Hill-Clohessy-Wiltshire linear relative motion (unforced chief, circular orbit).

Units are SI throughout (AGENTS.md invariant 3): position in m, velocity in m/s,
time in s, mean motion n in rad/s. State ordering is [x, y, z, vx, vy, vz] in the
chief LVLH frame: x radial, y along-track, z cross-track (AGENTS.md invariant 4).

Formula source: the analytic CW STM written in docs/MASTER_PROMPT.md section 3.1
(rows follow it term for term). It is verified against numerical integration of
the CW ODEs by tests/test_hcw.py (MASTER_PROMPT 3.1 "must verify" items) -- do
not trust it blindly, the tests are the guard.
"""

from __future__ import annotations

import math

import numpy as np

MU = 3.986004418e14  # Earth gravitational parameter, m^3/s^2
R_EARTH = 6378.137e3  # m


def mean_motion(altitude_m: float) -> float:
    """Mean motion n [rad/s] of a circular orbit at altitude_m above Earth."""
    return math.sqrt(MU / (R_EARTH + altitude_m) ** 3)


def stm(t: float, n: float) -> np.ndarray:
    """6x6 analytic CW state-transition matrix at time t [s], mean motion n [rad/s].

    Maps [x0, y0, z0, vx0, vy0, vz0] to [x, y, z, vx, vy, vz]; terms are exactly
    the solution in docs/MASTER_PROMPT.md section 3.1, with c = cos(n*t), s = sin(n*t).
    Identity at t = 0.
    """
    nt = n * t
    c = math.cos(nt)
    s = math.sin(nt)
    return np.array(
        [
            [4.0 - 3.0 * c, 0.0, 0.0, s / n, 2.0 * (1.0 - c) / n, 0.0],
            [
                6.0 * (s - nt),
                1.0,
                0.0,
                -2.0 * (1.0 - c) / n,
                (4.0 * s - 3.0 * nt) / n,
                0.0,
            ],
            [0.0, 0.0, c, 0.0, 0.0, s / n],
            [3.0 * n * s, 0.0, 0.0, c, 2.0 * s, 0.0],
            [6.0 * n * (c - 1.0), 0.0, 0.0, -2.0 * s, 4.0 * c - 3.0, 0.0],
            [0.0, 0.0, -n * s, 0.0, 0.0, c],
        ]
    )


def propagate(state0, t, n) -> np.ndarray:
    """Propagate state0 with the analytic STM (no forces).

    t scalar -> shape (6,); t a 1D array of times -> shape (len(t), 6) whose row
    k is the state at t[k]. This behavior is the stm_propagate contract that
    tests/test_hcw.py imports.
    """
    state = np.asarray(state0, dtype=float)
    times = np.asarray(t, dtype=float)
    if times.ndim == 0:
        return stm(float(times), n) @ state
    return np.array([stm(tk, n) @ state for tk in times])


# Name the G1 tests import (tests/test_hcw.py); same function as propagate.
stm_propagate = propagate


def drift_free_state(x0: float, z0: float = 0.0, *, n: float) -> np.ndarray:
    """Initial state on the passive (drift-free) 2:1 ellipse: vx0 = 0, vy0 = -2*n*x0, vz0 = 0.

    Returns [x0, 0, z0, 0, -2*n*x0, 0] (SI, LVLH); closes after one period 2*pi/n.
    n is keyword-only because the requested signature (x0, z0=0, n) is not valid
    Python (non-default after default) and the order was kept as requested.
    """
    return np.array([x0, 0.0, z0, 0.0, -2.0 * n * x0, 0.0])


def forcing_matrix(t: float, n: float) -> np.ndarray:
    """G(t) = integral_0^t of the STM's velocity columns: maps a constant acceleration
    held in LVLH over [0, t] to the state it produces on top of the unforced motion.

    Terms are the analytic integrals of the MASTER_PROMPT 3.1 rows (G = int Phi ds @ B,
    B = [0; I]). Double-integrator limit at small t: G ~ [[t^2/2 I3], [t I3]].
    Verified against RK45 of the forced CW ODEs by tests/test_pd.py.
    """
    nt = n * t
    c = math.cos(nt)
    s = math.sin(nt)
    n2 = n * n
    return np.array(
        [
            [(1.0 - c) / n2, 2.0 * (nt - s) / n2, 0.0],
            [-2.0 * (nt - s) / n2, (4.0 * (1.0 - c) - 1.5 * nt * nt) / n2, 0.0],
            [0.0, 0.0, (1.0 - c) / n2],
            [s / n, 2.0 * (1.0 - c) / n, 0.0],
            [-2.0 * (1.0 - c) / n, 4.0 * s / n - 3.0 * t, 0.0],
            [0.0, 0.0, s / n],
        ]
    )


def propagate_controlled(state0, accel, t, n) -> np.ndarray:
    """Propagate state0 for t [s] under CW dynamics with `accel` [m/s^2] held constant
    in LVLH over [0, t]: Phi(t) @ x0 + G(t) @ a. Exact for the zero-order-hold step the
    PD controller uses (cubesat/pd.py); scalar t only. SI, LVLH throughout.
    """
    state = np.asarray(state0, dtype=float)
    a = np.asarray(accel, dtype=float)
    return stm(float(t), n) @ state + forcing_matrix(float(t), n) @ a
