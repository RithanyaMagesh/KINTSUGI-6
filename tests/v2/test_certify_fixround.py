"""Phase 5d fix round: reviewer false-pass repros (P0/P1/P2) and mutation survivors, as tests.

Every reviewer repro here once returned passed=True (or hung); each now fails with the named
reason. dt_s 10 keeps most of them fast (the physics does not depend on it)."""

from __future__ import annotations

import threading

import numpy as np
import pytest
from certify_fixtures import N_MM, PERIOD, engine_at, scn, slots

from cubesat import truth
from cubesat.certify import Plan, PlanItem, certify, swarm_state_from_engine
from cubesat.certify_sim import CertificateCancelled, simulate
from cubesat.hcw import propagate, stm
from cubesat.spacecraft import G0, SatState
from cubesat.transfer import Transfer, lp_transfer, propagate_plan

TINY = 1e-6  # d_safe_m must be > 0
FAST = {"horizon_orbits": 0.1}


def kinds(cert):
    return sorted({r.split(":")[0] for r in cert.reasons})


def burn(*dvs, times=None) -> Transfer:
    dv = np.array(dvs, dtype=float)
    t = np.arange(len(dvs)) * 100.0 if times is None else np.array(times, dtype=float)
    return Transfer(dv, t, float(np.abs(dv).sum()), float(t[-1]), 1)


def tank(m=4.0, prop=0.2):
    return 40.0 * G0 * np.log(m / (m - prop))


def seat_t0(state, i):  # the sat's current seat in the formation t = 0 convention
    return propagate(state.refs[i], -state.t_s, N_MM)


# ---- P0-1 / P0-2: a sat that does not reach its seat is not certified ---------------------
@pytest.mark.parametrize("y", [4000.0, 8000.0])
def test_hold_item_with_a_far_seat_fails_settled(y):
    sc = scn(2.0, dt_s=10.0)
    st = swarm_state_from_engine(engine_at(sc, 2))
    item = PlanItem(1, None, np.array([0, y, 0, 0, 0, 0.0]), tuple(st.roles[1]))
    c = certify(Plan((item,), "far", st.t_s), st, sc, d_safe_m=TINY, coverage_floor=0.0)
    print(f"\nhold item y={y:.0f}: settled error {c.settled_error_m / 1000:.0f} km, {kinds(c)}")
    assert not c.passed and "settled" in kinds(c) and c.settled_error_m > 1000.0


def test_thruster_out_sat_with_a_far_hold_seat_fails_and_earns_no_coverage():
    sc = scn(2.0, dt_s=10.0, failures=[{"t": 0.0, "sat_id": 1, "mode": "THRUSTER_OUT"}])
    st = swarm_state_from_engine(engine_at(sc, 2))
    item = PlanItem(1, None, np.array([0, 14000.0, 0, 0, 0, 0.0]), tuple(st.roles[1]))
    c = certify(Plan((item,), "far", st.t_s), st, sc, d_safe_m=TINY)
    assert not c.passed and {"settled", "coverage"} <= set(kinds(c))
    assert c.coverage < c.hold_coverage - 1e-3  # an unreachable seat is not credited


def test_stuck_open_sat_fails_as_a_hold_and_with_a_tiny_mover_plan():
    sc = scn(2.0, dt_s=10.0, failures=[{"t": 0.0, "sat_id": 2, "mode": "THRUSTER_STUCK_OPEN"}])
    st = swarm_state_from_engine(engine_at(sc, 3))
    hold = certify(Plan((), "hold", st.t_s), st, sc, d_safe_m=TINY)
    assert not hold.passed and {"settled", "fuel"} <= set(kinds(hold))
    assert any("runs out" in r for r in hold.reasons)
    mover = PlanItem(2, burn([1e-6, 0, 0], times=[0.0]), seat_t0(st, 2), ("imager",))
    c = certify(Plan((mover,), "tiny", st.t_s), st, sc, d_safe_m=TINY)
    assert not c.passed and "settled" in kinds(c)


