"""PD control with thrust saturation and per-satellite delta-v accounting (gate G2).

Control law (docs/MASTER_PROMPT.md section 3.2): u = -Kp*(r - r_ref) - Kd*(v - v_ref)
with Kp = wn^2, Kd = 2*zeta*wn, zeta ~ 1. The reference is a MOVING slot on the passive
drift-free ellipse -- v_ref must be the slot's own ellipse velocity; a static-target
form (v_ref = 0) fights the natural 2:1 motion and wastes delta-v.

One PDController per satellite; dv_used accumulates |u|*dt [m/s] and feeds the run-log
field dv_used (MASTER_PROMPT section 5).

Units SI (AGENTS.md 3): m, m/s, m/s^2, s. LVLH frame (AGENTS.md 4). No wall clock
(AGENTS.md 2): fixed dt, analytic STM step plus the exact constant-acceleration forcing
term (cubesat.hcw.propagate_controlled).
"""

from __future__ import annotations

import math

import numpy as np

from cubesat.hcw import propagate_controlled

# Thrust saturation, m/s^2. Research patch #1 overrides the master prompt's 1e-4:
# cold-gas class, ASSUMED ~8 kg CubeSat with ~150 mN thruster (mass/thrust figures are
# an unverified assumption, labelled as such). Scenario parameter; nominal.json uses 0.01.
A_MAX_DEFAULT = 1e-2


def bang_bang_time_lower_bound(d_m: float, a_max: float) -> float:
    """Rest-to-rest reconfiguration lower bound t >= 2*sqrt(d/a_max) [s] for distance
    d_m under |a| <= a_max (MASTER_PROMPT 3.2; research patch #1: log per reconfig).

    A reference number for achievable reconfiguration time, not an assertion about the
    closed loop: CW natural dynamics can assist or oppose, so a PD trajectory is not
    bound by it in general.
    """
    return 2.0 * math.sqrt(d_m / a_max)


class PDController:
    """PD law with thrust saturation and per-satellite delta-v accounting.

    The reference is the slot state (r_ref, v_ref) at the CURRENT sim time; for a
    passive slot that is cubesat.hcw.propagate(slot_state0, t, n).
    """

    def __init__(self, wn: float, zeta: float = 1.0, a_max: float = A_MAX_DEFAULT) -> None:
        self.wn = float(wn)
        self.zeta = float(zeta)
        self.a_max = float(a_max)
        self.kp = self.wn * self.wn
        self.kd = 2.0 * self.zeta * self.wn
        self.dv_used = 0.0  # m/s, accumulated |u|*dt

    def command(self, r, v, r_ref, v_ref) -> np.ndarray:
        """Saturated acceleration command [m/s^2] from the full-state error against the
        moving reference. Saturation clamps the vector magnitude: ||u|| <= a_max."""
        r_err = np.asarray(r, dtype=float) - np.asarray(r_ref, dtype=float)
        v_err = np.asarray(v, dtype=float) - np.asarray(v_ref, dtype=float)
        u = -self.kp * r_err - self.kd * v_err
        norm = float(np.linalg.norm(u))
        if norm > self.a_max:
            u *= self.a_max / norm
        return u

    def step(self, state, r_ref, v_ref, dt: float, n: float) -> tuple[np.ndarray, np.ndarray]:
        """One fixed-dt step: command from the error at the current instant, hold it over
        [t, t+dt), advance with STM + exact forcing. Returns (state_next, u).

        r_ref / v_ref are the reference slot state at the current sim time. dv_used
        accumulates |u|*dt (per-satellite delta-v, MASTER_PROMPT section 5 dv_used).
        """
        state = np.asarray(state, dtype=float)
        u = self.command(state[:3], state[3:], r_ref, v_ref)
        self.dv_used += float(np.linalg.norm(u)) * dt
        return propagate_controlled(state, u, dt, n), u
