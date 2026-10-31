"""Forward simulation behind the certificate (physics Phase 5d-1). Pure: no RNG, no wall clock.

It is the EngineV2 stepper (cubesat/sim_v2.py `_advance`) replayed on a copy of the swarm:
truth RK4 (`truth.rk4_step`, the scenario's dt), chief J2-only (B = 0, no drag), active sats at
`truth.area_active_m2`, DEAD sats at `truth.area_dead_m2`, the v1 `PDController` on the LVLH
state against a seat reference advanced by the cached Phi(dt), every command through
`spacecraft.thrust_limited` (cap k F_max / m, propellant use, tank truncation), a thrust that is
constant in ECI over a step (rotated with the chief at the step start), re-entry freezing below
100 km. With no plan items it reproduces the engine run (tests/v2/test_certify_engine.py).

Transfer execution (docs/PHYSICS_V2.md "Phase 5d"): node k of a `Transfer` (impulse dv_k at t_k) is
delivered as a constant LVLH acceleration dv_k / (m_k dt) over m_k = ceil(|dv_k| / (k F_max / m dt))
consecutive steps from the step that contains t_k (m = mass at the start of the plan). Between
bursts the mover coasts; once its last node time has passed and its last burn is done it holds
with PD. Assumed NOT to happen: new failures during the horizon.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass

import numpy as np

from cubesat import truth
from cubesat.hcw import mean_motion, stm
from cubesat.pd import PDController
from cubesat.scenario import Scenario
from cubesat.spacecraft import SatState, thrust_limited
from cubesat.transfer import Transfer

REENTRY_ALTITUDE_M = 100e3  # = sim_v2.REENTRY_ALTITUDE_M (same guard, duplicated: the engine
STATUS_DEAD, STATUS_REENTERED = "DEAD", "REENTERED"  # module is fenced and would be circular)
_EPS = 1e-9


class CertificateCancelled(RuntimeError):
    """cancel_event was set between steps of the certificate simulation; no result."""


def clone_sat(s: SatState) -> SatState:
    return SatState.from_dict(s.to_dict())


@dataclass
class SwarmState:
    """What the certificate needs from the engine at time t_s (a copy; never mutated by it).
    chief (6,) ECI [r, v]; sat_eci (N, 6) ECI; status[i] the TRUE status string; sats[i] the
    SatState (mass, propellant, k, flags, stuck vector); roles[i] the roles held NOW; refs
    (N, 6) the seat references now (LVLH, the engine's `refs`)."""

    t_s: float
    chief: np.ndarray
    sat_eci: np.ndarray
    status: list[str]
    sats: list[SatState]
    roles: list[list[str]]
    refs: np.ndarray


def swarm_state_from_engine(engine) -> SwarmState:
    """Copy a live EngineV2's state. Reads only these attributes (none private): `k`, `dt`, `X`
    (row 0 chief, rows 1.. sats), `refs`, `status` (property of `faults.status`),
    `faults.sats`, `roles`."""
    return SwarmState(
        t_s=engine.k * engine.dt,
        chief=np.array(engine.X[0], dtype=float),
        sat_eci=np.array(engine.X[1:], dtype=float),
        status=list(engine.status),
        sats=[clone_sat(s) for s in engine.faults.sats],
        roles=[list(r) for r in engine.roles],
        refs=np.array(engine.refs, dtype=float),
    )


@dataclass
class SimResult:
    min_sep_m: float
    min_sep_pair: tuple[int, int]
    min_sep_t_s: float
    landing_m: dict[int, float]  # mover id -> truth position error vs seat at its plan end
    n_steps: int  # steps simulated (>= the requested horizon)
    final_eci: np.ndarray  # (N + 1, 6), row 0 chief
    final_sats: list[SatState]


def _schedule(transfers: dict[int, Transfer], sats: list[SatState], dt: float):
    """Per mover: (burn (steps, 3) LVLH acceleration per step, step at which PD takes over)."""
    out = {}
    for i, tr in transfers.items():
        s = sats[i]
        cap_dv = s.k * s.f_max_n / s.m_kg * dt  # delta-v one step can deliver
        steps = [int(math.floor(t / dt + _EPS)) for t in tr.times]
        counts = [
            int(math.ceil(float(np.linalg.norm(dv)) / cap_dv - _EPS)) if cap_dv > 0.0 else 0
            for dv in tr.dv
        ]
        ends = [a + c for a, c in zip(steps, counts, strict=True)]
        last = max([int(math.floor(tr.times[-1] / dt + _EPS)), *ends])
        burn = np.zeros((last + 1, 3))
        for a, c, dv in zip(steps, counts, tr.dv, strict=True):
            if c:
                burn[a : a + c] += dv / (c * dt)
        out[i] = (burn, last)
    return out


def simulate(
    scenario: Scenario,
    state: SwarmState,
    seats: np.ndarray,
    transfers: dict[int, Transfer],
    n_steps: int,
    cancel_event: threading.Event | None = None,
) -> SimResult:
    """Run `n_steps` engine steps (more if a transfer needs them) and report the minimum pairwise
    distance over the states at t = 0 .. n_steps dt (sats not re-entered), where it happened,
    and each mover's position error vs its seat the moment PD takes over (its plan end)."""
    dt, tr = scenario.dt_s, scenario.truth
    n = mean_motion(scenario.chief.altitude_km * 1000.0)
    sats = [clone_sat(s) for s in state.sats]
    status = list(state.status)
    count = len(sats)
    X = np.vstack([state.chief, state.sat_eci]).astype(float)
    refs = np.array(seats, dtype=float)
    phi = stm(dt, n)
    pd = PDController(scenario.gains.wn, scenario.gains.zeta, scenario.a_max_mps2)
    b_active, b_dead = tr.cd * tr.area_active_m2 / tr.mass_kg, tr.cd * tr.area_dead_m2 / tr.mass_kg
    sched = _schedule(transfers, sats, dt)
    n_steps = max([n_steps] + [last for _, last in sched.values()])
    hold = np.zeros((count, 6))
    best, pair, t_best, landing = math.inf, (0, 0), 0.0, {}
    for j in range(n_steps + 1):
        if cancel_event is not None and cancel_event.is_set():
            raise CertificateCancelled(f"certificate cancelled before step {j}")
        c = X[0]
        lvlh = truth.eci_to_lvlh(X[1:, :3], X[1:, 3:], c[:3], c[3:])
        alt = np.linalg.norm(X[1:, :3], axis=1) - truth.RE
        for i in range(count):
            fresh = alt[i] < REENTRY_ALTITUDE_M and status[i] != STATUS_REENTERED
            if fresh or (j == 0 and status[i] == STATUS_REENTERED):  # frozen state, as the engine
                hold[i], status[i] = lvlh[i], STATUS_REENTERED
        gone = np.array([s == STATUS_REENTERED for s in status])
        lvlh[gone] = hold[gone]
        keep = [i for i in range(count) if not gone[i]]
        keep = keep if len(keep) >= 2 else list(range(count))
        d2 = ((lvlh[keep, None, :3] - lvlh[None, keep, :3]) ** 2).sum(-1)
        iu = np.triu_indices(len(keep), 1)
        flat = d2[iu]
        m = int(np.argmin(flat))
        if flat[m] < best**2:
            best, t_best = float(math.sqrt(flat[m])), j * dt
            pair = (keep[iu[0][m]], keep[iu[1][m]])
        for i, (_, last) in sched.items():
            if j == last:
                landing[i] = float(np.linalg.norm(lvlh[i, :3] - refs[i, :3]))
        if j == n_steps:
            break
        u = np.zeros((count, 3))
        a_stuck = np.zeros((count, 3))
        for i, s in enumerate(status):
            if s in (STATUS_DEAD, STATUS_REENTERED):
                continue
            sat = sats[i]
            if sat.stuck_vec is not None:
                a_stuck[i], _ = thrust_limited(sat, u[i], dt)
            else:
                if i in sched and j < sched[i][1]:
                    cmd = sched[i][0][j]
                else:
                    cmd = pd.command(lvlh[i, :3], lvlh[i, 3:], refs[i, :3], refs[i, 3:])
                u[i], _ = thrust_limited(sat, cmd, dt)
        a_thrust = np.vstack([np.zeros(3), truth.thrust_eci(u, c[:3], c[3:]) + a_stuck])
        b = np.array([0.0] + [b_dead if s == STATUS_DEAD else b_active for s in status])

        def accel(r, v, b=b, a_thrust=a_thrust):
            a = truth.accel_gravity(r) + truth.accel_drag(r, v, b, tr.density_factor) + a_thrust
            return a + truth.accel_j2(r) if tr.j2_enabled else a

        new = truth.rk4_step(X, dt, accel)
        frozen = np.array([False] + [s == STATUS_REENTERED for s in status])
        X = np.where(frozen[:, None], X, new)
        refs = refs @ phi.T
    return SimResult(best, pair, t_best, landing, n_steps, X, sats)
