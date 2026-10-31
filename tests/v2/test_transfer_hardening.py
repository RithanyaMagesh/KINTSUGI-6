"""Phase 5c fix round: validation, solver post-check, verified keep-out, MPC horizon, cap shapes."""

from __future__ import annotations

import math
import threading
from types import SimpleNamespace

import numpy as np
import pytest

import cubesat.transfer as tf
from cubesat.hcw import mean_motion, propagate, slot_initial_state
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
T_S = 4000.0


def target(T: float) -> np.ndarray:
    return propagate(SLOT1, T, N_MM)


def plan(a_max=0.05, k=1.0, N=12, T=T_S, x0=SLOT0, **kw) -> Transfer | None:
    return lp_transfer(x0, target(T), T, N_MM, a_max, k, N, **kw)


# ---- 4: validation (ValueError) vs infeasibility (None) -----------------------------------
@pytest.mark.parametrize(
    "kw",
    [
        {"k": 1.5},
        {"k": 2.0},
        {"k": math.inf},
        {"k": -0.1},
        {"k": math.nan},
        {"a_max": -1.0},
        {"a_max": math.nan},
        {"a_max": math.inf},
        {"N": 2.7},
        {"N": 0},
        {"N": -3},
        {"N": True},
        {"T": math.nan},
        {"T": math.inf},
        {"T": -1.0},
        {"T": 0.0},
        {"x0": np.zeros(5)},
        {"x0": np.full(6, np.nan)},
        {"cap_shape": "sphere"},
    ],
)
def test_malformed_input_raises_valueerror(kw):
    with pytest.raises(ValueError):
        plan(**kw)


def test_malformed_n_and_target_and_keepout_raise():
    xt = target(T_S)
    for n in (0.0, -1.0, math.nan, math.inf):
        with pytest.raises(ValueError):
            lp_transfer(SLOT0, xt, T_S, n, 0.05, 1.0, 12)
    with pytest.raises(ValueError):
        lp_transfer(SLOT0, xt[:5], T_S, N_MM, 0.05, 1.0, 12)
    ts, pos = np.array([100.0, 200.0]), np.zeros((2, 3))
    for bad in (
        [(ts, pos[:1], 500.0)],  # length mismatch
        [(ts, np.full((2, 3), np.nan), 500.0)],
        [(np.array([200.0, 100.0]), pos, 500.0)],  # not increasing
        [(ts, pos, -1.0)],
        [(ts, pos, math.nan)],
    ):
        with pytest.raises(ValueError):
            plan(keepout=bad)


def test_best_transfer_and_mpc_validate_the_same_way():
    with pytest.raises(ValueError):
        best_transfer(SLOT0, target, N_MM, 0.05, 1.5)
    with pytest.raises(ValueError):
        best_transfer(SLOT0, target, N_MM, 0.05, 1.0, N=2.5)
    with pytest.raises(ValueError):
        best_transfer(SLOT0, target, N_MM, 0.05, 1.0, orbits=(0.0, 1))
    with pytest.raises(ValueError):
        mpc_step(SLOT0, target, -1.0, PERIOD, N_MM, 0.05, 1.0)  # negative t_elapsed
    with pytest.raises(ValueError):
        mpc_step(SLOT0, target, 0.0, PERIOD, N_MM, 0.05, 2.0)


# ---- 3: zero-fuel guards must not be masked by LP infeasibility -------------------------
@pytest.mark.parametrize("kw", [{"k": 0.0}, {"a_max": 0.0}])
def test_zero_burn_transfer_with_no_fuel_or_thrust_is_none(kw):
    free = propagate(SLOT0, T_S, N_MM)  # target already on the free trajectory: no burn needed
    args = {"a_max": 0.05, "k": 1.0, **kw}
    assert lp_transfer(SLOT0, free, T_S, N_MM, args["a_max"], args["k"], 12) is None
    assert lp_transfer(SLOT0, free, T_S, N_MM, 0.05, 1.0, 12) is not None  # control: feasible


def test_zero_fuel_mpc_step_none():
    assert mpc_step(SLOT0, target, 0.0, T_S, N_MM, 0.05, 0.0) is None