# ---- P0-3: the fuel check judges the flown tank --------------------------------------------------
def test_flown_tank_below_the_reserve_fails_even_when_the_planned_sum_fits():
    sc = scn(8.0, a_max_mps2=0.01)  # the reviewer's 8 km CW plan: planned 14.1 of 20.12 m/s
    st = swarm_state_from_engine(engine_at(sc, 0))
    s = slots(8.0)
    tr = lp_transfer(s[0], propagate(s[1], PERIOD, N_MM), PERIOD, N_MM, 0.01, 1.0, 48)
    plan = Plan((PlanItem(0, tr, s[1], ("leader",)),), "x", 0.0)
    c = certify(plan, st, sc, d_safe_m=TINY, landing_tol_m=1e6, coverage_floor=0.0)
    assert c.planned_fuel_margin_mps == pytest.approx(0.8 * tank() - tr.l2_dv_mps)
    assert c.planned_fuel_margin_mps > 1.0  # the old check said "+2 m/s" and passed
    assert c.worst_fuel_margin_mps < -2.0 and c.worst_fuel_sat == 0
    assert any(r.startswith("fuel") and "would end" in r for r in c.reasons) and not c.passed


def test_worst_fuel_margin_is_the_smaller_of_planned_and_flown():
    sc = scn(2.0, dt_s=10.0)
    st = swarm_state_from_engine(engine_at(sc, 0))
    plan = Plan((PlanItem(0, burn([0.3, 0, 0]), slots(2.0)[0], ("leader",)),), "x", 0.0)
    c = certify(plan, st, sc, d_safe_m=TINY, landing_tol_m=1e6, coverage_floor=0.0)
    res = simulate(sc, st, np.array(st.refs), {0: plan.items[0].transfer}, round(2 * PERIOD / 10.0))
    flown = [
        f.fuel_mps_left - 0.2 * i.fuel_mps_left
        for f, i in zip(res.final_sats, st.sats, strict=True)
    ]
    assert c.worst_fuel_margin_mps == pytest.approx(min(min(flown), c.planned_fuel_margin_mps))
    assert c.worst_fuel_sat == int(np.argmin(flown))
    assert c.worst_fuel_margin_mps <= c.planned_fuel_margin_mps


def test_a_sat_that_runs_dry_fails_even_with_no_reserve():
    sc = scn(2.0, dt_s=10.0, spacecraft={"m_prop_kg": 0.01})  # 0.98 m/s tank
    st = swarm_state_from_engine(engine_at(sc, 0))
    plan = Plan((PlanItem(0, burn([0.5, 0, 0]), slots(2.0)[0], ("leader",)),), "x", 0.0)
    c = certify(plan, st, sc, d_safe_m=TINY, fuel_reserve=0.0, landing_tol_m=1e6)
    assert not [r for r in c.reasons if "needs" in r]  # 0.5 of 0.98 m/s fits statically
    assert any("runs out" in r for r in c.reasons) and not c.passed


# ---- P0-4: the horizon is never shorter than two orbits (and covers the plan) -------------
def test_a_short_horizon_cannot_pass():
    sc = scn(2.0, dt_s=10.0)
    st = swarm_state_from_engine(engine_at(sc, 0))
    short = certify(Plan((), "hold", 0.0), st, sc, d_safe_m=500.0, horizon_orbits=1.0)
    assert not short.passed and kinds(short) == ["horizon"]
    assert short.horizon_s == pytest.approx(PERIOD, abs=10.0)  # reports what was simulated
    full = certify(Plan((), "hold", 0.0), st, sc, d_safe_m=500.0)
    assert full.passed and full.horizon_s == pytest.approx(2 * PERIOD, abs=10.0)


