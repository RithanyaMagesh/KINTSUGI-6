"""Candidate seat moves for the recovery ladder (cubesat/ladder.py): L2 local re-seat, L3 full
re-formation and the move-to-the-cripple ring. Pure: no RNG, no wall clock.

A candidate = {sat id: seat at formation t = 0} for the movers. Pre-filter (cheap, CW): every
pair of seats in the candidate and of the sats that stay put, and every seat against every
obstacle (dead or passive sats, CW-propagated from their TRUE state now), keeps >= d_safe over
one orbit (SWEEP_SAMPLES samples). Transfers: L1-optimal CW plan (transfer.best_transfer, one
orbit, keep-out around the obstacles), then SHOOTING: fly the burns in the certificate's truth
simulation (certify_sim.simulate, the engine stepper), measure the miss vs the seat at the end
and re-aim the CW target by minus the miss, up to SHOOT_ITERS times (CW is not truth: a raw CW
plan lands 0.1-1 km off at 8 km). The certificate then judges the corrected plan.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.optimize import linear_sum_assignment

from cubesat import truth
from cubesat.certify_sim import SWEEP_SAMPLES, burn_span, coverage_estimate, simulate
from cubesat.hcw import propagate, slot_initial_state, stm
from cubesat.transfer import best_transfer

SHOOT_ITERS = 3
FUEL_RESERVE = 0.20  # = certify default
N_NODES = 48
_EPS = 1e-9  # index tie-break (AGENTS.md invariant 6)


def ring(amp_m, theta0, psi_rad, k, n, cross_amp_m=None):
    """k seats (t = 0) on the passive 2:1 ellipse; = allocate_v2.candidate_slots when
    cross_amp_m is None (B = A); the cripple ring passes the cripple's own B."""
    b = amp_m if cross_amp_m is None else cross_amp_m
    out = []
    for j in range(k):
        th = theta0 + 2.0 * math.pi * j / k
        s = slot_initial_state(amp_m, amp_m, th, n)
        s[[2, 5]] = slot_initial_state(amp_m, b, th + psi_rad, n)[[2, 5]]
        out.append(s)
    return out


def ring_through(seat0, k, n):
    """The k-seat ring whose seat 0 is `seat0` (a seat at t = 0 on a passive 2:1 ellipse):
    the formation centred on that sat's natural relative orbit."""
    x, y, z, _, _, vz = seat0
    amp, th = math.hypot(x, y / 2.0), math.atan2(-y / 2.0, x)
    b, phz = math.hypot(z, vz / n), math.atan2(-vz / n, z)
    return ring(amp, th, phz - th, k, n, cross_amp_m=b)


def _tracks(states_now, n, period):
    """(SWEEP_SAMPLES, M, 3) CW positions over one orbit from states at now."""
    ts = [m * period / SWEEP_SAMPLES for m in range(SWEEP_SAMPLES)]
    if not len(states_now):
        return np.zeros((len(ts), 0, 3))
    return np.array([[(stm(t, n) @ s)[:3] for s in states_now] for t in ts])


def clear(seats_now, obstacles_now, n, d_safe):
    """Min CW distance over one orbit among seats and seat-to-obstacle >= d_safe."""
    period = 2.0 * math.pi / n
    a, o = _tracks(seats_now, n, period), _tracks(obstacles_now, n, period)
    if a.shape[1] >= 2:
        d = np.linalg.norm(a[:, :, None] - a[:, None, :], axis=-1)
        d[:, np.arange(a.shape[1]), np.arange(a.shape[1])] = np.inf
        if d.min() < d_safe:
            return False
    if o.shape[1] and a.shape[1]:
        return bool(np.linalg.norm(a[:, :, None] - o[:, None, :], axis=-1).min() >= d_safe)
    return True


def assign(lvlh, movers, pool_now):
    """Hungarian, rows = movers, cols = pool seats, cost = position distance + index eps.
    Returns {mover: pool index} and the summed distance."""
    cost = np.array([[np.linalg.norm(lvlh[i, :3] - s[:3]) for s in pool_now] for i in movers])
    cost = cost + _EPS * np.arange(cost.size).reshape(cost.shape)
    rows, cols = linear_sum_assignment(cost)
    out = {movers[r]: int(c) for r, c in zip(rows, cols, strict=True)}
    return out, float(cost[rows, cols].sum())


def estimate(seats_now_all, imagers, ctx):
    return coverage_estimate(list(seats_now_all), imagers, r_f=ctx.r_f, grid=ctx.grid, n=ctx.n)


def transfers(ctx, state, lvlh, targets, obstacles_now, d_safe, cancel=None):
    """{mover: Transfer} landing on targets {mover: seat0} in TRUTH (shooting), or a string
    saying why not. A mover already on its seat (< 1 m, < 1 mm/s) gets no transfer."""
    n, t, dt = ctx.n, state.t_s, ctx.dt
    period = 2.0 * math.pi / n
    obs = []
    if len(obstacles_now):
        times = np.arange(0.0, period + 60.0, 60.0)
        for s in obstacles_now:
            obs.append((times, np.array([(stm(tt, n) @ s)[:3] for tt in times]), d_safe))
    corr = {i: np.zeros(6) for i in targets}
    plan = {}

    def solve(i):
        sat, seat0 = state.sats[i], targets[i]
        tgt = lambda T, s=seat0, c=corr[i]: propagate(s, t + T, n) + c  # noqa: E731
        return best_transfer(
            lvlh[i], tgt, n, sat.f_max_n / sat.m_kg, sat.k, N=N_NODES, orbits=(1,),
            keepout=obs or None, cancel_event=cancel,
        )

    for i, seat0 in targets.items():
        here = propagate(seat0, t, n) - lvlh[i]
        if np.linalg.norm(here[:3]) < 1.0 and np.linalg.norm(here[3:]) < 1e-3:
            continue
        plan[i] = solve(i)
        if plan[i] is None:
            return f"no CW transfer for sat {i} (cap, fuel or keep-out)"
        need, have = plan[i].l2_dv_mps, state.sats[i].fuel_mps_left * (1.0 - FUEL_RESERVE)
        if need > have:  # the certificate's static fuel check, before the costly shooting
            return f"sat {i} needs {need:.3f} m/s, {have:.3f} m/s usable"
    seats_now = np.array(state.refs, dtype=float)
    for i, seat0 in targets.items():
        seats_now[i] = propagate(seat0, t, n)
    for _ in range(SHOOT_ITERS if plan else 0):
        steps = max(burn_span(tr, state.sats[i], dt)[2] for i, tr in plan.items())
        res = simulate(ctx.scenario, state, seats_now, plan, steps, cancel)
        X = res.final_eci
        fin = truth.eci_to_lvlh(X[1:, :3], X[1:, 3:], X[0, :3], X[0, 3:])
        worst = 0.0
        for i in plan:
            miss = fin[i] - propagate(targets[i], t + steps * dt, n)
            worst = max(worst, float(np.linalg.norm(miss[:3])))
            corr[i] = corr[i] - miss
        if worst < ctx.landing_tol_m / 2.0:
            break
        for i in list(plan):
            plan[i] = solve(i)
            if plan[i] is None:
                return f"no CW transfer for sat {i} after re-aiming"
    return plan