# ---- 5: landing post-check and solver failures --------------------------------------------
def _fake(monkeypatch, **res):
    monkeypatch.setattr(tf, "linprog", lambda *a, **k: SimpleNamespace(**res))


def test_status0_with_garbage_solution_is_rejected_by_the_landing_check(monkeypatch):
    _fake(monkeypatch, status=0, x=np.zeros(6 * 12))
    assert plan() is None


@pytest.mark.parametrize("status", [1, 2, 3, 4])
def test_nonzero_solver_status_is_none(monkeypatch, status):
    _fake(monkeypatch, status=status, x=np.ones(6 * 12) * 1e-3)
    assert plan() is None


@pytest.mark.parametrize("status", [1, 2, 3, 4])
def test_nonzero_status_is_none_even_when_x_is_a_valid_landing_plan(monkeypatch, status):
    real = tf.linprog
    monkeypatch.setattr(
        tf, "linprog", lambda *a, **k: SimpleNamespace(status=status, x=real(*a, **k).x)
    )
    assert plan() is None


def test_status0_with_x_none_is_none(monkeypatch):
    _fake(monkeypatch, status=0, x=None)
    assert plan() is None


@pytest.mark.parametrize("exc", [ValueError("bad"), FloatingPointError("fp"), RuntimeError("x")])
def test_linprog_exception_is_none_not_raise(monkeypatch, exc):
    def boom(*a, **k):
        raise exc

    monkeypatch.setattr(tf, "linprog", boom)
    assert plan() is None


def test_near_singular_transfer_is_none_or_landing_checked():
    T = PERIOD * (1.0 + 1e-6)
    xt = propagate(SLOT1, T, N_MM)
    tr = lp_transfer(SLOT0, xt, T, N_MM, 1e3, 1.0, 2)
    if tr is not None:
        resid = np.linalg.norm(propagate_plan(SLOT0, tr, N_MM) - xt)
        assert resid <= 1e-6 * max(1.0, np.linalg.norm(xt))


def test_overshoot_of_the_cap_is_clipped_and_relanded(monkeypatch):
    real = tf.linprog
    peak = float(np.abs(plan(N=12).dv).max())
    a_max = 0.8 * peak * math.sqrt(3.0) * 12 / T_S
    cap = a_max * (T_S / 12) / math.sqrt(3.0)

    def over(*a, **k):
        res = real(*a, **k)
        x = res.x.copy()
        i = int(np.argmax(x))
        x[i] += 1e-8  # HiGHS-style bound overshoot at the feasibility boundary
        return SimpleNamespace(status=res.status, x=x)

    monkeypatch.setattr(tf, "linprog", over)
    tr = plan(a_max=a_max)
    assert tr is not None and np.abs(tr.dv).max() <= cap
    assert np.linalg.norm(propagate_plan(SLOT0, tr, N_MM) - target(T_S)) < 1e-2


# ---- 12c: octahedron cap ------------------------------------------------------------------
def test_octahedron_cap_bounds_the_l1_norm_per_node_and_is_binding():
    free = plan(N=12, cap_shape="octahedron")
    peak = float(np.abs(free.dv).sum(axis=1).max())
    cap = 0.7 * peak
    a_max = cap * 12 / T_S
    tr = plan(a_max=a_max, cap_shape="octahedron")
    assert tr is not None
    assert np.abs(tr.dv).sum(axis=1).max() <= cap * (1 + 1e-7)
    assert np.abs(tr.dv).sum(axis=1).max() >= 0.99 * cap  # active
    assert np.linalg.norm(tr.dv, axis=1).max() <= cap * (1 + 1e-7)  # |dv|_2 <= |dv|_1


def test_octahedron_cap_rejects_a_node_whose_l1_exceeds_it():
    two = plan(N=2, cap_shape="octahedron")  # N = 2: the impulses are unique (no freedom)
    l1_max = float(np.abs(two.dv).sum(axis=1).max())
    comp_max = float(np.abs(two.dv).max())
    assert comp_max < 0.9 * l1_max  # more than one axis burns: a per-component bound is looser
    a_max = lambda cap: cap * 2 / T_S  # noqa: E731
    assert plan(N=2, a_max=a_max(0.9 * l1_max), cap_shape="octahedron") is None
    assert plan(N=2, a_max=a_max(1.001 * l1_max), cap_shape="octahedron") is not None


