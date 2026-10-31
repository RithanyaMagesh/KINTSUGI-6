"""Phase 5c: LP fuel-optimal CW transfers (cubesat/transfer.py). SI, LVLH."""

from __future__ import annotations

import math

import numpy as np
import pytest

from cubesat.dv_bound import two_impulse_dv
from cubesat.hcw import mean_motion, propagate, slot_initial_state, stm
from cubesat.transfer import (
    Transfer,
    lp_transfer,
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
    assert tr.total_dv_mps == pytest.approx(
        np.abs(dv1).sum() + np.abs(dv2).sum(), rel=1e-6
    )
    assert list(tr.times) == [0.0, T_S]


def test_lp_never_worse_than_two_impulse():
    tr = plan(N=12)
    dv1, dv2 = two_impulse_vectors(SLOT0, target(T_S), T_S)
    assert tr is not None
    assert tr.total_dv_mps <= np.abs(dv1).sum() + np.abs(dv2).sum() + 1e-9


@pytest.mark.parametrize(
    "kw",
    [{"k": 0.0}, {"a_max": 1e-9}, {"T": 5.0}, {"a_max": 0.0}, {"N": 0}],
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

