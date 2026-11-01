"""Input validation and the dense CW / keep-out model behind `cubesat.transfer` (no LP here).

Vectorised closed-form CW position model (equals `hcw.stm` propagation; tested), the 1 s keep-out
verification grid, and the half-space rows. SI, LVLH."""

from __future__ import annotations

import math
import threading

import numpy as np

GRID_DT_S = 1.0  # dense verification step [s]
KEEPOUT_TOL_M = 1e-6
CHUNK = 64  # rows/times per assembly chunk (cancel check between chunks)
CAP_SHAPES = ("box", "octahedron")
MAX_CANDIDATES = 8  # fixed head-on normal candidates per degenerate obstacle
AXES = np.array([[1.0, 0, 0], [-1.0, 0, 0], [0, 1.0, 0], [0, -1.0, 0], [0, 0, 1.0], [0, 0, -1.0]])


class TransferCancelled(RuntimeError):
    """cancel_event was set between solves; no partial result is returned."""


def check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise TransferCancelled("transfer solve cancelled")


def finite(v, name: str) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number, got {v!r}") from None
    if not math.isfinite(f):
        raise ValueError(f"{name} must be finite, got {v!r}")
    return f


def validate(*, n, a_max, k, N, cap_shape="box", x0=None, x_target=None, T=None, keepout=None):
    """Malformed input -> ValueError (programming error). a_max = 0 or k = 0 are legal (no
    thrust / no fuel) and later give None. Returns (cleaned keepout list, x0, x_target)."""
    if finite(n, "n") <= 0.0:
        raise ValueError(f"n must be > 0, got {n!r}")
    if finite(a_max, "a_max") < 0.0:
        raise ValueError(f"a_max must be >= 0, got {a_max!r}")
    if not 0.0 <= finite(k, "k") <= 1.0:
        raise ValueError(f"k (health) must be in [0, 1], got {k!r}")
    if isinstance(N, bool) or not isinstance(N, int | np.integer) or N < 1:
        raise ValueError(f"N must be an integer >= 1, got {N!r}")
    if cap_shape not in CAP_SHAPES:
        raise ValueError(f"cap_shape must be one of {CAP_SHAPES}, got {cap_shape!r}")
    if T is not None and finite(T, "T") <= 0.0:
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
        if finite(d, f"keepout[{i}] d_safe") <= 0.0:
            raise ValueError(f"keepout[{i}] d_safe must be > 0")
        clean.append((ts, pos, float(d)))
    return clean, out[0], out[1]


def rv(tau: np.ndarray, n: float) -> np.ndarray:
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


def free_positions(x0: np.ndarray, n: float, t: np.ndarray) -> np.ndarray:
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


def blocks(t: np.ndarray, times: np.ndarray, n: float) -> np.ndarray:
    """(S, N, 3, 3): Phi_rv(t_s - t_k) for t_k <= t_s, else 0."""
    tau = t[:, None] - times[None, :]
    live = tau >= 0.0
    return rv(np.where(live, tau, 0.0), n) * live[..., None, None]


def plan_positions(x0, times, dv, n: float, t, cancel_event=None) -> np.ndarray:
    """Position of x0 under impulses dv at `times`, at times t (vectorised)."""
    t = np.asarray(t, dtype=float)
    pos = free_positions(np.asarray(x0, dtype=float), n, t)
    for i in range(0, t.size, CHUNK):
        check_cancel(cancel_event)
        sl = slice(i, i + CHUNK)
        pos[sl] += np.einsum("snij,nj->si", blocks(t[sl], times, n), dv)
    return pos


