"""Per-satellite propulsion and mass for engine v2 (Phase 2, fuel-first subset).

Formulas: docs/superpowers/specs/2026-10-31-physics-v2-brief.md section 4 Phase 2, listed with
defaults and validation commands in docs/PHYSICS_V2.md. SI units. Power/eclipse (Task 2.2) is
NOT built: SatState has no battery fields.

    |F| <= k F_max,  a = F / m,  mdot = |F| / (Isp g0),  g0 = 9.80665 m/s^2
    tank delta-v = Isp g0 ln(m / (m - m_prop))

Defaults are illustrative (3U, 4.0 kg wet, 0.2 kg propellant, Isp 40 s, F_max 0.04 N).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from cubesat.scenario import FailureMode, Scenario

G0 = 9.80665  # m/s^2
PARTIAL_K = 0.5  # PARTIAL_THRUST health
STUCK_K = 1.0  # THRUSTER_STUCK_OPEN: valve fully open (illustrative)


@dataclass
class SatState:
    """Resource state of one satellite. m_kg is the CURRENT mass (dry + propellant)."""

    m_kg: float = 4.0
    m_prop_kg: float = 0.2
    isp_s: float = 40.0
    f_max_n: float = 0.04
    k: float = 1.0  # thrust health 0..1 (THRUSTER_OUT 0, PARTIAL_THRUST 0.5)
    stuck_vec: np.ndarray | None = None  # unit vector in ECI while a thruster is stuck open
    stuck_k: float = 0.0
    payload_ok: bool = True
    radio_ok: bool = True

    @property
    def depleted(self) -> bool:
        return self.m_prop_kg <= 0.0

    @property
    def fuel_mps_left(self) -> float:
        """Remaining tank delta-v, m/s: Isp g0 ln(m / (m - m_prop)) (0 when empty)."""
        if self.depleted:
            return 0.0
        return self.isp_s * G0 * math.log(self.m_kg / (self.m_kg - self.m_prop_kg))

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["stuck_vec"] = None if self.stuck_vec is None else self.stuck_vec.tolist()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> SatState:
        v = d["stuck_vec"]
        return cls(**{**d, "stuck_vec": None if v is None else np.array(v)})

    @classmethod
    def from_scenario(cls, scenario: Scenario) -> SatState:
        sc = scenario.spacecraft
        return cls(scenario.truth.mass_kg, sc.m_prop_kg, sc.isp_s, sc.f_max_n)


def thrust_limited(sat: SatState, a_cmd: np.ndarray, dt: float) -> tuple[np.ndarray, float]:
    """Applied acceleration and propellant consumed over one step of length dt; updates sat.

    Commanded thrust: a_cmd (LVLH, m/s^2) is clipped to |a| <= k F_max / m (direction kept; a
    command under the cap passes through bit-unchanged). A stuck-open thruster ignores a_cmd
    and fires stuck_k F_max along stuck_vec, so the result is then in ECI, not LVLH. Empty
    tank: zero. A burn that would overdraw the tank is truncated: the acceleration is scaled
    so the step delivers exactly the impulse the remaining propellant buys, and m_prop is
    set to exactly 0 (never negative). Acceleration uses the mass at the start of the step.
    """
    if sat.depleted:
        sat.k = 0.0
        return np.zeros(3), 0.0
    if sat.stuck_vec is not None:
        a = sat.stuck_vec * (sat.stuck_k * sat.f_max_n / sat.m_kg)
    else:
        a = np.asarray(a_cmd, dtype=float)
        cap = sat.k * sat.f_max_n / sat.m_kg
        norm = float(np.linalg.norm(a))
        if norm > cap:
            a = a * (cap / norm)
    dm = float(np.linalg.norm(a)) * sat.m_kg * dt / (sat.isp_s * G0)
    if dm > sat.m_prop_kg:  # truncated on the step that empties the tank
        a = a * (sat.m_prop_kg / dm)
        dm = sat.m_prop_kg
    sat.m_kg -= dm
    sat.m_prop_kg = 0.0 if dm == sat.m_prop_kg else sat.m_prop_kg - dm
    if sat.depleted:
        sat.k = 0.0  # an empty tank cannot thrust (the stuck-open valve is dry too)
    return a, dm


def apply_failure(sat: SatState, mode: FailureMode, stuck_vec: np.ndarray | None = None) -> None:
    """Failure mode as resource damage (mutates sat). DEAD and EPS_DEGRADE (a fade that ends in
    a death, Phase-1 behaviour): all off. THRUSTER_OUT: k = 0. PARTIAL_THRUST: k = 0.5.
    THRUSTER_STUCK_OPEN: fires stuck_k F_max along the fixed ECI direction stuck_vec (stored as
    a unit vector; required). PAYLOAD_FAIL: payload_ok = False. RADIO_FAIL: radio_ok = False."""
    if mode in (FailureMode.DEAD, FailureMode.EPS_DEGRADE):
        sat.k, sat.stuck_vec, sat.stuck_k = 0.0, None, 0.0
        sat.payload_ok = sat.radio_ok = False
    elif mode == FailureMode.THRUSTER_OUT:
        sat.k = 0.0
    elif mode == FailureMode.PARTIAL_THRUST:
        sat.k = min(sat.k, PARTIAL_K)
    elif mode == FailureMode.THRUSTER_STUCK_OPEN:
        if stuck_vec is None or not np.linalg.norm(stuck_vec) > 0:
            raise ValueError("THRUSTER_STUCK_OPEN needs a non-zero stuck_vec (ECI direction)")
        sat.stuck_vec = np.asarray(stuck_vec, dtype=float) / np.linalg.norm(stuck_vec)
        sat.stuck_k = STUCK_K
    elif mode == FailureMode.PAYLOAD_FAIL:
        sat.payload_ok = False
    elif mode == FailureMode.RADIO_FAIL:
        sat.radio_ok = False
