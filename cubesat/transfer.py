"""L1-optimal impulsive CW transfers by linear programming, plus a receding-horizon helper.

"L1-optimal" = minimum of the per-axis impulse sum sum_k |dv_k|_1, a conservative upper bound on
the vector-magnitude fuel sum_k |dv_k|_2 (see Transfer.l2_dv_mps and the l2_optimum_check in
cubesat.transfer_report). Planning model: Hill-Clohessy-Wiltshire (cubesat.hcw.stm), state
[x, y, z, vx, vy, vz] in the chief LVLH frame, SI units (AGENTS.md invariants 3, 4). Pure and
deterministic: no wall clock, no RNG. `cancel_event` is a cooperative hook (TransferCancelled;
cubesat.sim.RunCancelled is not importable from here by design).

Formulation (docs/PHYSICS_V2.md "Phase 5c"): N impulse nodes t_k = linspace(0, T, N) (spacing
T/(N-1); the cap uses T/N, so total capacity is a_max*T; the node at T has no following
interval); variables dv+_k, dv-_k >= 0, dv_k = dv+_k - dv-_k; minimise sum(dv+ + dv-) subject to
    sum_k Phi(T - t_k)[:, 3:] @ dv_k = x_target - Phi(T) @ x0           (all 6 rows)
and a per-node cap, cap_shape "box" (default): |dv_k,axis| <= k*a_max*(T/N)/sqrt(3), or
"octahedron": |dv_kx|+|dv_ky|+|dv_kz| <= k*a_max*(T/N) (full cap along one axis, still
|dv_k|_2 <= cap).

Keep-out. keepout = [(times, obstacle positions (M, 3), d_safe), ...], times in seconds from
the plan start, obstacle linearly interpolated between samples. After every solve the plan is
VERIFIED on a dense 1 s grid of [0, T] (plus every sample time); each (obstacle, grid time)
pair closer than d_safe becomes a half-space row n.(rho - rho_o) >= d_safe with n the unit
vector obstacle -> plan at the latest iterate (rows re-linearised every round), then re-solved;
at most MAX_ROUNDS refinement rounds. HEAD-ON: when a violated time has a relative vector
shorter than max(1 m, 1e-3 d_safe) the normal is undefined (an obstacle crossing exactly through
the plan), so a fixed deterministic candidate set (+-x, +-y, +-z, +-unit(cross(v_rel, z)): at most
8) is tried, each candidate applied to ALL rows of that obstacle (one consistent side) through
the same verify-and-refine loop, and the cheapest verified plan wins (ties: first attempt, then
lowest candidate index); None only if all fail. Worst case 1 + 3 + 8*3 = 28 LP solves; only
degenerate geometry pays for more than 4. Guarantee: verified clearance >= d_safe at every 1 s grid
point; between grid points the clearance can still shrink by at most v_rel * 0.5 s (obstacle
moves linearly, so v_rel is bounded by the plan speed plus the obstacle speed). A start inside
the keep-out at t = 0 is infeasible. If no plan satisfies it under the current linearisation
after the rounds, None (this does not prove the problem infeasible).
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass

import numpy as np
from scipy.optimize import linprog

from cubesat.hcw import stm
from cubesat.transfer_validate import (
    KeepoutGrid,
    TransferCancelled,
    check_cancel,
    finite,
    plan_positions,
    validate,
)

__all__ = ["Transfer", "TransferCancelled", "best_transfer", "lp_transfer", "mpc_step"]

MAX_ROUNDS = 3  # keep-out refinement rounds after the unconstrained solve
LANDING_RTOL = 1e-6  # accepted landing residual: LANDING_RTOL * max(1, |x_target|)


@dataclass
class Transfer:
    dv: np.ndarray  # (N, 3) impulses [m/s], applied at `times`
    times: np.ndarray  # (N,) node times [s] from the plan start
    total_dv_mps: float  # LP objective: sum |dv| over components (L1)
    T_s: float
    feasible_iterations: int  # feasible LP solves taken (1 = no keep-out action)
    min_clearance_m: float | None = None  # min obstacle distance, 1 s grid; None = no keep-out

    @property
    def l2_dv_mps(self) -> float:
        """Sum of impulse magnitudes ||dv_k||_2 (the physical delta-v spent)."""
        return float(np.linalg.norm(self.dv, axis=1).sum())


def propagate_plan(x0, plan: Transfer, n: float, t_end: float | None = None) -> np.ndarray:
    """Apply the plan's impulses to x0 under CW up to t_end (default T): STM between nodes,
    each dv added at its node time (nodes at t <= t_end are applied)."""
    t_end = plan.T_s if t_end is None else float(t_end)
    x, t = np.asarray(x0, dtype=float).copy(), 0.0
    for tk, dv in zip(plan.times, plan.dv, strict=True):
        if tk > t_end:
            break
        x = stm(float(tk) - t, n) @ x
        x[3:] += dv
        t = float(tk)
    return stm(t_end - t, n) @ x


def _plan_positions(x0, plan: Transfer, n: float, t, cancel_event=None) -> np.ndarray:
    """Position of x0 under the plan at times t (vectorised; equals propagate_plan[:3])."""
    return plan_positions(x0, plan.times, plan.dv, n, t, cancel_event)


def _solve(c, A_eq, b_eq, A_ub, b_ub, cap):
    """linprog (HiGHS). Any non-optimal status, missing x or numerical exception -> None."""
    try:
        res = linprog(
            c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=(0.0, cap), method="highs"
        )
    except (ValueError, ArithmeticError, RuntimeError, np.linalg.LinAlgError):
        return None
    ok = res.status == 0 and res.x is not None and np.all(np.isfinite(res.x))
    return np.asarray(res.x, dtype=float) if ok else None


def lp_transfer(
    x0,
    x_target,
    T: float,
    n: float,
    a_max: float,
    k: float,
    N: int,
    keepout: list[tuple[np.ndarray, np.ndarray, float]] | None = None,
    cancel_event: threading.Event | None = None,
    cap_shape: str = "box",
    node_times: np.ndarray | None = None,
    cap_dt_s: float | None = None,
) -> Transfer | None:
    """L1-optimal impulsive transfer from x0 to x_target(T) (CW). None when there is no plan:
    k = 0 or a_max = 0 (no fuel / thrust, even if no burn is needed), cap too small for the
    transfer, solver failure, landing residual above tolerance, or no keep-out-clear plan under
    the current linearisation after the refinement rounds (and, for head-on geometry, after
    every fixed candidate side). Malformed input raises ValueError; infeasibility never raises.
    cancel_event is checked before every solve and between chunks of the keep-out verification
    and assembly (TransferCancelled, no partial result). node_times (len N, strictly
    increasing in [0, T]) and cap_dt_s (cap interval, default T/N) override the uniform grid;
    mpc_step uses them to keep the original schedule."""
    keepout, x0, x_target = validate(
        n=n,
        a_max=a_max,
        k=k,
        N=N,
        cap_shape=cap_shape,
        x0=x0,
        x_target=x_target,
        T=T,
        keepout=keepout,
    )
    check_cancel(cancel_event)
    if a_max == 0.0 or k == 0.0:
        return None
    N, T = int(N), float(T)
    times = np.linspace(0.0, T, N)
    if node_times is not None:
        times = np.asarray(node_times, dtype=float)
        if times.shape != (N,) or not np.all(np.isfinite(times)) or np.any(np.diff(times) <= 0):
            raise ValueError("node_times must be N finite strictly increasing values")
        if times[0] < 0.0 or times[-1] > T:
            raise ValueError("node_times must lie in [0, T]")
    dt_cap = T / N
    if cap_dt_s is not None:
        dt_cap = finite(cap_dt_s, "cap_dt_s")
        if dt_cap <= 0.0:
            raise ValueError("cap_dt_s must be > 0")
    box = cap_shape == "box"
    cap = k * a_max * dt_cap / (math.sqrt(3.0) if box else 1.0)  # variable bound
    G = np.hstack([stm(T - t, n)[:, 3:] for t in times])  # (6, 3N): state at T per unit dv
    A_eq, b_eq = np.hstack([G, -G]), x_target - stm(T, n) @ x0
    c = np.ones(6 * N)
    A_cap = b_cap = None
    if not box:  # per node: sum over axes of (dv+ + dv-) <= cap
        A_cap = np.zeros((N, 6 * N))
        for i in range(N):
            A_cap[i, 3 * i : 3 * i + 3] = A_cap[i, 3 * N + 3 * i : 3 * N + 3 * i + 3] = 1.0
        b_cap = np.full(N, cap)
    tol = LANDING_RTOL * max(1.0, float(np.linalg.norm(x_target)))

    def solve(A_rows=None, b_rows=None):
        """One LP -> Transfer (clipped to the cap, kept only if it still lands) or None."""
        A_ub = (
            A_cap if A_rows is None else np.vstack([A_rows] if A_cap is None else [A_cap, A_rows])
        )
        b_ub = (
            b_cap
            if b_rows is None
            else np.concatenate([b_rows] if b_cap is None else [b_cap, b_rows])
        )
        x = _solve(c, A_eq, b_eq, A_ub, b_ub, cap)
        if x is None:
            return None
        dv = (x[: 3 * N] - x[3 * N :]).reshape(N, 3)
        for cand in (np.clip(dv, -cap, cap), dv):
            tr = Transfer(cand, times, float(np.abs(cand).sum()), T, 1)
            if np.linalg.norm(propagate_plan(x0, tr, n) - x_target) <= tol:
                return tr
        return None

    tr0 = solve()
    if tr0 is None or not keepout:
        return tr0
    ko = KeepoutGrid(keepout, x0, n, T, times)

    def refine(fixed, cands):
        """Verify-and-refine from the unconstrained plan; fixed = {obstacle: unit normal}.
        Degenerate obstacles seen are recorded in `cands`. Returns a verified Transfer or None."""
        tr, solved, active = tr0, 1, np.zeros(ko.obs.shape[:2], dtype=bool)
        for rnd in range(MAX_ROUNDS + 1):
            pos = _plan_positions(x0, tr, n, ko.grid, cancel_event)
            dist, bad = ko.verify(pos)
            for o, cs in ko.degenerate(pos, dist, bad).items():
                cands.setdefault(o, cs)
            if not bad.any():
                clear = float(np.nanmin(dist)) if np.isfinite(dist).any() else None
                return Transfer(tr.dv, times, tr.total_dv_mps, T, solved, clear)
            active |= bad
            if rnd == MAX_ROUNDS:
                return None  # (a violation at t = 0 makes the next LP infeasible)
            tr = solve(*ko.rows(active, pos, fixed, cancel_event))
            if tr is None:
                return None
            solved += 1
        return None

    cands: dict[int, list[np.ndarray]] = {}
    best = refine({}, cands)
    if not cands:  # no degenerate (head-on) obstacle: the first attempt is the answer
        return best
    for i in range(max(len(v) for v in cands.values())):
        plan = refine({o: v[i] for o, v in cands.items() if i < len(v)}, {})
        if plan is not None and (best is None or plan.total_dv_mps < best.total_dv_mps):
            best = plan
    return best


def best_transfer(
    x0,
    x_target_fn,
    n: float,
    a_max: float,
    k: float,
    N: int = 48,
    orbits=(0.5, 1, 2),
    keepout=None,
    cancel_event: threading.Event | None = None,
    cap_shape: str = "box",
) -> Transfer | None:
    """Sweep T over `orbits` periods; return the feasible plan with the least total delta-v
    (ties within 1e-9 m/s: smaller T), or None. x_target_fn(T) is the target state T seconds
    after the plan start. A set cancel_event raises TransferCancelled (checked inside every
    lp_transfer call) and discards everything computed so far."""
    keepout, x0, _ = validate(
        n=n, a_max=a_max, k=k, N=N, cap_shape=cap_shape, x0=x0, keepout=keepout
    )
    for o in orbits:
        if finite(o, "orbits entry") <= 0.0:
            raise ValueError(f"orbits entries must be > 0, got {o!r}")
    best = None
    for o in sorted(orbits):
        T = float(o) * 2.0 * math.pi / n
        tr = lp_transfer(x0, x_target_fn(T), T, n, a_max, k, N, keepout, cancel_event, cap_shape)
        if tr is not None and (best is None or tr.total_dv_mps < best.total_dv_mps - 1e-9):
            best = tr
    return best


def mpc_step(
    x_meas,
    x_target_fn,
    t_elapsed: float,
    T_total: float,
    n: float,
    a_max: float,
    k: float,
    N: int = 48,
    keepout=None,
    cancel_event: threading.Event | None = None,
    cap_shape: str = "box",
) -> Transfer | None:
    """Re-solve from the measured state x_meas at t_elapsed s into a T_total s plan, on the
    remaining horizon rem = T_total - t_elapsed, to the same final target x_target_fn(T_total).
    The nodes are the original plan's remaining schedule (the linspace(0, T_total, N) entries
    after t_elapsed; none is added at 'now', so the first correction comes at the next node)
    and the per-interval cap keeps the ORIGINAL interval T_total/N, so the cap does not shrink
    with the horizon and the unexecuted nominal plan stays feasible (cost never above the
    remaining nominal cost). Node times are relative to NOW; keep-out sample times (plan-start
    based) are shifted by t_elapsed. The terminal hold is the caller's (PD). None when no
    horizon is left or no plan; negative t_elapsed is a ValueError; a set cancel_event raises
    even when the horizon is exhausted."""
    keepout, x_meas, _ = validate(
        n=n, a_max=a_max, k=k, N=N, cap_shape=cap_shape, x0=x_meas, T=T_total, keepout=keepout
    )
    if finite(t_elapsed, "t_elapsed") < 0.0:
        raise ValueError(f"t_elapsed must be >= 0, got {t_elapsed!r}")
    check_cancel(cancel_event)
    rem = float(T_total) - float(t_elapsed)
    if rem <= 0.0:
        return None
    nodes = np.linspace(0.0, float(T_total), int(N))  # the original plan's schedule
    nodes = nodes[nodes > t_elapsed] - t_elapsed  # the nodes still to come
    shifted = [(ts - t_elapsed, pos, d) for ts, pos, d in keepout]
    return lp_transfer(
        x_meas,
        x_target_fn(T_total),
        rem,
        n,
        a_max,
        k,
        nodes.size,
        shifted or None,
        cancel_event,
        cap_shape,
        nodes,
        float(T_total) / int(N),
    )
