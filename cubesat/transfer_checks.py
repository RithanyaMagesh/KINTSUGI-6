"""Independent checks of the LP planner (Phase 5c fix round): true L2 optimum by SLSQP, spherical
cap minimum, and the two seeded fuzz runs behind `cubesat.transfer_report`. Report-side only
(scipy SLSQP is not used by the planner). SI, LVLH."""

from __future__ import annotations

import math
import time

import numpy as np
from scipy.optimize import minimize

from cubesat.hcw import mean_motion, propagate, slot_initial_state, stm
from cubesat.transfer import Transfer, _plan_positions, lp_transfer, propagate_plan

N_MM = mean_motion(500e3)
PERIOD = 2.0 * math.pi / N_MM
SEED = 20261031


def _system(x0, x_target, T, n, N):
    times = np.linspace(0.0, T, N)
    G = np.hstack([stm(T - t, n)[:, 3:] for t in times])
    return times, G, np.asarray(x_target, float) - stm(T, n) @ np.asarray(x0, float)


def _landing(x0, x_target, times, v, T, n) -> float:
    tr = Transfer(v.reshape(-1, 3), times, 0.0, T, 1)
    return float(np.linalg.norm(propagate_plan(x0, tr, n) - x_target))


def l2_optimum(x0, x_target, T, n, a_max, N, cap: str, eps_rel=1e-6) -> dict:
    """Minimum of sum ||dv_k||_2 under the landing equality and cap = 'box' (|dv_axis| <=
    a_max*(T/N)/sqrt3) or 'sphere' (||dv_k|| <= a_max*T/N), by SLSQP (smoothed norm, eps =
    (eps_rel * cap)^2) started from the LP plan of a cap-feasible shape."""
    times, G, b = _system(x0, x_target, T, n, N)
    S = np.diag([n, n, n, 1.0, 1.0, 1.0])
    Gs, bs = S @ G, S @ b
    c_norm = a_max * T / N
    start = lp_transfer(
        x0, x_target, T, n, a_max, 1.0, N, cap_shape="box" if cap == "box" else "octahedron"
    )
    if start is None:
        return {"success": False}
    eps = (eps_rel * c_norm) ** 2

    def f(v):
        return float(np.sqrt((v.reshape(-1, 3) ** 2).sum(1) + eps).sum())

    def jac(v):
        w = v.reshape(-1, 3)
        return (w / np.sqrt((w**2).sum(1, keepdims=True) + eps)).ravel()

    cons = [{"type": "eq", "fun": lambda v: Gs @ v - bs, "jac": lambda v: Gs}]
    bounds = None
    if cap == "box":
        cc = c_norm / math.sqrt(3.0)
        bounds = [(-cc, cc)] * (3 * N)
    else:

        def ineq(v):
            return c_norm**2 - (v.reshape(-1, 3) ** 2).sum(1)

        def ineq_jac(v):
            J = np.zeros((N, 3 * N))
            for i in range(N):
                J[i, 3 * i : 3 * i + 3] = -2.0 * v[3 * i : 3 * i + 3]
            return J

        cons.append({"type": "ineq", "fun": ineq, "jac": ineq_jac})
    res = minimize(
        f,
        start.dv.ravel(),
        jac=jac,
        constraints=cons,
        bounds=bounds,
        method="SLSQP",
        options={"maxiter": 2000, "ftol": 1e-12},
    )
    v = res.x
    dv = v.reshape(-1, 3)
    return {
        "success": bool(res.success),
        "nit": int(res.nit),
        "l2_mps": float(np.linalg.norm(dv, axis=1).sum()),
        "l1_mps": float(np.abs(dv).sum()),
        "landing_residual_m": _landing(
            np.asarray(x0, float), np.asarray(x_target, float), times, v, T, n
        ),
    }


def dual_lower_bound_l2(x0, x_target, T, n, N) -> float:
    """Certified lower bound on the UNCAPPED minimum of sum ||dv_k||_2: any lambda with
    ||G_k^T lambda|| <= 1 for all k gives b.lambda <= optimum (weak duality). lambda from SLSQP,
    then rescaled to be exactly dual-feasible."""
    times, G, b = _system(x0, x_target, T, n, N)
    S = np.diag([n, n, n, 1.0, 1.0, 1.0])
    Gs, bs = S @ G, S @ b
    Gk = [Gs[:, 3 * i : 3 * i + 3] for i in range(N)]
    cons = {
        "type": "ineq",
        "fun": lambda lam: np.array([1.0 - np.sum((g.T @ lam) ** 2) for g in Gk]),
    }
    res = minimize(
        lambda lam: -bs @ lam,
        np.zeros(6),
        constraints=[cons],
        method="SLSQP",
        options={"maxiter": 500, "ftol": 1e-14},
    )
    lam = res.x
    worst = max(float(np.linalg.norm(g.T @ lam)) for g in Gk)
    return float(bs @ lam / max(worst, 1.0))