def test_box_is_the_default_and_unchanged():
    a, b = plan(), plan(cap_shape="box")
    assert a is not None and np.array_equal(a.dv, b.dv)


def test_octahedron_min_feasible_a_max_is_below_box():
    def min_a(shape):
        lo, hi = 1e-4, 0.1
        for _ in range(40):
            mid = math.sqrt(lo * hi)
            ok = lp_transfer(SLOT0, target(PERIOD), PERIOD, N_MM, mid, 1.0, 48, cap_shape=shape)
            lo, hi = (lo, mid) if ok else (mid, hi)
        return hi

    assert min_a("octahedron") < min_a("box")


# ---- dense position model equals hcw.stm --------------------------------------------------
def test_dense_positions_match_hcw_stm_propagation():
    tr = plan()
    ts = np.array([0.0, 1.0, 777.0, 2000.0, 3999.0, T_S])
    got = tf._plan_positions(SLOT0, tr, N_MM, ts)
    want = np.array([propagate_plan(SLOT0, tr, N_MM, t)[:3] for t in ts])
    assert np.max(np.abs(got - want)) < 1e-6


# ---- 1: keep-out is verified between samples ----------------------------------------------
def _true_min_distance(tr, ts, pos, lo, hi, step=0.25):
    grid = np.arange(lo, hi, step)
    mine = np.array([propagate_plan(SLOT0, tr, N_MM, t)[:3] for t in grid])
    obs = np.stack([np.interp(grid, ts, pos[:, i]) for i in range(3)], axis=1)
    return float(np.linalg.norm(mine - obs, axis=1).min())


def _free():
    free = plan()
    assert free is not None
    return free


def test_obstacle_crossing_between_widely_spaced_samples_is_avoided():
    free = _free()
    tc, w = 0.5 * T_S + 437.5, 1600.0
    ta, tb = tc - 30.0, tc + 30.0
    pa = propagate_plan(SLOT0, free, N_MM, ta)[:3]
    pb = propagate_plan(SLOT0, free, N_MM, tb)[:3]
    u = np.array([0.0, 0.0, 1.0])  # cross-track: sides far from the path at both samples
    ts, pos = np.array([ta, tb]), np.array([pa + w * u, pb - w * u])
    assert _true_min_distance(free, ts, pos, ta, tb) < 50.0  # the free plan does collide
    tr = plan(keepout=[(ts, pos, 500.0)])
    # on the 1 s verification grid the plan clears 500 m; between grid points the clearance can
    # shrink by at most v_rel * 0.5 s (v_rel ~ 55 m/s here)
    assert tr is not None and tr.min_clearance_m >= 500.0 - 1e-6
    assert _true_min_distance(tr, ts, pos, ta, tb) >= 500.0 - 0.5 * 80.0
    assert np.linalg.norm(propagate_plan(SLOT0, tr, N_MM) - target(T_S)) < 1e-5


def test_start_inside_the_keepout_is_infeasible():
    ts, pos = np.array([0.0, 100.0]), np.array([SLOT0[:3] + 100.0, SLOT0[:3] + 1e5])
    assert plan(keepout=[(ts, pos, 500.0)]) is None
    ts2, pos2 = np.array([-50.0, 100.0]), np.array([SLOT0[:3] + 100.0, SLOT0[:3] + 100.0])
    assert plan(keepout=[(ts2, pos2, 500.0)]) is None  # samples before t=0 are not ignored


def test_min_clearance_is_none_without_keepout_and_float_with():
    assert _free().min_clearance_m is None
    ts, pos = np.array([T_S / 2]), np.full((1, 3), 1e6)
    tr = plan(keepout=[(ts, pos, 500.0)])
    assert tr is not None and tr.min_clearance_m > 5e5


@pytest.mark.parametrize("offset", [1.0, 100.0])
@pytest.mark.parametrize("direction", [(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 1)])
@pytest.mark.parametrize("window", [(0.2, 0.4), (0.4, 0.6), (0.6, 0.8)])
def test_obstacle_nearly_on_the_path_still_solves(offset, direction, window):
    free = _free()
    ts = np.linspace(window[0] * T_S, window[1] * T_S, 12)
    d = np.array(direction, float)
    pos = np.array(
        [propagate_plan(SLOT0, free, N_MM, t)[:3] + offset * d / np.linalg.norm(d) for t in ts]
    )
    tr = plan(keepout=[(ts, pos, 4000.0)], a_max=0.05, N=24)
    assert tr is not None, "first-iterate normals must not produce a false None"
    assert tr.min_clearance_m >= 4000.0 - 1e-6


