"""Phase 5c head-on keep-out: an obstacle crossing exactly THROUGH the free plan must not give a
false None (the half-space normal is undefined there, so fixed candidate normals are tried)."""

from __future__ import annotations

import math
import threading

import numpy as np
import pytest

import cubesat.transfer as tf
from cubesat.hcw import mean_motion, propagate, slot_initial_state
from cubesat.transfer import TransferCancelled, lp_transfer, propagate_plan

N_MM = mean_motion(500e3)
T = 2.0 * math.pi / N_MM
SLOT0 = slot_initial_state(8000.0, 8000.0, 0.0, N_MM)
SLOT1 = slot_initial_state(8000.0, 8000.0, 2.0 * math.pi / 5.0, N_MM)
XT = propagate(SLOT1, T, N_MM)
A_MAX, N_NODES, D_SAFE = 0.05, 48, 300.0
COMBOS = [(m, v) for m in (10, 20, 50, 96) for v in (2.0, 10.0)]


def solve(keepout=None, cancel_event=None):
    return lp_transfer(SLOT0, XT, T, N_MM, A_MAX, 1.0, N_NODES, keepout, cancel_event)


FREE = solve()


def pos_at(plan, t):
    return propagate_plan(SLOT0, plan, N_MM, t)[:3]


def head_on(m, v, offset=(0.0, 0.0, 0.0), axis=(0.0, 0.0, 1.0), frac=0.5):
    """Obstacle crossing through the free-plan point at tc with velocity v*axis (m samples)."""
    ts = np.linspace(T / m, T, m)
    tc = ts[int(m * frac)] + (ts[1] - ts[0]) / 2
    pc = pos_at(FREE, tc) + np.array(offset)
    vel = v * np.array(axis)
    return ts, np.array([pc + vel * (t - tc) for t in ts]), tc, pc, vel


def true_min_distance(plan, ts, pos, step=2.0):
    """Independent check with hcw.stm propagation (not the planner's vectorised model)."""
    grid = np.arange(ts[0], ts[-1], step)
    obs = np.stack([np.interp(grid, ts, pos[:, i]) for i in range(3)], axis=1)
    mine = np.array([pos_at(plan, t) for t in grid])
    return float(np.linalg.norm(mine - obs, axis=1).min())


def test_the_free_plan_really_collides_in_every_combo():
    for m, v in COMBOS[::3]:
        ts, pos, *_ = head_on(m, v)
        assert true_min_distance(FREE, ts, pos, 1.0) < 20.0


@pytest.mark.parametrize(("m", "v"), COMBOS)
def test_head_on_obstacle_through_the_free_plan_gets_a_verified_plan(m, v):
    ts, pos, tc, pc, vel = head_on(m, v)
    tr = solve([(ts, pos, D_SAFE)])
    assert tr is not None, "false None in exactly the most dangerous geometry"
    assert tr.min_clearance_m >= D_SAFE - 1e-6
    assert true_min_distance(tr, ts, pos) >= D_SAFE - 1e-3  # 2 s points are on the 1 s grid
    near = np.arange(tc - 40.0, tc + 40.0, 0.25)  # finer window around the crossing
    obs = np.array([pc + vel * (t - tc) for t in near])
    mine = np.array([pos_at(tr, t) for t in near])
    assert np.linalg.norm(mine - obs, axis=1).min() >= D_SAFE - 0.5 * 60.0  # v_rel * 0.5 s
    assert np.linalg.norm(propagate_plan(SLOT0, tr, N_MM) - XT) < 1e-3


@pytest.mark.slow
def test_head_on_cost_is_within_2_percent_of_the_best_offset_150_plan():
    best = min(
        solve([(ts, pos, D_SAFE)]).total_dv_mps
        for ts, pos, *_ in (head_on(m, v, offset=(150.0, 0, 0)) for m, v in COMBOS)
    )
    for m, v in COMBOS:
        ts, pos, *_ = head_on(m, v)
        assert solve([(ts, pos, D_SAFE)]).total_dv_mps <= 1.02 * best


def test_head_on_with_the_obstacle_moving_along_x_needs_a_perpendicular_candidate():
    ts, pos, *_ = head_on(50, 5.0, axis=(1.0, 0.0, 0.0))
    tr = solve([(ts, pos, D_SAFE)])  # +x is parallel to v_rel: only a perpendicular side works
    assert tr is not None and tr.min_clearance_m >= D_SAFE - 1e-6


def test_two_obstacles_crossing_head_on_at_different_times():
    a, b = head_on(50, 5.0, frac=0.3), head_on(50, 8.0, frac=0.7)
    tr = solve([(a[0], a[1], D_SAFE), (b[0], b[1], 250.0)])
    assert tr is not None
    assert true_min_distance(tr, a[0], a[1]) >= D_SAFE - 1e-3
    assert true_min_distance(tr, b[0], b[1]) >= 250.0 - 1e-3


def test_obstacle_on_the_target_or_on_the_start_is_still_none():
    on_target = [(np.array([T - 10.0, T]), np.array([XT[:3] + [0, 0, 5.0], XT[:3]]), D_SAFE)]
    assert solve(on_target) is None
    on_start = [(np.array([0.0, 50.0]), np.array([SLOT0[:3], SLOT0[:3] + 1e5]), D_SAFE)]
    assert solve(on_start) is None


def test_head_on_solve_is_deterministic():
    ts, pos, *_ = head_on(20, 2.0)
    a, b = solve([(ts, pos, D_SAFE)]), solve([(ts, pos, D_SAFE)])
    assert np.array_equal(a.dv, b.dv) and a.total_dv_mps == b.total_dv_mps


def test_nondegenerate_crossing_does_not_pay_for_the_multi_start(monkeypatch):
    ts, pos, *_ = head_on(20, 2.0, offset=(150.0, 0, 0))
    calls = []
    real = tf.linprog
    monkeypatch.setattr(tf, "linprog", lambda *a, **k: calls.append(1) or real(*a, **k))
    assert solve([(ts, pos, D_SAFE)]) is not None
    assert len(calls) <= 4  # unconstrained + at most 3 refinement solves


def test_multi_start_solve_count_is_bounded(monkeypatch):
    ts, pos, *_ = head_on(20, 2.0)
    calls = []
    real = tf.linprog
    monkeypatch.setattr(tf, "linprog", lambda *a, **k: calls.append(1) or real(*a, **k))
    solve([(ts, pos, D_SAFE)])
    assert len(calls) <= 1 + 3 + 8 * 3  # first attempt + 8 candidates x 3 refinement rounds


class CountingEvent(threading.Event):
    def __init__(self, limit=None):
        super().__init__()
        self.calls, self.limit = 0, limit

    def is_set(self):
        self.calls += 1
        return self.limit is not None and self.calls > self.limit


def test_cancel_works_inside_the_multi_start():
    ts, pos, *_ = head_on(20, 2.0)
    ev = CountingEvent()
    assert solve([(ts, pos, D_SAFE)], ev) is not None
    ev2 = CountingEvent(limit=int(ev.calls * 0.8))  # late: inside the candidate loop
    with pytest.raises(TransferCancelled):
        solve([(ts, pos, D_SAFE)], ev2)
    assert ev2.calls <= int(ev.calls * 0.8) + 1
