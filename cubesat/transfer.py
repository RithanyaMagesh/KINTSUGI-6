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
at most MAX_ROUNDS refinement rounds. Guarantee: verified clearance >= d_safe at every 1 s grid
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

MAX_ROUNDS = 3  # keep-out refinement rounds after the unconstrained solve
GRID_DT_S = 1.0  # dense verification step [s]
KEEPOUT_TOL_M = 1e-6
LANDING_RTOL = 1e-6  # accepted landing residual: LANDING_RTOL * max(1, |x_target|)
CHUNK = 64  # rows/times per assembly chunk (cancel check between chunks)
CAP_SHAPES = ("box", "octahedron")


class TransferCancelled(RuntimeError):
    """cancel_event was set between solves; no partial result is returned."""


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


def _check(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise TransferCancelled("transfer solve cancelled")


def _finite(v, name: str) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number, got {v!r}") from None
    if not math.isfinite(f):
        raise ValueError(f"{name} must be finite, got {v!r}")
    return f


def _validate(*, n, a_max, k, N, cap_shape="box", x0=None, x_target=None, T=None, keepout=None):
    """Malformed input -> ValueError (programming error). a_max = 0 or k = 0 are legal (no
    thrust / no fuel) and later give None. Returns (cleaned keepout list, x0, x_target)."""
    if _finite(n, "n") <= 0.0:
        raise ValueError(f"n must be > 0, got {n!r}")
    if _finite(a_max, "a_max") < 0.0:
        raise ValueError(f"a_max must be >= 0, got {a_max!r}")
    if not 0.0 <= _finite(k, "k") <= 1.0:
        raise ValueError(f"k (health) must be in [0, 1], got {k!r}")
    if isinstance(N, bool) or not isinstance(N, int | np.integer) or N < 1:
        raise ValueError(f"N must be an integer >= 1, got {N!r}")
    if cap_shape not in CAP_SHAPES:
        raise ValueError(f"cap_shape must be one of {CAP_SHAPES}, got {cap_shape!r}")
    if T is not None and _finite(T, "T") <= 0.0:
        raise ValueError(f"T must be > 0, got {T!r}")
    out = []
    for name, x in (("x0", x0), ("x_target", x_target)):
        if x is None:
            out.append(None)
            continue
        x = np.asarray(x, dtype=float)
        if x.shape != (6,) or not np.all(np.isfinite(x)):
            raise ValueError(f"{name} must be a finite (6,) state, got shape {x.shape}")
        out.append(x)
    clean = []
    for i, item in enumerate(keepout or []):
        try:
            ts, pos, d = item
            ts = np.asarray(ts, dtype=float).ravel()
            pos = np.asarray(pos, dtype=float)
            pos = pos.reshape(-1, 3) if pos.size == 3 * ts.size else pos
        except (TypeError, ValueError):
            raise ValueError(f"keepout[{i}] must be (times, positions (M, 3), d_safe)") from None
        if pos.shape != (ts.size, 3) or ts.size == 0:
            raise ValueError(f"keepout[{i}]: times ({ts.size},) and positions {pos.shape} differ")
        if not (np.all(np.isfinite(ts)) and np.all(np.isfinite(pos))):
            raise ValueError(f"keepout[{i}] has non-finite values")
        if np.any(np.diff(ts) <= 0.0):
            raise ValueError(f"keepout[{i}] times must be strictly increasing")
        if _finite(d, f"keepout[{i}] d_safe") <= 0.0:
            raise ValueError(f"keepout[{i}] d_safe must be > 0")
        clean.append((ts, pos, float(d)))
    return clean, out[0], out[1]


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


def _rv(tau: np.ndarray, n: float) -> np.ndarray:
    """Position-from-velocity STM block Phi_rv(tau), shape tau.shape + (3, 3) (hcw.stm rows)."""
    nt = n * tau
    c, s = np.cos(nt), np.sin(nt)
    out = np.zeros(tau.shape + (3, 3))
    out[..., 0, 0] = s / n
    out[..., 0, 1] = 2.0 * (1.0 - c) / n
    out[..., 1, 0] = -2.0 * (1.0 - c) / n
    out[..., 1, 1] = (4.0 * s - 3.0 * nt) / n
    out[..., 2, 2] = s / n
    return out


def _free_positions(x0: np.ndarray, n: float, t: np.ndarray) -> np.ndarray:
    """Position rows of Phi(t) @ x0, shape (len(t), 3)."""
    nt = n * t
    c, s = np.cos(nt), np.sin(nt)
    x = (4.0 - 3.0 * c) * x0[0] + s / n * x0[3] + 2.0 * (1.0 - c) / n * x0[4]
    y = (
        6.0 * (s - nt) * x0[0]
        + x0[1]
        - 2.0 * (1.0 - c) / n * x0[3]
        + (4.0 * s - 3.0 * nt) / n * x0[4]
    )
    z = c * x0[2] + s / n * x0[5]
    return np.stack([x, y, z], axis=1)


def _blocks(t: np.ndarray, times: np.ndarray, n: float) -> np.ndarray:
    """(S, N, 3, 3): Phi_rv(t_s - t_k) for t_k <= t_s, else 0."""
    tau = t[:, None] - times[None, :]
    live = tau >= 0.0
    return _rv(np.where(live, tau, 0.0), n) * live[..., None, None]


def _plan_positions(x0, plan: Transfer, n: float, t, cancel_event=None) -> np.ndarray:
    """Position of x0 under the plan at times t (vectorised; equals propagate_plan[:3])."""
    t = np.asarray(t, dtype=float)
    pos = _free_positions(np.asarray(x0, dtype=float), n, t)
    for i in range(0, t.size, CHUNK):
        _check(cancel_event)
        sl = slice(i, i + CHUNK)
        pos[sl] += np.einsum("snij,nj->si", _blocks(t[sl], plan.times, n), plan.dv)
    return pos


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
    the current linearisation after MAX_ROUNDS rounds. Malformed input raises ValueError;
    infeasibility never raises. cancel_event is checked before every solve and between chunks
    of the keep-out assembly (TransferCancelled, no partial result). node_times (len N, strictly
    increasing in [0, T]) and cap_dt_s (cap interval, default T/N) override the uniform grid;
    mpc_step uses them to keep the original schedule."""
    keepout, x0, x_target = _validate(
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
    _check(cancel_event)
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
        dt_cap = _finite(cap_dt_s, "cap_dt_s")
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

    def finish(x):
        """dv from x, clipped to the cap; the clip is kept only if the plan still lands."""
        dv = (x[: 3 * N] - x[3 * N :]).reshape(N, 3)
        for cand in (np.clip(dv, -cap, cap), dv):
            tr = Transfer(cand, times, float(np.abs(cand).sum()), T, 1)
            if np.linalg.norm(propagate_plan(x0, tr, n) - x_target) <= tol:
                return tr
        return None

    x = _solve(c, A_eq, b_eq, A_cap, b_cap, cap)
    tr = finish(x) if x is not None else None
    if tr is None or not keepout:
        return tr
    grid = np.unique(
        np.concatenate(
            [np.arange(0.0, T, GRID_DT_S), [T]] + [t[(t >= 0.0) & (t <= T)] for t, _, _ in keepout]
        )
    )
    obs = []  # per obstacle: interpolated positions on the grid (nan outside its time range)
    for ts, pos, d in keepout:
        p = np.stack([np.interp(grid, ts, pos[:, i]) for i in range(3)], axis=1)
        p[(grid < ts[0]) | (grid > ts[-1])] = np.nan
        obs.append((p, d))
    dsafe = np.array([d for _, d in obs])[:, None]
    free = _free_positions(x0, n, grid)
    active = np.zeros((len(obs), grid.size), dtype=bool)
    solved = 1
    for rnd in range(MAX_ROUNDS + 1):
        pos = _plan_positions(x0, tr, n, grid, cancel_event)
        dist = np.stack([np.linalg.norm(pos - p, axis=1) for p, _ in obs])  # nan outside range
        with np.errstate(invalid="ignore"):
            bad = dist < dsafe - KEEPOUT_TOL_M
        if not bad.any():
            clear = float(np.nanmin(dist)) if np.isfinite(dist).any() else None
            return Transfer(tr.dv, times, tr.total_dv_mps, T, solved, clear)
        active |= bad
        if rnd == MAX_ROUNDS:
            return None  # a violation at t = 0 (start inside) makes the next LP infeasible
        rows, rhs = [], []
        oi, gi = np.nonzero(active)
        for lo in range(0, gi.size, CHUNK):
            if lo:
                _check(cancel_event)
            o, g = oi[lo : lo + CHUNK], gi[lo : lo + CHUNK]
            p = np.stack([obs[j][0][i] for j, i in zip(o, g, strict=True)])
            nrm = pos[g] - p
            norm = np.linalg.norm(nrm, axis=1, keepdims=True)
            nrm = np.where(norm > 1e-9, nrm / np.maximum(norm, 1e-9), [1.0, 0.0, 0.0])
            R = np.transpose(_blocks(grid[g], times, n), (0, 2, 1, 3)).reshape(-1, 3, 3 * N)
            row = np.einsum("ai,aij->aj", nrm, R)  # n.rho = n.free + row @ dv
            rows.append(np.hstack([-row, row]))
            rhs.append(np.einsum("ai,ai->a", nrm, free[g] - p) - dsafe[o, 0])
        A_ub = np.vstack(rows if A_cap is None else [A_cap, *rows])
        b_ub = np.concatenate(rhs if b_cap is None else [b_cap, *rhs])
        x = _solve(c, A_eq, b_eq, A_ub, b_ub, cap)
        tr = finish(x) if x is not None else None
        if tr is None:
            return None
        solved += 1
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
    cap_shape: str = "box",
) -> Transfer | None:
    """Sweep T over `orbits` periods; return the feasible plan with the least total delta-v
    (ties within 1e-9 m/s: smaller T), or None. x_target_fn(T) is the target state T seconds
    after the plan start. A set cancel_event raises TransferCancelled (checked inside every
    lp_transfer call) and discards everything computed so far."""
    keepout, x0, _ = _validate(
        n=n, a_max=a_max, k=k, N=N, cap_shape=cap_shape, x0=x0, keepout=keepout
    )
    for o in orbits:
        if _finite(o, "orbits entry") <= 0.0:
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
    keepout, x_meas, _ = _validate(
        n=n, a_max=a_max, k=k, N=N, cap_shape=cap_shape, x0=x_meas, T=T_total, keepout=keepout
    )
    if _finite(t_elapsed, "t_elapsed") < 0.0:
        raise ValueError(f"t_elapsed must be >= 0, got {t_elapsed!r}")
    _check(cancel_event)
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
