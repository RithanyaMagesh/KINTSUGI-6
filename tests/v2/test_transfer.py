"""Phase 5c: L1-optimal impulse CW transfers (cubesat/transfer.py). SI, LVLH."""

from __future__ import annotations

import math
import threading

import numpy as np
import pytest

from cubesat.dv_bound import two_impulse_dv
from cubesat.hcw import mean_motion, propagate, slot_initial_state, stm
from cubesat.transfer import (
    Transfer,
    TransferCancelled,
    best_transfer,
    lp_transfer,
    mpc_step,
    propagate_plan,
)

N_MM = mean_motion(500e3)
PERIOD = 2.0 * math.pi / N_MM
A = 8000.0
SLOT0 = slot_initial_state(A, A, 0.0, N_MM)
SLOT1 = slot_initial_state(A, A, 2.0 * math.pi / 5.0, N_MM)
T_S = 4000.0  # not a multiple of half a period: the two-impulse solve is non-singular
A_BIG = 0.05


def target(T: float) -> np.ndarray:
    return propagate(SLOT1, T, N_MM)


def plan(a_max=A_BIG, k=1.0, N=12, T=T_S, **kw) -> Transfer | None:
    return lp_transfer(SLOT0, target(T), T, N_MM, a_max, k, N, **kw)


def two_impulse_vectors(x0, x_t, T):
    """The unique N=2 impulses (t=0 and t=T) as vectors: same maths as dv_bound."""
    Phi = stm(T, N_MM)
    v1 = np.linalg.solve(Phi[:3, 3:], x_t[:3] - Phi[:3, :3] @ x0[:3])
    dv1 = v1 - x0[3:]
    v_arr = Phi[3:, :3] @ x0[:3] + Phi[3:, 3:] @ v1
    return dv1, x_t[3:] - v_arr


def test_lp_lands_on_target_exactly():
    tr = plan()
    assert tr is not None
    xf = propagate_plan(SLOT0, tr, N_MM)
    assert np.max(np.abs(xf[:3] - target(T_S)[:3])) < 1e-6
    assert np.max(np.abs(xf[3:] - target(T_S)[3:])) < 1e-9


def test_lp_n2_equals_two_impulse():
    tr = plan(N=2)
    assert tr is not None
    ref = two_impulse_dv(SLOT0, SLOT1, 0.0, T_S, N_MM)
    dv1, dv2 = two_impulse_vectors(SLOT0, target(T_S), T_S)
    assert tr.l2_dv_mps == pytest.approx(ref["dv_total_mps"], rel=1e-6)
    assert tr.total_dv_mps == pytest.approx(np.abs(dv1).sum() + np.abs(dv2).sum(), rel=1e-6)
    assert list(tr.times) == [0.0, T_S]


def test_lp_never_worse_than_two_impulse():
    tr = plan(N=12)
    dv1, dv2 = two_impulse_vectors(SLOT0, target(T_S), T_S)
    assert tr is not None
    assert tr.total_dv_mps <= np.abs(dv1).sum() + np.abs(dv2).sum() + 1e-9


@pytest.mark.parametrize(
    "kw",
    [{"k": 0.0}, {"a_max": 1e-9}, {"T": 5.0}, {"a_max": 0.0}],
)
def test_infeasible_returns_none_not_raise(kw):
    assert plan(**kw) is None


def test_per_component_cap_respected_and_binding():
    big = plan(N=12)
    assert big is not None
    cap = 0.8 * float(np.abs(big.dv).max())
    a_max = cap * math.sqrt(3.0) * 12 / T_S
    tr = plan(a_max=a_max, N=12)
    assert tr is not None, "0.8x the free plan's peak must stay feasible"
    assert np.abs(tr.dv).max() <= cap + 1e-12
    assert np.abs(tr.dv).max() > 0.99 * cap  # the cap is actually active
    assert np.linalg.norm(tr.dv, axis=1).max() <= a_max * T_S / 12 + 1e-12  # |a|<=a_max


def test_cap_scales_with_health():
    peak = float(np.abs(plan(N=12).dv).max())  # free plan's largest component
    a_max = 1.5 * peak * math.sqrt(3.0) * 12 / T_S  # k=1 cap = 1.5x peak
    half, tiny = plan(a_max=a_max, k=0.5), plan(a_max=a_max, k=0.05)
    assert half is not None and tiny is None  # health shrinks the cap, then infeasible
    assert np.abs(half.dv).max() <= 0.5 * a_max * (T_S / 12) / math.sqrt(3.0) + 1e-12


def test_lp_deterministic():
    a, b = plan(), plan()
    assert a is not None and b is not None
    assert np.array_equal(a.dv, b.dv) and a.total_dv_mps == b.total_dv_mps


def _path_obstacle(free: Transfer, d_safe: float, frac=(0.3, 0.7), m=20):
    """Obstacle parked exactly on the free plan's path at samples in the middle."""
    ts = np.linspace(0.0, T_S, m + 1)[1:]
    pos = np.array([propagate_plan(SLOT0, free, N_MM, t)[:3] for t in ts])
    far = np.array([1e6, 1e6, 1e6])
    pos = np.where(((ts >= frac[0] * T_S) & (ts <= frac[1] * T_S))[:, None], pos, far)
    return [(ts, pos, d_safe)]