def test_horizon_extends_one_orbit_past_the_plan_end_and_reports_it():
    sc = scn(2.0, dt_s=10.0)
    st = swarm_state_from_engine(engine_at(sc, 0))
    t_last = 2.5 * PERIOD
    tr = burn([1e-6, 0, 0], [1e-6, 0, 0], times=[0.0, t_last])
    plan = Plan((PlanItem(0, tr, slots(2.0)[0], ("leader",)),), "x", 0.0)
    c = certify(plan, st, sc, d_safe_m=TINY)
    last = int(t_last // 10.0) + 1  # the last node, one step of burn
    assert c.horizon_s == (last + round(PERIOD / 10.0)) * 10.0
    assert c.horizon_s > 3.4 * PERIOD


# ---- P1-1: nothing hangs or exhausts memory ------------------------------------------------------
def _timeout_event(seconds=60.0):
    ev = threading.Event()
    t = threading.Timer(seconds, ev.set)
    t.daemon = True
    t.start()
    return ev


def test_huge_inputs_fail_fast_instead_of_simulating_for_decades():
    sc = scn(2.0, dt_s=10.0)
    s = slots(2.0)
    base = swarm_state_from_engine(engine_at(sc, 0))

    def run(tr, state=base, **kw):
        plan = Plan((PlanItem(1, tr, s[1], ("imager",)),), "x", 0.0)
        return certify(plan, state, sc, d_safe_m=TINY, cancel_event=_timeout_event(), **kw)

    with pytest.raises(ValueError, match="orbits"):
        run(burn([1e-6, 0, 0], [1e-6, 0, 0], times=[0, 1e9]))
    c = run(burn([1e4, 0, 0], times=[0.0]))  # 1e4 m/s: fails the static fuel check, never flown
    assert not c.passed and any("needs" in r for r in c.reasons)
    assert c.horizon_s == pytest.approx(2 * PERIOD, abs=10.0)
    weak = swarm_state_from_engine(engine_at(sc, 0))
    weak.sats[1].k = 1e-9  # a burn that would take ~1e8 steps
    c = run(burn([0.1, 0, 0], times=[0.0]), weak)
    assert not c.passed and any(r.startswith("fuel") and "steps" in r for r in c.reasons)
    with pytest.raises(ValueError, match="steps"):
        certify(Plan((), "x", 0.0), base, sc, d_safe_m=TINY, horizon_orbits=1e6)


@pytest.mark.parametrize(
    ("field", "value"),
    [("k", 50.0), ("k", -0.1), ("m_prop_kg", -0.1), ("m_prop_kg", 4.0), ("m_prop_kg", 5.0),
     ("f_max_n", -1.0), ("f_max_n", 0.0), ("isp_s", 0.0), ("m_kg", 0.0)],
)
def test_nonphysical_sat_state_raises_value_error(field, value):
    sc = scn(2.0, dt_s=10.0)
    st = swarm_state_from_engine(engine_at(sc, 0))
    setattr(st.sats[1], field, value)
    with pytest.raises(ValueError, match="SatState"):
        certify(Plan((), "x", 0.0), st, sc, d_safe_m=TINY, **FAST)


def test_zero_d_safe_and_bad_times_raise_value_error():
    sc = scn(2.0, dt_s=10.0)
    st = swarm_state_from_engine(engine_at(sc, 0))
    with pytest.raises(ValueError, match="d_safe_m"):
        certify(Plan((), "x", 0.0), st, sc, d_safe_m=0.0, **FAST)
    bad = Transfer(np.array([[1.0, 0, 0]]), ["a"], 1.0, 0.0, 1)
    with pytest.raises(ValueError, match="transfer"):
        plan = Plan((PlanItem(1, bad, slots(2.0)[1], ()),), "x", 0.0)
        certify(plan, st, sc, d_safe_m=TINY, **FAST)
    listy = Transfer([[1e-6, 0, 0]], [0.0], 1e-6, 0.0, 1)  # plain lists are coerced
    certify(Plan((PlanItem(1, listy, slots(2.0)[1], ()),), "x", 0.0), st, sc, d_safe_m=TINY, **FAST)


def test_bool_sat_id_is_rejected():
    sc = scn(2.0, dt_s=10.0)
    st = swarm_state_from_engine(engine_at(sc, 0))
    with pytest.raises(ValueError, match="int"):
        certify(Plan((PlanItem(True, None, slots(2.0)[1], ()),), "x", 0.0), st, sc,
                d_safe_m=TINY, **FAST)


# ---- P2 ------------------------------------------------------------------------------------------
def _roles_cert(items, state=None, sc=None):
    sc = sc or scn(2.0, dt_s=10.0)
    state = state or swarm_state_from_engine(engine_at(sc, 0))
    s = slots(2.0)
    plan = Plan(tuple(PlanItem(i, None, s[i], tuple(r)) for i, r in items.items()), "x", 0.0)
    return certify(plan, state, sc, d_safe_m=TINY, coverage_floor=0.0, **FAST)


def test_two_holders_of_a_single_seat_role_fail():
    c = _roles_cert({0: ["leader"], 1: ["leader"], 5: ["downlink"], 4: ["downlink"], 2: ["imager"]})
    assert not c.roles_ok and any("held by sats" in r for r in c.reasons)


def test_stacking_non_stackable_roles_fails_while_a_free_capable_sat_exists():
    c = _roles_cert({0: ["leader", "downlink", "imager"], 5: []})
    assert not c.roles_ok and any("stack" in r for r in c.reasons)
    ok = _roles_cert({0: ["leader"], 5: ["downlink"], 1: ["imager"], 2: ["imager"]})
    assert ok.roles_ok  # a stackable leader on an imager sat is fine
    assert _roles_cert({0: ["leader", "imager"], 5: ["downlink"]}).roles_ok


def test_plan_item_for_a_dead_sat_is_reported_as_a_note_not_a_failure():
    sc = scn(2.0, dt_s=10.0, failures=[{"t": 0.0, "sat_id": 4, "mode": "DEAD"}])
    st = swarm_state_from_engine(engine_at(sc, 30))
    base = certify(Plan((), "h", st.t_s), st, sc, d_safe_m=500.0)
    far = PlanItem(4, None, np.array([0, 9000.0, 0, 0, 0, 0.0]), ())
    c = certify(Plan((far,), "h", st.t_s), st, sc, d_safe_m=500.0)
    assert base.notes == [] and any("sat 4" in n and "DEAD" in n for n in c.notes)
    assert c.passed == base.passed and c.reasons == base.reasons
    assert c.event_payload()["reasons"] == base.event_payload()["reasons"]


def test_engine_hold_is_copied_into_the_state_and_used():
    sc = scn(2.0, dt_s=10.0, chief={"altitude_km": 165.0}, duration_s=30000.0,
             failures=[{"t": 0.0, "sat_id": 1, "mode": "DEAD"}], truth={"density_factor": 20})
    eng = engine_at(sc, 0)
    while "REENTERED" not in eng.status:
        eng.step()
    for _ in range(50):
        eng.step()
    st = swarm_state_from_engine(eng)
    assert np.array_equal(st.hold, eng.hold) and np.abs(st.hold[1]).max() > 1e3
    st.hold[:] = 5.0
    assert not np.array_equal(st.hold, eng.hold)  # a copy
    st = swarm_state_from_engine(eng)
    res = simulate(sc, st, st.refs, {}, 0)
    assert 1 not in res.min_sep_pair


def test_coverage_estimate_copy_equals_the_allocator_function():
    from cubesat.allocate import _coverage_estimate
    from cubesat.certify_sim import coverage_estimate
    from cubesat.coverage import footprint_radius, target_grid

    sc = scn(2.0)
    rng = np.random.default_rng(3)
    seats = [s + rng.normal(0, 300.0, 6) * [1, 1, 1, 0, 0, 0] for s in slots(2.0)]
    grid, r_f = target_grid(2000.0, 20000.0), footprint_radius(500e3, np.radians(1.5))
    for imagers in ([1, 2, 4], [0], []):
        labels = ["imager" if i in imagers else "-" for i in range(6)]
        want = _coverage_estimate(seats, labels, r_f=r_f, grid=grid, n=N_MM, t_replan=0.0)
        assert coverage_estimate(seats, imagers, r_f=r_f, grid=grid, n=N_MM) == want
    assert sc.sensor.grid_step_km == 2.0


# ---- survivors ----------------------------------------------------------------------------
def _impulsive_plan(dt=10.0, f_max=4.0):
    """Sat 0 slot 0 -> a free spot 6 km along track (no sat near it), 4 N thrusters."""
    sc = scn(2.0, dt_s=dt, spacecraft={"f_max_n": f_max})
    st = swarm_state_from_engine(engine_at(sc, 0))
    seat = np.array([0.0, 6000.0, 0.0, 0.0, 0.0, 0.0])
    tr = lp_transfer(slots(2.0)[0], propagate(seat, PERIOD, N_MM), PERIOD, N_MM, 1.0, 1.0, 48)
    return sc, st, Plan((PlanItem(0, tr, seat, ("leader",)),), "x", 0.0)


def test_a_landing_only_failure_makes_passed_false():
    sc, st, plan = _impulsive_plan()
    c = certify(plan, st, sc, d_safe_m=TINY, landing_tol_m=1.0)
    assert kinds(c) == ["landing"] and not c.passed and c.landing_error_m > 1.0


def test_boundaries_are_inclusive():
    sc, st, plan = _impulsive_plan()
    c = certify(plan, st, sc, d_safe_m=TINY)
    at = certify(plan, st, sc, d_safe_m=TINY, landing_tol_m=c.landing_error_m)
    assert not [r for r in at.reasons if r.startswith("landing")]
    h = certify(Plan((), "h", 0.0), st, sc, d_safe_m=TINY)
    at = certify(Plan((), "h", 0.0), st, sc, d_safe_m=h.min_sep_m)
    assert not [r for r in at.reasons if r.startswith("separation")]


def test_planned_fuel_is_the_l2_sum_and_a_mover_that_cannot_move_counts_minus_planned():
    sc = scn(2.0, dt_s=10.0)
    st = swarm_state_from_engine(engine_at(sc, 0))
    plan = Plan((PlanItem(1, burn([0.3, 0.4, 0.0]), slots(2.0)[1], ("imager",)),), "x", 0.0)
    c = certify(plan, st, sc, d_safe_m=TINY, **FAST)  # L2 = 0.5, L1 = 0.7
    assert c.planned_fuel_margin_mps == pytest.approx(0.8 * tank() - 0.5, abs=1e-9)
    st.sats[1].k = 0.0
    c = certify(Plan((PlanItem(1, burn([0.01, 0, 0]), slots(2.0)[1], ()),), "x", 0.0), st, sc,
                d_safe_m=TINY, **FAST)
    assert c.planned_fuel_margin_mps == pytest.approx(-0.01, abs=1e-12)


def test_cancel_latency_is_one_step(monkeypatch):
    sc = scn(2.0)
    st = swarm_state_from_engine(engine_at(sc, 0))
    ev, calls, orig = threading.Event(), [0], truth.rk4_step

    def spy(*a, **k):
        calls[0] += 1
        if calls[0] == 30:
            ev.set()
        return orig(*a, **k)

    monkeypatch.setattr(truth, "rk4_step", spy)
    with pytest.raises(CertificateCancelled):
        certify(Plan((), "h", 0.0), st, sc, d_safe_m=TINY, cancel_event=ev)
    assert calls[0] == 30  # stopped at the next step, not 100 steps later


def test_burn_schedule_overlapping_nodes_add_and_k_scales_the_step_count():
    from cubesat.certify_sim import burn_schedule

    dt = 2.0
    sat = SatState()  # 4 kg, F_max 0.04 N: 0.02 m/s per 2 s step at k = 1
    tr = burn([0.2, 0, 0], [0.0, 0.1, 0.0], times=[0.0, 10.0])  # node 2 starts inside node 1
    b, last = burn_schedule({0: tr}, [sat], dt)[0]
    assert np.allclose(b.sum(axis=0) * dt, [0.2, 0.1, 0.0], atol=1e-12)  # impulses add
    assert (b[:, 0] != 0).sum() == 10 and (b[:, 1] != 0).sum() == 5 and last == 10
    assert b[5, 0] > 0 and b[5, 1] > 0  # the overlap step carries both
    half = SatState(k=0.5)
    b2, last2 = burn_schedule({0: burn([0.2, 0, 0], times=[0.0])}, [half], dt)[0]
    assert (b2[:, 0] != 0).sum() == 20 and last2 == 20
    assert np.allclose(b2.sum(axis=0) * dt, [0.2, 0, 0], atol=1e-12)


def test_landing_error_is_the_worst_mover_not_the_best():
    sc = scn(2.0, dt_s=10.0, spacecraft={"f_max_n": 4.0})
    st = swarm_state_from_engine(engine_at(sc, 0))
    s = slots(2.0)
    items = []
    for i, j in ((0, 1), (3, 4)):
        tr = lp_transfer(s[i], propagate(s[j], PERIOD, N_MM), PERIOD, N_MM, 1.0, 1.0, 48)
        items.append(PlanItem(i, tr, s[j], tuple(st.roles[i])))
    c = certify(Plan(tuple(items), "x", 0.0), st, sc, d_safe_m=TINY, landing_tol_m=1e6)
    seats = np.array(st.refs)
    for it in items:
        seats[it.sat_id] = propagate(it.seat, 0.0, N_MM)
    movers = {it.sat_id: it.transfer for it in items}
    res = simulate(sc, st, seats, movers, round(2 * PERIOD / 10.0))
    errs = sorted(res.landing_m.values())
    assert len(errs) == 2 and errs[1] - errs[0] > 1.0
    assert c.landing_error_m == pytest.approx(errs[1])


def test_collision_in_the_middle_of_a_transfer_is_found():
    sc = scn(2.0, dt_s=10.0, spacecraft={"f_max_n": 4.0})
    st = swarm_state_from_engine(engine_at(sc, 0))
    s = slots(2.0)
    T, seat = PERIOD / 2.0, np.array([0.0, 6000.0, 0.0, 0.0, 0.0, 0.0])  # a free spot
    tr = lp_transfer(s[0], propagate(seat, T, N_MM), T, N_MM, 1.0, 1.0, 24)
    mid = propagate_plan(s[0], tr, N_MM, t_end=T / 2.0)
    x3 = stm(-T / 2.0, N_MM) @ (mid + np.array([300.0, 0, 0, 0, 0, 0]))  # sat 3 waits on the path
    r, v = truth.lvlh_to_eci(x3, st.chief[:3], st.chief[3:])
    st.sat_eci[3], st.refs[3] = np.concatenate([r, v]), x3
    plan = Plan((PlanItem(0, tr, seat, ("leader",)),), "x", 0.0)
    c = certify(plan, st, sc, d_safe_m=1000.0, landing_tol_m=1e6, coverage_floor=0.0)
    assert set(c.min_sep_pair) == {0, 3} and c.min_sep_m < 600.0
    assert abs(c.min_sep_t_s - T / 2.0) < 600.0  # mid-transfer, long before the plan end
    assert any(r.startswith("separation") for r in c.reasons)


def test_stepper_follows_scenario_gains_and_a_max_like_the_engine():
    """Sats start 200 m off their seats, so the PD (gains, saturation) does the work."""
    from cubesat.sim_v2 import EngineV2

    sc = scn(2.0, gains={"wn": 0.03, "zeta": 0.6}, a_max_mps2=0.002)
    start = np.array(slots(2.0))
    start[:, :3] += 200.0
    eng = EngineV2(sc, initial_lvlh=start)
    st = swarm_state_from_engine(eng)
    res = simulate(sc, st, st.refs, {}, 300)
    for _ in range(300):
        eng.step()
    assert np.abs(res.final_eci - eng.X).max() < 1e-6


def test_a_live_sat_that_re_enters_during_the_horizon_fails():
    """Chief at 165 km under a x200 storm: drag exceeds a_max, the active sats cannot hold, one
    falls below 100 km. A re-entry of a live sat is a failure ('settled'), not an exclusion."""
    sc = scn(2.0, dt_s=10.0, chief={"altitude_km": 165.0}, truth={"density_factor": 200})
    st = swarm_state_from_engine(engine_at(sc, 0))
    res = simulate(sc, st, st.refs, {}, round(2 * 5200.0 / 10.0))
    assert "REENTERED" in res.final_status  # the premise
    c = certify(Plan((), "hold", 0.0), st, sc, d_safe_m=TINY)
    assert not c.passed and "settled" in kinds(c)
    gone = [i for i, s in enumerate(res.final_status) if s == "REENTERED"]
    assert any(f"sat {i} is" in r and r.startswith("settled") for i in gone for r in c.reasons)


@pytest.mark.slow
def test_slow_dead_sat_drift_is_invisible_at_two_orbits_and_visible_later():
    """Known limit (docs/PHYSICS_V2.md): dead sat 1, x10 density, psi 30, 2 km. Two orbits show
    2419 m; 4.19 orbits show 615 m (and still falling). The ladder must re-certify each replan
    and may pass a longer horizon."""
    sc = scn(2.0, failures=[{"t": 0.0, "sat_id": 1, "mode": "DEAD"}], truth={"density_factor": 10},
             formation={"n_slots": 6, "radial_amp_km": 2.0, "cross_track_phase_deg": 30.0})
    st = swarm_state_from_engine(engine_at(sc, 10, psi_deg=30.0))
    two = certify(Plan((), "hold", st.t_s), st, sc, d_safe_m=500.0)
    long = certify(Plan((), "hold", st.t_s), st, sc, d_safe_m=500.0, horizon_orbits=4.19)
    print(f"\nx10 psi 30: {two.min_sep_m:.1f} m at 2 orbits, {long.min_sep_m:.1f} m at 4.19")
    assert two.min_sep_m == pytest.approx(2419.1, abs=1.0)
    assert long.min_sep_m == pytest.approx(614.8, abs=1.0) and long.min_sep_pair == (1, 2)


def test_a_coverage_only_failure_makes_passed_false():
    sc = scn(2.0, dt_s=10.0)
    st = swarm_state_from_engine(engine_at(sc, 0))
    s = slots(2.0)
    items = (PlanItem(4, None, s[4], ("spare",)),)  # same seat, imager role dropped
    c = certify(Plan(items, "drop", 0.0), st, sc, d_safe_m=TINY)
    assert kinds(c) == ["coverage"] and not c.passed


def test_settled_error_between_the_tolerance_and_kilometres_fails():
    """A THRUSTER_OUT sat asked to hold a seat 300 m off its own coasts on its own orbit: it ends
    hundreds of metres from the seat, far below the 5 km a loose tolerance would accept."""
    sc = scn(2.0, dt_s=10.0, failures=[{"t": 0.0, "sat_id": 1, "mode": "THRUSTER_OUT"}])
    st = swarm_state_from_engine(engine_at(sc, 2))
    seat = seat_t0(st, 1) + np.array([0.0, 300.0, 0.0, 0.0, 0.0, 0.0])
    plan = Plan((PlanItem(1, None, seat, tuple(st.roles[1])),), "x", st.t_s)
    c = certify(plan, st, sc, d_safe_m=TINY, coverage_floor=0.0)
    assert 100.0 < c.settled_error_m < 5000.0 and "settled" in kinds(c) and not c.passed