# ---- 10: cancel latency in the keep-out build ---------------------------------------------
class CountingEvent(threading.Event):
    def __init__(self, limit=None):
        super().__init__()
        self.calls, self.limit = 0, limit

    def is_set(self):
        self.calls += 1
        return self.limit is not None and self.calls > self.limit


def _crowded_keepout(m=3000):
    free = _free()
    ts = np.linspace(0.3 * T_S, 0.7 * T_S, m)
    pos = np.array([propagate_plan(SLOT0, free, N_MM, t)[:3] for t in ts[::50]])
    pos = np.repeat(pos, 50, axis=0)[:m] + 10.0
    return [(ts, pos, 300.0)]


def test_cancel_inside_a_large_keepout_build_is_prompt():
    ko = _crowded_keepout()
    ev = CountingEvent()
    plan(keepout=ko, cancel_event=ev, N=24)
    total = ev.calls
    assert total > 20  # checks happen inside the assembly loops, not just per solve
    ev2 = CountingEvent(limit=total // 2)
    with pytest.raises(TransferCancelled):
        plan(keepout=ko, cancel_event=ev2, N=24)
    assert ev2.calls <= total // 2 + 1


def test_cancel_set_between_sequential_iterations_stops_the_solve(monkeypatch):
    free = _free()
    ts = np.array([0.5 * T_S])  # one violated grid time: the build has a single chunk
    pos = np.array([propagate_plan(SLOT0, free, N_MM, 0.5 * T_S)[:3] + 5.0])
    ev, real, calls = threading.Event(), tf.linprog, []

    def spy(*a, **k):
        calls.append(1)
        ev.set()  # set while the first solve is running
        return real(*a, **k)

    monkeypatch.setattr(tf, "linprog", spy)
    with pytest.raises(TransferCancelled):
        plan(keepout=[(ts, pos, 1000.0)], cancel_event=ev)
    assert len(calls) == 1  # the second (constrained) solve never started


def test_cancel_preset_raises_even_for_zero_fuel_and_exhausted_mpc_horizon():
    ev = threading.Event()
    ev.set()
    with pytest.raises(TransferCancelled):
        plan(k=0.0, cancel_event=ev)
    with pytest.raises(TransferCancelled):
        mpc_step(SLOT0, target, T_S + 5.0, T_S, N_MM, 0.05, 1.0, cancel_event=ev)


def test_mpc_cancel_is_forwarded_to_the_solve():
    ev, calls = threading.Event(), []

    def fn(T):
        calls.append(T)
        ev.set()
        return target(T)

    with pytest.raises(TransferCancelled):
        mpc_step(SLOT0, fn, 100.0, T_S, N_MM, 0.05, 1.0, cancel_event=ev)


# ---- tie tolerance ------------------------------------------------------------------------
def test_best_transfer_ties_within_tolerance_prefer_the_shorter_T():
    free = lambda T: propagate(SLOT0, T, N_MM)  # noqa: E731
    best = best_transfer(SLOT0, free, N_MM, 0.05, 1.0, N=12)
    assert best.T_s == pytest.approx(0.5 * PERIOD)
    # a 1e-10 m/s difference is a tie, a 1e-6 one is not
    totals = iter([1.0 + 1e-10, 1.0])
    real = tf.lp_transfer

    def fake(*a, **k):
        t = real(*a, **k)
        t.total_dv_mps = next(totals, 5.0)
        return t

    import unittest.mock as mock

    with mock.patch.object(tf, "lp_transfer", fake):
        assert best_transfer(SLOT0, free, N_MM, 0.05, 1.0, N=12).T_s == pytest.approx(0.5 * PERIOD)
    totals = iter([1.0 + 1e-6, 1.0])
    with mock.patch.object(tf, "lp_transfer", fake):
        assert best_transfer(SLOT0, free, N_MM, 0.05, 1.0, N=12).T_s == pytest.approx(PERIOD)


# ---- keep-out through MPC: obstacle times are plan-start based and get shifted ------------
def test_mpc_keepout_times_are_shifted_by_elapsed_time():
    free = lp_transfer(SLOT0, target(PERIOD), PERIOD, N_MM, 0.01, 1.0, 48)
    t_e = 1200.0
    x = propagate_plan(SLOT0, free, N_MM, t_e)
    t_obs = 3000.0  # plan-start time; a fresh plan from x sees it at t_obs - t_e
    p_obs = propagate_plan(SLOT0, free, N_MM, t_obs)[:3] + 3.0
    ko = [(np.array([t_obs]), p_obs[None, :], 800.0)]
    fix = mpc_step(x, target, t_e, PERIOD, N_MM, 0.01, 1.0, 48, keepout=ko)
    assert fix is not None
    pos_at_obs = propagate_plan(x, fix, N_MM, t_obs - t_e)[:3]
    assert np.linalg.norm(pos_at_obs - p_obs) >= 800.0 - 1e-6
    assert fix.min_clearance_m >= 800.0 - 1e-6


# ---- 2: MPC keeps the per-interval cap when the horizon shrinks ----------------------------
def _open_loop():
    pl = lp_transfer(SLOT0, target(PERIOD), PERIOD, N_MM, 0.01, 1.0, 48)
    assert pl is not None
    return pl


def test_mpc_on_plan_state_stays_feasible_at_every_resolve_time():
    pl = _open_loop()
    for t_e in np.arange(120.0, PERIOD - 300.0, 120.0):
        x = propagate_plan(SLOT0, pl, N_MM, float(t_e))
        fix = mpc_step(x, target, float(t_e), PERIOD, N_MM, 0.01, 1.0, 48)
        remaining = float(np.abs(pl.dv[pl.times > t_e]).sum())
        assert fix is not None, f"None at t_elapsed={t_e}"
        assert fix.total_dv_mps <= remaining + 1e-6


def _closed_loop(noise_pos, noise_vel, seed=3, period_s=120.0):
    rng = np.random.default_rng(seed)
    pl = _open_loop()
    x, spent, none_count, t = SLOT0.copy(), 0.0, 0, 0.0
    cur = pl
    while t + period_s < PERIOD - 300.0:
        x = propagate_plan(x, cur, N_MM, period_s)
        spent += float(np.abs(cur.dv[cur.times <= period_s]).sum())
        t += period_s
        x = x + np.concatenate([rng.normal(0, noise_pos, 3), rng.normal(0, noise_vel, 3)])
        fix = mpc_step(x, target, t, PERIOD, N_MM, 0.01, 1.0, 48)
        if fix is None:
            none_count += 1
            cur = Transfer(cur.dv[:0], cur.times[:0], 0.0, PERIOD - t, 1)
        else:
            cur = fix
    xf = propagate_plan(x, cur, N_MM)
    spent += float(np.abs(cur.dv).sum())
    return none_count, spent, float(np.linalg.norm(xf[:3] - target(PERIOD)[:3]))


def test_mpc_closed_loop_zero_noise_matches_the_open_loop_plan():
    nones, spent, err = _closed_loop(0.0, 0.0)
    assert nones == 0 and err < 1e-3
    assert spent == pytest.approx(_open_loop().total_dv_mps, rel=1e-3)


def test_mpc_closed_loop_with_seeded_noise_stays_close_and_never_fails():
    nones, spent, err = _closed_loop(1.0, 1e-3)
    assert nones == 0 and err < 20.0


def test_keepout_assembly_loop_checks_cancel_between_chunks(monkeypatch):
    real = tf._plan_positions
    monkeypatch.setattr(tf, "_plan_positions", lambda *a, **k: real(*a[:4]))  # no checks there
    ko = _crowded_keepout()
    ev = CountingEvent()
    assert plan(keepout=ko, cancel_event=ev, N=24) is not None
    assert ev.calls >= 3  # entry + at least two chunk boundaries inside the row build
    ev2 = CountingEvent(limit=2)
    with pytest.raises(TransferCancelled):
        plan(keepout=ko, cancel_event=ev2, N=24)
