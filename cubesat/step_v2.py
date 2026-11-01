"""One truth step of the v2 swarm, shared by EngineV2 (cubesat/sim_v2.py) and the plan
certificate's forward simulation (cubesat/certify_sim.py), so the executor and the certificate
cannot drift apart. Pure apart from `sats` (thrust_limited spends their propellant)."""

from __future__ import annotations

import numpy as np

from cubesat import truth
from cubesat.faults_v2 import STATUS_REENTERED
from cubesat.sim import STATUS_DEAD
from cubesat.spacecraft import thrust_limited

REENTRY_ALTITUDE_M = 100e3  # below this a sat is flagged REENTERED and frozen


def advance(X, lvlh, refs, status, sats, pd, dt, tr, cmd=None):
    """Command per sat that can still fly (LVLH, zero-order hold): `cmd[i]` when given (a
    planned burn or an evasion), else PD to its seat `refs[i]`; every command through
    thrust_limited (cap k F_max / m, propellant use). A stuck-open thruster ignores both and
    fires along its fixed ECI vector. Then one batched RK4 step (row 0 = chief, no drag);
    re-entered sats stay frozen. `tr` = scenario.truth. Returns (X_new, u LVLH, a_stuck ECI)."""
    n_sats = len(status)
    cmd = cmd or {}
    u = np.zeros((n_sats, 3))  # applied LVLH acceleration
    a_stuck = np.zeros((n_sats, 3))  # applied ECI acceleration of stuck-open sats
    for i, s in enumerate(status):
        if s in (STATUS_DEAD, STATUS_REENTERED):
            continue
        sat = sats[i]
        if sat.stuck_vec is not None:
            a_stuck[i], _ = thrust_limited(sat, u[i], dt)
        else:
            if i in cmd:
                c = cmd[i]
            else:
                c = pd.command(lvlh[i, :3], lvlh[i, 3:], refs[i, :3], refs[i, 3:])
            u[i], _ = thrust_limited(sat, c, dt)
    a_dep = truth.thrust_eci(u, X[0, :3], X[0, 3:]) + a_stuck
    a_thrust = np.vstack([np.zeros(3), a_dep])
    b_active, b_dead = tr.cd * tr.area_active_m2 / tr.mass_kg, tr.cd * tr.area_dead_m2 / tr.mass_kg
    b = np.array([0.0] + [b_dead if s == STATUS_DEAD else b_active for s in status])

    def accel(r, v):
        a = truth.accel_gravity(r) + truth.accel_drag(r, v, b, tr.density_factor) + a_thrust
        return a + truth.accel_j2(r) if tr.j2_enabled else a

    new = truth.rk4_step(X, dt, accel)
    frozen = np.array([False] + [s == STATUS_REENTERED for s in status])  # chief never frozen
    return np.where(frozen[:, None], X, new), u, a_stuck