def sphere_min_a_max(x0, x_target, T, n, N, a_hint: float) -> dict:
    """Smallest a_max for which a plan with ||dv_k|| <= a_max*T/N lands (SLSQP min-max impulse
    norm, started from the octahedron plan at a_hint)."""
    times, G, b = _system(x0, x_target, T, n, N)
    S = np.diag([n, n, n, 1.0, 1.0, 1.0])
    Gs, bs = S @ G, S @ b
    start = lp_transfer(x0, x_target, T, n, a_hint, 1.0, N, cap_shape="octahedron")
    v0 = np.append(start.dv.ravel(), np.linalg.norm(start.dv, axis=1).max())

    def ineq(z):
        return z[-1] ** 2 - (z[:-1].reshape(-1, 3) ** 2).sum(1)

    def ineq_jac(z):
        J = np.zeros((N, 3 * N + 1))
        for i in range(N):
            J[i, 3 * i : 3 * i + 3] = -2.0 * z[3 * i : 3 * i + 3]
        J[:, -1] = 2.0 * z[-1]
        return J

    cons = [
        {
            "type": "eq",
            "fun": lambda z: Gs @ z[:-1] - bs,
            "jac": lambda z: np.hstack([Gs, np.zeros((6, 1))]),
        },
        {"type": "ineq", "fun": ineq, "jac": ineq_jac},
    ]
    res = minimize(
        lambda z: z[-1],
        v0,
        jac=lambda z: np.eye(3 * N + 1)[-1],
        constraints=cons,
        method="SLSQP",
        options={"maxiter": 2000, "ftol": 1e-14},
    )
    return {"a_max_mps2": float(res.x[-1] * N / T), "success": bool(res.success)}


def min_feasible_a_max(x0, x_target, T, n, N, **kw) -> float:
    """Bisection on lp_transfer feasibility (log scale, 50 halvings)."""
    lo, hi = 1e-5, 1.0
    for _ in range(50):
        mid = math.sqrt(lo * hi)
        ok = lp_transfer(x0, x_target, T, n, mid, 1.0, N, **kw) is not None
        lo, hi = (lo, mid) if ok else (mid, hi)
    return hi


def landing_fuzz(cases: int = 300) -> dict:
    """Seeded random transfers, 1 m .. 2e6 m, T 0.3-2.5 orbits, a_max 1e-2..10, N in
    {2, 12, 48}: how many plans ship and the worst landing residual among them."""
    rng = np.random.default_rng(SEED)
    s0 = slot_initial_state(8000.0, 8000.0, 0.0, N_MM)
    feasible, worst_abs, worst_vel, worst_rel, worst_scale = 0, 0.0, 0.0, 0.0, 0.0
    for _ in range(cases):
        dist = 10 ** rng.uniform(0.0, math.log10(2e6))
        d = rng.normal(size=3)
        x0 = s0.copy()
        x0[:3] += dist * d / np.linalg.norm(d)
        x0[3:] += rng.normal(size=3) * 1e-3 * dist * N_MM
        T = PERIOD * rng.uniform(0.3, 2.5)
        a_max, N = 10 ** rng.uniform(-2.0, 1.0), int(rng.choice([2, 12, 48]))
        xt = propagate(slot_initial_state(8000.0, 8000.0, 2 * math.pi / 5, N_MM), T, N_MM)
        tr = lp_transfer(x0, xt, T, N_MM, a_max, 1.0, N)
        if tr is None:
            continue
        feasible += 1
        r = propagate_plan(x0, tr, N_MM) - xt
        worst_abs = max(worst_abs, float(np.abs(r[:3]).max()))
        worst_vel = max(worst_vel, float(np.abs(r[3:]).max()))
        rel = float(np.linalg.norm(r)) / max(1.0, float(np.linalg.norm(xt)))
        if rel > worst_rel:
            worst_rel, worst_scale = rel, float(np.linalg.norm(xt))
    return {
        "seed": SEED,
        "cases": cases,
        "feasible": feasible,
        "none": cases - feasible,
        "worst_abs_position_residual_m": worst_abs,
        "worst_abs_velocity_residual_mps": worst_vel,
        "worst_rel_residual": worst_rel,
        "norm_x_target_at_worst_rel": worst_scale,
        "post_check_tolerance": "1e-6 * max(1, |x_target|) on the 6-vector 2-norm",
    }


def _true_min(s0, tr, ts, pos):
    """True minimum plan-obstacle distance on a 0.05 s grid (linear obstacle) and the largest
    relative speed seen there."""
    fine = np.arange(ts[0], ts[1], 0.05)
    mine = _plan_positions(s0, tr, N_MM, fine)
    obs = np.stack([np.interp(fine, ts, pos[:, i]) for i in range(3)], axis=1)
    rel = mine - obs
    return float(np.linalg.norm(rel, axis=1).min()), float(
        np.linalg.norm(np.gradient(rel, 0.05, axis=0), axis=1).max()
    )


