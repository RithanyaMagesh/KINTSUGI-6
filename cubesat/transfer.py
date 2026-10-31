"""Fuel-optimal impulsive CW transfers by linear programming, plus a receding-horizon helper.

Planning model: Hill-Clohessy-Wiltshire (cubesat.hcw.stm), state [x, y, z, vx, vy, vz] in the
chief LVLH frame, SI units (AGENTS.md invariants 3, 4). Pure and deterministic: no wall clock,
no RNG. `cancel_event` is a cooperative hook checked between solves (raises TransferCancelled;
cubesat.sim.RunCancelled is not importable from here by design).

Formulation (docs/PHYSICS_V2.md "Phase 5c"): N impulse nodes t_k = linspace(0, T, N); variables
dv+_k, dv-_k >= 0, dv_k = dv+_k - dv-_k; minimise sum(dv+ + dv-) (L1 cost) subject to
    sum_k Phi(T - t_k)[:, 3:] @ dv_k = x_target - Phi(T) @ x0           (all 6 rows)
    |dv_k,axis| <= k_health * a_max * (T/N) / sqrt(3)                    (|dv_k| <= a_max*T/N)
and optional keep-out half-spaces n_j . (rho(t_j) - rho_o(t_j)) >= d_safe (sequential
convexification, n_j from the previous iterate, <= 3 iterations; a half-space solution is
truly >= d_safe from the obstacle because n_j is a unit vector). Infeasible -> None.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass

import numpy as np
from scipy.optimize import linprog

from cubesat.hcw import stm

MAX_ITER = 3  # keep-out sequential-convexification iterations (first = unconstrained)
MPC_M = 60  # default receding-horizon period in ticks
KEEPOUT_TOL_M = 1e-6


class TransferCancelled(RuntimeError):
    """cancel_event was set between solves; no partial result is returned."""


@dataclass
class Transfer:
    dv: np.ndarray  # (N, 3) impulses [m/s], applied at `times`
    times: np.ndarray  # (N,) node times [s] from the plan start
    total_dv_mps: float  # LP objective: sum |dv| over components (L1)
    T_s: float
    feasible_iterations: int  # feasible LP solves taken (1 = no keep-out action)

    @property
    def l2_dv_mps(self) -> float:
        """Sum of impulse magnitudes ||dv_k||_2 (the physical delta-v spent)."""
        return float(np.linalg.norm(self.dv, axis=1).sum())


def _check(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise TransferCancelled("transfer solve cancelled")


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


def _solve(c, A_eq, b_eq, A_ub, b_ub, cap):
    res = linprog(
        c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=(0.0, cap), method="highs"
    )
    return res.x if res.status == 0 and res.x is not None else None


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
) -> Transfer | None:
    """Fuel-optimal impulsive transfer from x0 to x_target(T). None when infeasible
    (k=0, a_max/T too small, keep-out unsatisfiable): never raises on infeasibility.

    keepout: list of (times (M,), obstacle positions (M, 3), d_safe) with times in seconds
    from the plan start (samples outside (0, T] are ignored)."""
    _check(cancel_event)
    N = int(N)
    if not (T > 0.0 and a_max > 0.0 and k > 0.0 and N >= 1 and n > 0.0):
        return None
    x0 = np.asarray(x0, dtype=float)
    x_target = np.asarray(x_target, dtype=float)
    times = np.linspace(0.0, T, N)
    cap = k * a_max * (T / N) / math.sqrt(3.0)
    # Velocity columns of the STM (all 6 rows). Row scaling (position rows * n) was measured
    # to change the landing residual by nothing (60 random cases, ~1e-9 m either way): HiGHS
    # scales internally, so none is applied.
    G = np.hstack([stm(T - t, n)[:, 3:] for t in times])  # (6, 3N): state at T per unit dv
    A_eq = np.hstack([G, -G])
    b_eq = x_target - stm(T, n) @ x0
    c = np.ones(6 * N)

    samples = []  # (t_j, rows (3, 3N) giving rho(t_j) - free, free rho(t_j), rho_o, d_safe)
    for ts, pos, d_safe in keepout or []:
        pos = np.asarray(pos, float).reshape(-1, 3)
        for t_j, p in zip(np.asarray(ts, float), pos, strict=True):
            if not (0.0 < t_j <= T):
                continue
            rows = np.zeros((3, 3 * N))
            for i, t_k in enumerate(times):
                if t_k <= t_j:
                    rows[:, 3 * i : 3 * i + 3] = stm(t_j - t_k, n)[:3, 3:]
            samples.append((rows, stm(t_j, n)[:3] @ x0, p, float(d_safe)))

    x_prev, solved = None, 0
    for _ in range(MAX_ITER):
        _check(cancel_event)
        A_ub = b_ub = None
        if x_prev is not None:  # normals from the previous iterate
            ub_rows, ub_rhs = [], []
            for rows, free, p, d_safe in samples:
                rho = free + rows @ (x_prev[: 3 * N] - x_prev[3 * N :])
                nrm = rho - p
                norm = float(np.linalg.norm(nrm))
                nrm = nrm / norm if norm > 1e-9 else np.array([1.0, 0.0, 0.0])
                row = nrm @ rows  # n.(rho - p) >= d  <=>  -n.rows dv <= n.(free - p) - d
                ub_rows.append(-np.concatenate([row, -row]))
                ub_rhs.append(nrm @ (free - p) - d_safe)
            A_ub, b_ub = np.array(ub_rows), np.array(ub_rhs)
        x = _solve(c, A_eq, b_eq, A_ub, b_ub, cap)
        if x is None:
            return None
        solved += 1
        dv = (x[: 3 * N] - x[3 * N :]).reshape(N, 3)
        clear = all(
            np.linalg.norm(free + rows @ dv.ravel() - p) >= d_safe - KEEPOUT_TOL_M
            for rows, free, p, d_safe in samples
        )
        if clear:
            return Transfer(dv, times, float(x.sum()), float(T), solved)
        x_prev = x
    return None


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
) -> Transfer | None:
    """Sweep T over `orbits` periods; return the feasible plan with the least total delta-v
    (ties: smaller T), or None. x_target_fn(T) is the target state T seconds after the plan
    start. cancel_event is checked before each solve; a set event raises TransferCancelled and
    discards everything computed so far (checked inside every lp_transfer call)."""
    best = None
    for o in sorted(orbits):  # lp_transfer checks cancel_event first, before any solve
        T = float(o) * 2.0 * math.pi / n
        tr = lp_transfer(x0, x_target_fn(T), T, n, a_max, k, N, keepout, cancel_event)
        if tr is not None and (best is None or tr.total_dv_mps < best.total_dv_mps - 1e-9):
            best = tr
    return best


def mpc_due(tick: int, M: int = MPC_M) -> bool:
    """True on the ticks where the receding-horizon planner re-solves (every M ticks)."""
    return tick % M == 0


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
) -> Transfer | None:
    """Re-solve from the measured state x_meas at t_elapsed s into a T_total s plan, on the
    remaining horizon T_total - t_elapsed, to the same target x_target_fn(T_total). Returned
    node times are relative to NOW. Keep-out sample times (plan-start based) are shifted.
    The terminal hold is the caller's (PD); None when no horizon is left or infeasible."""
    rem = float(T_total) - float(t_elapsed)
    if rem <= 0.0:
        return None
    shifted = [(np.asarray(ts, float) - t_elapsed, pos, d) for ts, pos, d in keepout or []]
    return lp_transfer(
        x_meas, x_target_fn(T_total), rem, n, a_max, k, N, shifted or None, cancel_event
    )