class KeepoutGrid:
    """Dense 1 s verification grid of [0, T] (plus every sample time) with each obstacle
    linearly interpolated onto it (nan outside its time range)."""

    def __init__(self, keepout, x0, n: float, T: float, times: np.ndarray):
        self.n, self.times = n, times
        extra = [t[(t >= 0.0) & (t <= T)] for t, _, _ in keepout]
        self.grid = np.unique(np.concatenate([np.arange(0.0, T, GRID_DT_S), [T], *extra]))
        obs = []
        for ts, pos, _ in keepout:
            p = np.stack([np.interp(self.grid, ts, pos[:, i]) for i in range(3)], axis=1)
            p[(self.grid < ts[0]) | (self.grid > ts[-1])] = np.nan
            obs.append(p)
        self.obs = np.stack(obs)  # (n_obs, S, 3)
        self.d = np.array([d for _, _, d in keepout])
        self.free = free_positions(x0, n, self.grid)

    def verify(self, pos):
        """(dist (n_obs, S) with nan outside range, violated mask)."""
        dist = np.linalg.norm(pos[None] - self.obs, axis=2)
        with np.errstate(invalid="ignore"):
            return dist, dist < self.d[:, None] - KEEPOUT_TOL_M

    def degenerate(self, pos, dist, bad) -> dict[int, list[np.ndarray]]:
        """Obstacles with a violated grid time whose relative vector is ~0, i.e. shorter than
        max(1 m, 1e-3 d_safe, |v_rel| * GRID_DT_S) (the last term: a crossing between two grid
        points leaves |rel| ~ v_rel * 0.5 s): the half-space normal is then undefined or flips
        sides. Returns up to MAX_CANDIDATES fixed unit normals per such obstacle: +-x, +-y, +-z,
        then +-u, u = unit(cross(v_rel, z)) (cross(v_rel, x) when that vanishes), v_rel =
        d(plan - obstacle)/dt at the closest violated time."""
        out = {}
        for o in range(self.d.size):
            rel = pos - self.obs[o]
            with np.errstate(invalid="ignore"):
                v = np.gradient(rel, self.grid, axis=0)
                speed = np.linalg.norm(v, axis=1)
                near = bad[o] & (
                    dist[o] < np.maximum(max(1.0, 1e-3 * self.d[o]), speed * GRID_DT_S)
                )
            if not near.any():
                continue
            g = int(np.nonzero(near)[0][np.argmin(dist[o][near])])
            vg = v[g]
            cands = list(AXES)
            for ref in (np.array([0.0, 0.0, 1.0]), np.array([1.0, 0.0, 0.0])):
                u = np.cross(vg, ref)
                if np.isfinite(u).all() and np.linalg.norm(u) > 1e-9 * max(1.0, np.linalg.norm(vg)):
                    u = u / np.linalg.norm(u)
                    cands += [u, -u]
                    break
            out[o] = cands[:MAX_CANDIDATES]
        return out

    def rows(self, active, pos, fixed, cancel_event=None):
        """Half-space rows n.(rho - rho_o) >= d_safe for every active (obstacle, time) pair as
        A_ub x <= b_ub on [dv+, dv-]. n = unit(plan - obstacle) at `pos` (latest iterate), or
        fixed[o] (one unit vector for ALL rows of obstacle o: a consistent side)."""
        N = self.times.size
        rows, rhs = [], []
        oi, gi = np.nonzero(active)
        for lo in range(0, gi.size, CHUNK):
            if lo:
                check_cancel(cancel_event)
            o, g = oi[lo : lo + CHUNK], gi[lo : lo + CHUNK]
            p = self.obs[o, g]
            nrm = pos[g] - p
            norm = np.linalg.norm(nrm, axis=1, keepdims=True)
            nrm = np.where(norm > 1e-9, nrm / np.maximum(norm, 1e-9), [1.0, 0.0, 0.0])
            for j, oj in enumerate(o):
                if int(oj) in fixed:
                    nrm[j] = fixed[int(oj)]
            R = np.transpose(blocks(self.grid[g], self.times, self.n), (0, 2, 1, 3))
            row = np.einsum("ai,aij->aj", nrm, R.reshape(-1, 3, 3 * N))  # n.rho = n.free + row@dv
            rows.append(np.hstack([-row, row]))
            rhs.append(np.einsum("ai,ai->a", nrm, self.free[g] - p) - self.d[o])
        return np.vstack(rows), np.concatenate(rhs)