def test_keepout_avoids_obstacle_on_straight_path():
    free = plan()
    assert free is not None
    ko = _path_obstacle(free, 500.0)
    # the free plan violates the keep-out (so the test can fail)
    ts, pos, d = ko[0]
    free_d = [
        np.linalg.norm(propagate_plan(SLOT0, free, N_MM, t)[:3] - p)
        for t, p in zip(ts, pos, strict=True)
    ]
    assert min(free_d) < 1.0
    tr = plan(keepout=ko)
    assert tr is not None
    for t, p in zip(ts, pos, strict=True):
        assert np.linalg.norm(propagate_plan(SLOT0, tr, N_MM, t)[:3] - p) >= 500.0 - 1e-6
    xf = propagate_plan(SLOT0, tr, N_MM)
    assert np.max(np.abs(xf - target(T_S))) < 1e-5
    assert tr.total_dv_mps >= free.total_dv_mps - 1e-9
    assert 2 <= tr.feasible_iterations <= 3


def test_keepout_obstacle_on_target_is_infeasible():
    ts = np.array([T_S])
    ko = [(ts, target(T_S)[None, :3], 500.0)]
    assert plan(keepout=ko) is None


# ---- 5c.2: best_transfer + mpc_step -------------------------------------------------
def _best(a_max=A_BIG, **kw):
    return best_transfer(SLOT0, target, N_MM, a_max, 1.0, N=24, **kw)


def test_best_transfer_picks_least_dv_feasible_T():
    best = _best()
    assert best is not None
    per_T = [
        lp_transfer(SLOT0, target(o * PERIOD), o * PERIOD, N_MM, A_BIG, 1.0, 24)
        for o in (0.5, 1.0, 2.0)
    ]
    feas = [t for t in per_T if t is not None]
    assert len(feas) == 3 and len({t.total_dv_mps for t in feas}) == 3
    assert best.total_dv_mps == min(t.total_dv_mps for t in feas)
    assert best.T_s == min(feas, key=lambda t: t.total_dv_mps).T_s


def test_best_transfer_tie_prefers_smaller_T():
    # target already on the free trajectory: every T needs zero dv -> shortest T wins
    free = lambda T: propagate(SLOT0, T, N_MM)  # noqa: E731
    best = best_transfer(SLOT0, free, N_MM, A_BIG, 1.0, N=12)
    assert best is not None and best.total_dv_mps == pytest.approx(0.0, abs=1e-9)
    assert best.T_s == pytest.approx(0.5 * PERIOD)


def test_best_transfer_falls_back_to_longer_T_at_low_a_max():
    # a_max low enough that 0.5 orbit is infeasible but 2 orbits is
    lo, hi = 1e-4, A_BIG
    for _ in range(40):  # smallest a_max for which T=0.5 orbit is feasible
        mid = math.sqrt(lo * hi)
        ok = lp_transfer(SLOT0, target(0.5 * PERIOD), 0.5 * PERIOD, N_MM, mid, 1.0, 24)
        lo, hi = (lo, mid) if ok else (mid, hi)
    a_max = 0.8 * hi  # just below the 0.5-orbit threshold
    assert lp_transfer(SLOT0, target(0.5 * PERIOD), 0.5 * PERIOD, N_MM, a_max, 1.0, 24) is None
    best = _best(a_max=a_max)
    assert best is not None and best.T_s > 0.5 * PERIOD
    assert best_transfer(SLOT0, target, N_MM, 1e-9, 1.0, N=24) is None


def test_cancel_mid_sweep_raises_without_partial_result():
    ev, calls = threading.Event(), []

    def fn(T):
        calls.append(T)
        if len(calls) == 2:
            ev.set()  # set while the sweep is running
        return target(T)

    with pytest.raises(TransferCancelled):
        best_transfer(SLOT0, fn, N_MM, A_BIG, 1.0, N=24, cancel_event=ev)
    assert len(calls) == 2  # stopped before the third T


def test_cancel_before_lp_raises():
    ev = threading.Event()
    ev.set()
    with pytest.raises(TransferCancelled):
        plan(cancel_event=ev)


def test_mpc_step_recovers_from_perturbation():
    T, dt, ticks = PERIOD, 2.0, 60
    first = lp_transfer(SLOT0, target(T), T, N_MM, 0.01, 1.0, 48)
    assert first is not None
    t_e = ticks * dt
    rng = np.random.default_rng(7)
    x = propagate_plan(SLOT0, first, N_MM, t_e)
    x_meas = x + np.concatenate([rng.normal(0, 5.0, 3), rng.normal(0, 0.01, 3)])
    # left alone the perturbation misses the target by metres
    miss = propagate_plan(x_meas, Transfer(first.dv[:0], first.times[:0], 0.0, T - t_e, 1), N_MM)
    assert np.linalg.norm(miss[:3] - target(T)[:3]) > 1.0
    fix = mpc_step(x_meas, target, t_e, T, N_MM, 0.01, 1.0, 48)
    assert fix is not None and fix.T_s == pytest.approx(T - t_e)
    xf = propagate_plan(x_meas, fix, N_MM)
    assert np.linalg.norm(xf[:3] - target(T)[:3]) < 1e-3
    assert mpc_step(x_meas, target, T + 1.0, T, N_MM, 0.01, 1.0, 48) is None  # no horizon left
    assert mpc_step(x_meas, target, t_e, T, N_MM, 0.01, 0.0, 48) is None  # zero fuel
