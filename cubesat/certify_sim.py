"""Forward simulation behind the certificate (physics Phase 5d). Pure: no RNG, no wall clock.

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
with PD. Assumed NOT to happen: new failures during the horizon. Bounds: node times <= 10 orbits,
at most MAX_STEPS steps (ValueError / a failed check beyond them).
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass

import numpy as np

from cubesat import truth
from cubesat.coverage import coverage_fraction
from cubesat.faults_v2 import STATUS_REENTERED
from cubesat.hcw import mean_motion, propagate, stm
from cubesat.pd import PDController
from cubesat.scenario import Scenario
from cubesat.sim import STATUS_DEAD
from cubesat.sim_v2 import REENTRY_ALTITUDE_M
from cubesat.spacecraft import SatState, thrust_limited
from cubesat.transfer import Transfer

_EPS = 1e-9
MAX_STEPS = 250_000  # documented cap on simulated (and burn) steps
MAX_PLAN_ORBITS = 10.0  # node times beyond this many chief orbits are rejected
SWEEP_SAMPLES = 72  # = allocate._SWEEP_SAMPLES (equality tested)


class CertificateCancelled(RuntimeError):
    """cancel_event was set between steps of the certificate simulation; no result."""


def clone_sat(s: SatState) -> SatState:
    return SatState.from_dict(s.to_dict())


@dataclass
class SwarmState:
    """What the certificate needs from the engine at time t_s (a copy; never mutated by it).
    chief (6,) ECI [r, v]; sat_eci (N, 6) ECI; status[i] the TRUE status string; sats[i] the
    SatState (mass, propellant, k, flags, stuck vector); roles[i] the roles held NOW; refs
    (N, 6) the seat references now (LVLH, the engine's `refs`); hold (N, 6) the engine's frozen
    LVLH state of re-entered sats (`hold`)."""

    t_s: float
    chief: np.ndarray
    sat_eci: np.ndarray
    status: list[str]
    sats: list[SatState]
    roles: list[list[str]]
    refs: np.ndarray
    hold: np.ndarray


def swarm_state_from_engine(engine) -> SwarmState:
    """Copy a live EngineV2's state. Reads only these attributes (none private): `k`, `dt`, `X`
    (row 0 chief, rows 1.. sats), `refs`, `hold`, `status` (property of `faults.status`),
    `faults.sats`, `roles`."""
    return SwarmState(
        t_s=engine.k * engine.dt,
        chief=np.array(engine.X[0], dtype=float),
        sat_eci=np.array(engine.X[1:], dtype=float),
        status=list(engine.status),
        sats=[clone_sat(s) for s in engine.faults.sats],
        roles=[list(r) for r in engine.roles],
        refs=np.array(engine.refs, dtype=float),
        hold=np.array(engine.hold, dtype=float),
    )


def coverage_estimate(seats, imagers, *, r_f: float, grid: np.ndarray, n: float) -> float:
    """Copy of allocate._coverage_estimate (t_replan = 0): mean coverage of the `imagers` seats
    (6-D states, hcw.propagate'd) over one orbit, SWEEP_SAMPLES samples. Equality is tested."""
    period, total = 2.0 * math.pi / n, 0.0
    for m in range(SWEEP_SAMPLES):
        t = m * period / SWEEP_SAMPLES
        centers = np.array([propagate(seats[j], t, n)[1:3] for j in imagers])
        total += coverage_fraction(centers, grid, r_f)
    return total / SWEEP_SAMPLES


def _finite(v, name: str) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number, got {v!r}") from None
    if not math.isfinite(f):
        raise ValueError(f"{name} must be finite, got {v!r}")
    return f


def validate_state(state: SwarmState, n_sats: int) -> None:
    """ValueError unless `state` is finite, consistently shaped and physical."""
    _finite(state.t_s, "state.t_s")
    shapes = {"chief": (6,), "sat_eci": (n_sats, 6), "refs": (n_sats, 6), "hold": (n_sats, 6)}
    for name, shape in shapes.items():
        a = np.asarray(getattr(state, name), dtype=float)
        if a.shape != shape or not np.all(np.isfinite(a)):
            raise ValueError(f"state.{name} must be a finite array of shape {shape}")
    if not (len(state.status) == len(state.sats) == len(state.roles) == n_sats):
        raise ValueError(f"state lists must hold {n_sats} entries (the scenario's sats)")
    for s in state.sats:
        vals = (s.m_kg, s.m_prop_kg, s.isp_s, s.f_max_n, s.k)
        ok = all(math.isfinite(v) for v in vals) and s.m_kg > 0.0 and s.isp_s > 0.0
        if not (ok and s.f_max_n > 0.0 and 0.0 <= s.k <= 1.0 and 0.0 <= s.m_prop_kg < s.m_kg):
            raise ValueError(f"non-finite or non-physical SatState {s}")


def transfer_arrays(tr: Transfer, name: str, period_s: float) -> tuple[np.ndarray, np.ndarray]:
    """(dv (M, 3), times (M,)) as float arrays; ValueError when malformed or beyond the bound."""
    try:
        dv, ts = np.asarray(tr.dv, dtype=float), np.asarray(tr.times, dtype=float)
    except (TypeError, ValueError):
        raise ValueError(f"{name}: transfer dv/times must be numeric arrays") from None
    if dv.ndim != 2 or dv.shape[1] != 3 or ts.shape != (dv.shape[0],) or dv.shape[0] < 1:
        raise ValueError(f"{name}: transfer needs dv (N, 3) and times (N,)")
    if not (np.all(np.isfinite(dv)) and np.all(np.isfinite(ts))) or np.any(ts < 0.0):
        raise ValueError(f"{name}: transfer has non-finite dv/times or t < 0")
    if ts.max() > MAX_PLAN_ORBITS * period_s:
        raise ValueError(f"{name}: transfer node times beyond {MAX_PLAN_ORBITS:g} orbits")
    return dv, ts


def burn_span(tr: Transfer, sat: SatState, dt: float):
    """(first step, step count) per node and the last step (no allocation: the counts can be
    huge for a weak thruster). Node k burns steps start .. start + count - 1."""
    dv, ts = np.asarray(tr.dv, dtype=float), np.asarray(tr.times, dtype=float)
    cap_dv = sat.k * sat.f_max_n / sat.m_kg * dt  # delta-v one step can deliver
    starts = np.floor(ts / dt + _EPS).astype(np.int64)
    mag = np.linalg.norm(dv, axis=1)
    if cap_dv > 0.0:  # clamp before the int cast (k = 1e-300 would overflow int64)
        counts = np.ceil(np.minimum(mag / cap_dv - _EPS, MAX_STEPS + 1.0)).astype(np.int64)
    else:
        counts = 0 * starts
    return starts, counts, int(max(starts.max(), (starts + counts).max()))


def burn_schedule(transfers: dict[int, Transfer], sats: list[SatState], dt: float) -> dict:
    """Per mover: (burn (steps, 3) LVLH acceleration per step, step at which PD takes over)."""
    out = {}
    for i, tr in transfers.items():
        starts, counts, last = burn_span(tr, sats[i], dt)
        if last > MAX_STEPS:
            raise ValueError(f"sat {i}: the burns need {last} steps (cap {MAX_STEPS})")
        burn = np.zeros((last + 1, 3))
        for a, c, dv in zip(starts, counts, np.asarray(tr.dv, dtype=float), strict=True):
            if c:
                burn[a : a + c] += dv / (c * dt)
        out[i] = (burn, last)
    return out


@dataclass
class SimResult:
    min_sep_m: float
    min_sep_pair: tuple[int, int]
    min_sep_t_s: float
    landing_m: dict[int, float]  # mover id -> truth position error vs seat at its plan end
    final_err_m: np.ndarray  # (N,) truth position error vs seat at the last step, every sat
    max_err_m: np.ndarray  # (N,) maximum of that error over the whole horizon
    tail_err_m: np.ndarray  # (N,) maximum over the final orbit of the horizon
    n_steps: int  # steps simulated (>= the requested horizon)
    final_eci: np.ndarray  # (N + 1, 6), row 0 chief
    final_sats: list[SatState]
    final_status: list[str]


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
    each mover's position error vs its seat the moment PD takes over (its plan end), and every
    sat's error vs its seat at the end."""
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
    sched = burn_schedule(transfers, sats, dt)
    n_steps = max([n_steps] + [last for _, last in sched.values()])
    if n_steps > MAX_STEPS:
        raise ValueError(f"the horizon needs {n_steps} steps (cap {MAX_STEPS})")
    hold = np.array(state.hold, dtype=float)
    best, pair, t_best, landing = math.inf, (0, 0), 0.0, {}
    max_err, tail_err = np.zeros(count), np.zeros(count)
    tail_from = n_steps - round(2.0 * math.pi / n / dt)  # steps of the final orbit
    for j in range(n_steps + 1):
        if cancel_event is not None and cancel_event.is_set():
            raise CertificateCancelled(f"certificate cancelled before step {j}")
        c = X[0]
        lvlh = truth.eci_to_lvlh(X[1:, :3], X[1:, 3:], c[:3], c[3:])
        alt = np.linalg.norm(X[1:, :3], axis=1) - truth.RE
        for i in range(count):
            if alt[i] < REENTRY_ALTITUDE_M and status[i] != STATUS_REENTERED:
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
        err = np.linalg.norm(lvlh[:, :3] - refs[:, :3], axis=1)
        max_err = np.maximum(max_err, err)
        if j >= tail_from:
            tail_err = np.maximum(tail_err, err)
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
    return SimResult(
        best, pair, t_best, landing, err, max_err, tail_err, n_steps, X, sats, status
    )