def head_on(
    cases=(
        (10, 2.0),
        (10, 10.0),
        (20, 2.0),
        (20, 10.0),
        (50, 2.0),
        (50, 10.0),
        (96, 2.0),
        (96, 10.0),
    ),
) -> dict:
    """The exact head-on geometry: an obstacle moving along z at v through the FREE plan's
    position at tc (mid-interval), d_safe 300 m, m samples over [T/m, T]; offset 0 (head-on) and
    +150 m in x (reference). True min distance on a 0.25 s grid within +-60 s of tc."""
    s0 = slot_initial_state(8000.0, 8000.0, 0.0, N_MM)
    xt = propagate(slot_initial_state(8000.0, 8000.0, 2 * math.pi / 5, N_MM), PERIOD, N_MM)
    T, N, a_max, d = PERIOD, 48, 0.05, 300.0
    free = lp_transfer(s0, xt, T, N_MM, a_max, 1.0, N)
    rows = []
    for m, v in cases:
        ts = np.linspace(T / m, T, m)
        tc = ts[m // 2] + (ts[1] - ts[0]) / 2
        pc = _plan_positions(s0, free, N_MM, [tc])[0]
        row = {"m_samples": m, "v_mps": v, "d_safe_m": d}
        for name, off in (("head_on", 0.0), ("offset_150m_x", 150.0)):
            c = pc + np.array([off, 0.0, 0.0])
            pos = np.array([c + np.array([0.0, 0.0, v]) * (t - tc) for t in ts])
            t0 = time.perf_counter()
            tr = lp_transfer(s0, xt, T, N_MM, a_max, 1.0, N, keepout=[(ts, pos, d)])
            ms = (time.perf_counter() - t0) * 1e3
            fine = np.arange(tc - 60.0, tc + 60.0, 0.25)
            obs = c + np.array([0.0, 0.0, v]) * (fine - tc)[:, None]
            mine = None if tr is None else _plan_positions(s0, tr, N_MM, fine)
            row[name] = {
                "planned": tr is not None,
                "l1_mps": None if tr is None else tr.total_dv_mps,
                "verified_clearance_m": None if tr is None else tr.min_clearance_m,
                "true_min_distance_m": None
                if tr is None
                else float(np.linalg.norm(mine - obs, axis=1).min()),
                "lp_solves": None if tr is None else tr.feasible_iterations,
                "runtime_ms_machine_dependent": ms,
            }
        rows.append(row)
    return {"free_plan_l1_mps": free.total_dv_mps, "rows": rows}


def keepout_fuzz(cases: int = 100) -> dict:
    """Seeded random crossings: an obstacle with two samples straddling the free path at
    tc +/- h (far on opposite sides), d_safe 200-1000 m. For each plan the TRUE minimum distance
    is measured on a 0.05 s grid with linear interpolation; shortfall = d_safe - true min."""
    rng = np.random.default_rng(SEED)
    s0 = slot_initial_state(8000.0, 8000.0, 0.0, N_MM)
    xt = propagate(slot_initial_state(8000.0, 8000.0, 2 * math.pi / 5, N_MM), PERIOD, N_MM)
    T, N, a_max = PERIOD, 24, 0.05
    free = lp_transfer(s0, xt, T, N_MM, a_max, 1.0, N)
    planned, collide, worst_short, worst_ratio, worst_grid = 0, 0, -math.inf, 0.0, 0.0
    for _ in range(cases):
        tc, h = rng.uniform(0.2, 0.8) * T, rng.uniform(10.0, 120.0)
        u = rng.normal(size=3)
        u /= np.linalg.norm(u)
        w, d = rng.uniform(500.0, 3000.0), rng.uniform(200.0, 1000.0)
        ts = np.array([tc - h, tc + h])
        pa, pb = (_plan_positions(s0, free, N_MM, ts)[i] for i in range(2))
        pos = np.array([pa + w * u, pb - w * u])
        collide += _true_min(s0, free, ts, pos)[0] < d
        tr = lp_transfer(s0, xt, T, N_MM, a_max, 1.0, N, keepout=[(ts, pos, d)])
        if tr is None:
            continue
        planned += 1
        worst_grid = max(worst_grid, d - tr.min_clearance_m)
        tmin, vrel = _true_min(s0, tr, ts, pos)
        worst_short = max(worst_short, d - tmin)
        worst_ratio = max(worst_ratio, max(d - tmin, 0.0) / (0.5 * vrel))
    return {
        "seed": SEED,
        "cases": cases,
        "planned": planned,
        "none": cases - planned,
        "free_plan_collides_cases": int(collide),
        "worst_true_shortfall_m": worst_short,
        "worst_verified_grid_shortfall_m": max(worst_grid, 0.0),
        "worst_shortfall_over_half_vrel": worst_ratio,
        "note": "shortfall = d_safe - true minimum distance (0.05 s grid, linear obstacle); the "
        "1 s verification grid bounds it by v_rel * 0.5 s (ratio <= 1)",
        "head_on": head_on(),
    }
