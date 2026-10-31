"""Phase 5d-1: each of the five certificate checks can fail, alone and together."""

from __future__ import annotations

import json
import math
import threading

import numpy as np
import pytest
from certify_fixtures import N_MM, PERIOD, engine_at, scn, slots

from cubesat.certify import (
    Certificate,
    CertificateCancelled,
    Plan,
    PlanItem,
    certify,
    swarm_state_from_engine,
)
from cubesat.hcw import propagate
from cubesat.spacecraft import G0
from cubesat.transfer import Transfer, lp_transfer

FAST = {"horizon_orbits": 0.1}  # checks that do not depend on the horizon stay quick


def hold(state) -> Plan:
    return Plan((), "hold", state.t_s)


def burn(*dvs, times=None) -> Transfer:
    dv = np.array(dvs, dtype=float)
    t = np.arange(len(dvs)) * 100.0 if times is None else np.array(times, dtype=float)
    return Transfer(dv, t, float(np.abs(dv).sum()), float(t[-1]), 1)


def mover(i, tr, amp=2.0, roles=("imager",), seat=None) -> PlanItem:
    return PlanItem(i, tr, slots(amp)[i] if seat is None else seat, tuple(roles))


def reasons_of(cert, prefix):
    return [r for r in cert.reasons if r.startswith(prefix)]


# ---- 1. healthy hold + separation ----------------------------------------------------------------
def test_hold_plan_passes_on_a_healthy_2km_formation():
    sc = scn(2.0, formation={"n_slots": 6, "radial_amp_km": 2.0, "cross_track_phase_deg": 30.0})
    eng = engine_at(sc, 0, psi_deg=30.0)
    state = swarm_state_from_engine(eng)
    cert = certify(hold(state), state, sc, d_safe_m=500.0)
    print(f"\nhealthy 2 km psi 30: min sep {cert.min_sep_m:.3f} m at {cert.min_sep_t_s:.0f} s, "
          f"coverage {cert.coverage:.5f}, hold {cert.hold_coverage:.5f}")
    assert cert.passed and cert.reasons == [] and cert.roles_ok and cert.vacant_roles == []
    assert cert.horizon_s == pytest.approx(2.0 * PERIOD, abs=sc.dt_s)
    assert cert.min_sep_m == pytest.approx(2589.96, abs=0.5)  # pinned, measured
    assert cert.coverage == cert.hold_coverage == pytest.approx(0.42353, abs=1e-3)  # pinned
    assert cert.landing_error_m == 0.0 and cert.planned_fuel_margin_mps == 0.0
    assert cert.worst_fuel_sat is not None and cert.worst_fuel_margin_mps > 0.0  # flown tank


@pytest.mark.slow
def test_hold_coverage_agrees_with_the_engine_logged_coverage():
    sc = scn(2.0)
    eng = engine_at(sc, 0)
    state = swarm_state_from_engine(eng)
    cert = certify(hold(state), state, sc, d_safe_m=500.0, horizon_orbits=1.0)
    steps = round(PERIOD / sc.dt_s)
    logged = np.mean([eng.step()["coverage"] for _ in range(steps)])
    print(f"\nengine logged coverage over one orbit {logged:.4f}, certificate {cert.coverage:.4f}")
    assert cert.coverage == pytest.approx(logged, abs=0.02)


DRAG_CASES = [(0.0, 427.0, False), (30.0, 300.0, False), (90.0, 1536.0, True)]


@pytest.mark.slow
@pytest.mark.parametrize(("psi", "expected_sep", "passes"), DRAG_CASES)
def test_separation_fails_when_a_dead_sat_drifts_through_a_slot(psi, expected_sep, passes):
    """A dead sat (drag area 0.035 vs 0.010 m^2) under a x130 density storm drifts along track
    through its neighbours' slots. Measured min separations (d_safe 500 m): psi 0 -> 426.8 m,
    psi 30 -> 300.4 m (no better), psi 90 -> 1536.4 m. The engine, run by itself for the same
    horizon from the same state, reports the same number to 1 m."""
    sc = scn(
        2.0,
        failures=[{"t": 0.0, "sat_id": 1, "mode": "DEAD"}],
        truth={"density_factor": 130},
        formation={"n_slots": 6, "radial_amp_km": 2.0, "cross_track_phase_deg": psi},
    )
    eng = engine_at(sc, 10, psi_deg=psi)
    state = swarm_state_from_engine(eng)
    cert = certify(hold(state), state, sc, d_safe_m=500.0)
    steps = round(cert.horizon_s / sc.dt_s)
    engine_sep = min(eng.step()["min_sep"] for _ in range(steps + 1))
    print(f"\npsi {psi:>4}: certificate {cert.min_sep_m:.2f} m, engine {engine_sep:.2f} m, "
          f"pair {cert.min_sep_pair} at {cert.min_sep_t_s:.0f} s")
    assert abs(cert.min_sep_m - engine_sep) < 1.0
    assert cert.min_sep_m == pytest.approx(expected_sep, abs=2.0)
    assert 1 in cert.min_sep_pair  # the dead sat is one of the two
    assert 1000.0 < cert.min_sep_t_s < cert.horizon_s - 1000.0  # mid-horizon, not an end state
    assert (reasons_of(cert, "separation") == []) == passes
    assert cert.passed == passes


def test_dead_sats_are_not_ignored_and_the_minimum_is_over_the_horizon():
    """Dead sat 1 parked 100 m from live sat 0, then drifting away: the minimum is the START
    (not the end state), and only counting the dead sat can find it."""
    sc = scn(2.0, failures=[{"t": 0.0, "sat_id": 1, "mode": "DEAD"}])
    eng = engine_at(sc, 2)
    eng.X[2, :3] = eng.X[1, :3] + np.array([100.0, 0.0, 0.0])  # row i + 1 is sat i
    state = swarm_state_from_engine(eng)
    cert = certify(hold(state), state, sc, d_safe_m=500.0, **FAST)
    assert set(cert.min_sep_pair) == {0, 1} and cert.min_sep_t_s == 0.0
    assert cert.min_sep_m == pytest.approx(100.0, abs=1e-6)
    assert reasons_of(cert, "separation") and not cert.passed


# ---- 2. fuel -------------------------------------------------------------------------------------
def test_fuel_fails_with_a_small_tank():
    sc = scn(2.0, spacecraft={"m_prop_kg": 0.01})  # tank delta-v = 40 g0 ln(4/3.99) = 0.9824 m/s
    state = swarm_state_from_engine(engine_at(sc, 0))
    tank = 40.0 * G0 * math.log(4.0 / 3.99)
    cert = certify(Plan((mover(0, burn([0.5, 0, 0], [0, 0.3, 0])),), "x", 0.0), state, sc,
                   d_safe_m=60.0, **FAST)
    assert reasons_of(cert, "fuel") and not cert.passed
    assert cert.worst_fuel_sat == 0
    assert cert.planned_fuel_margin_mps == pytest.approx(0.8 * tank - 0.8, abs=1e-9)  # reserve 20 %
    assert cert.worst_fuel_margin_mps <= cert.planned_fuel_margin_mps
    cert0 = certify(Plan((mover(0, burn([0.5, 0, 0], [0, 0.3, 0])),), "x", 0.0), state, sc,
                    d_safe_m=60.0, fuel_reserve=0.0, **FAST)
    assert cert0.planned_fuel_margin_mps == pytest.approx(tank - 0.8, abs=1e-9)
    # exact: no static "needs" reason; with no reserve the flown check reports only the empty tank
    assert reasons_of(cert0, "fuel") == ["fuel: sat 0 runs out of propellant during the horizon"]


def test_fuel_margin_uses_the_current_mass_not_the_launch_mass():
    sc = scn(2.0)
    state = swarm_state_from_engine(engine_at(sc, 0))
    s = state.sats[2]
    s.m_kg, s.m_prop_kg = 3.9, 0.1  # used 0.1 kg already: tank delta-v now 40 g0 ln(3.9/3.8)
    cert = certify(Plan((mover(2, burn([1.0, 0, 0])),), "x", 0.0), state, sc, d_safe_m=60.0, **FAST)
    assert cert.planned_fuel_margin_mps == pytest.approx(
        0.8 * 40.0 * G0 * math.log(3.9 / 3.8) - 1.0, abs=1e-9
    )


def test_fuel_worst_margin_is_over_all_movers():
    sc = scn(2.0)
    state = swarm_state_from_engine(engine_at(sc, 0))
    items = (mover(1, burn([1.0, 0, 0])), mover(3, burn([4.0, 0, 0])), mover(4, burn([2.0, 0, 0])))
    cert = certify(Plan(items, "x", 0.0), state, sc, d_safe_m=60.0, **FAST)
    assert cert.worst_fuel_sat == 3
    assert cert.planned_fuel_margin_mps == pytest.approx(0.8 * state.sats[3].fuel_mps_left - 4.0)


def test_k_zero_sat_cannot_move():
    sc = scn(2.0, failures=[{"t": 0.0, "sat_id": 3, "mode": "THRUSTER_OUT"}])
    state = swarm_state_from_engine(engine_at(sc, 1))
    assert state.sats[3].k == 0.0 and state.sats[3].fuel_mps_left > 10.0  # fuel left, no thrust
    tiny = burn([0.01, 0, 0])
    cert = certify(Plan((mover(3, tiny),), "x", state.t_s), state, sc, d_safe_m=60.0, **FAST)
    assert any("sat 3 cannot move" in r and "k = 0" in r for r in reasons_of(cert, "fuel"))
    assert not cert.passed and cert.worst_fuel_sat == 3 and cert.worst_fuel_margin_mps <= 0.0


@pytest.mark.parametrize(
    "mode", ["DEAD", "RADIO_FAIL"], ids=["dead sat", "silent sat (cannot be commanded)"]
)
def test_dead_or_silent_sat_cannot_be_a_mover(mode):
    sc = scn(2.0, failures=[{"t": 0.0, "sat_id": 4, "mode": mode}])
    state = swarm_state_from_engine(engine_at(sc, 1))
    cert = certify(Plan((mover(4, burn([0.01, 0, 0])),), "x", state.t_s), state, sc,
                   d_safe_m=60.0, **FAST)
    assert any("sat 4 cannot move" in r for r in reasons_of(cert, "fuel"))
    assert cert.landing_error_m == 0.0  # its burn is not flown: it cannot be commanded


def test_zero_fuel_start():
    sc = scn(2.0, spacecraft={"m_prop_kg": 0.0})
    state = swarm_state_from_engine(engine_at(sc, 2))
    assert all(s.depleted for s in state.sats)
    hold_cert = certify(hold(state), state, sc, d_safe_m=500.0, **FAST)  # holds, never raises
    assert reasons_of(hold_cert, "fuel") == [] and hold_cert.worst_fuel_margin_mps == 0.0
    cert = certify(Plan((mover(0, burn([0.001, 0, 0])),), "x", state.t_s), state, sc,
                   d_safe_m=60.0, **FAST)
    assert any("empty tank" in r for r in cert.reasons) and not cert.passed


def test_lp_returns_none_for_k_zero_and_the_plan_is_a_hold():
    """The planner's side of the zero-fuel contract: no plan -> the caller certifies a hold."""
    slot0, slot1 = slots(2.0)[0], slots(2.0)[1]
    assert lp_transfer(slot0, propagate(slot1, 4000.0, N_MM), 4000.0, N_MM, 0.01, 0.0, 12) is None


# ---- 3. roles ------------------------------------------------------------------------------------
def test_roles_fail_when_leader_vacant_or_incapable():
    sc = scn(2.0, failures=[{"t": 0.0, "sat_id": 0, "mode": "DEAD"}])  # sat 0 = leader
    # (a) declared dead and re-roled: a hold plan keeps the engine's roles and is fine
    state = swarm_state_from_engine(engine_at(sc, 20))
    assert certify(hold(state), state, sc, d_safe_m=500.0, **FAST).roles_ok
    # (b) not yet declared (tick 2 < K heartbeats): the swarm still believes the dead leader leads
    early = swarm_state_from_engine(engine_at(sc, 2))
    assert early.roles[0] == ["leader"] and early.status[0] == "DEAD"
    cert = certify(hold(early), early, sc, d_safe_m=500.0, **FAST)
    assert not cert.roles_ok and not cert.passed
    assert cert.vacant_roles == ["leader"]  # the only holder is incapable: vacant in truth
    assert any("leader on sat 0 (DEAD)" in r for r in reasons_of(cert, "roles"))
    # (c) a plan that simply drops the leader role
    seats = slots(2.0)
    items = tuple(
        PlanItem(i, None, seats[i], tuple(r for r in state.roles[i] if r != "leader"))
        for i in range(6)
    )
    cert = certify(Plan(items, "x", state.t_s), state, sc, d_safe_m=500.0, **FAST)
    assert cert.vacant_roles == ["leader"] and not cert.roles_ok
    # (d) leader AND downlink given to an incapable (payload-less is fine for a leader; radio-less
    # is not) sat: the downlink on a RADIO_SILENT sat
    sc2 = scn(2.0, failures=[{"t": 0.0, "sat_id": 5, "mode": "RADIO_FAIL"}])
    st2 = swarm_state_from_engine(engine_at(sc2, 20))
    it = (PlanItem(5, None, slots(2.0)[5], ("downlink",)),)
    cert = certify(Plan(it, "x", st2.t_s), st2, sc2, d_safe_m=500.0, **FAST)
    assert not cert.roles_ok and any("downlink on sat 5" in r for r in cert.reasons)


def test_a_role_on_an_incapable_sat_fails_even_when_a_capable_sat_also_holds_it():
    sc = scn(2.0, failures=[{"t": 0.0, "sat_id": 2, "mode": "PAYLOAD_FAIL"}])
    state = swarm_state_from_engine(engine_at(sc, 20))
    items = (PlanItem(2, None, slots(2.0)[2], ("imager",)),)  # a payload-dead imager
    cert = certify(Plan(items, "x", state.t_s), state, sc, d_safe_m=500.0, **FAST)
    assert not cert.roles_ok and cert.vacant_roles == []  # critical roles are fine
    assert any("imager on sat 2" in r for r in cert.reasons)


# ---- 4. coverage ---------------------------------------------------------------------------------
def test_coverage_fails_when_plan_is_worse_than_hold():
    """Imager sat 4 is sent 600 m along track of imager sat 3: the footprints overlap. (Stacking
    all imagers on one seat no longer works as a probe: they never settle there, and a sat that
    does not reach its seat is removed from both sides of the coverage comparison.)"""
    sc = scn(2.0, dt_s=10.0)
    state = swarm_state_from_engine(engine_at(sc, 0))
    seats = slots(2.0)
    near = seats[3] + np.array([0.0, 600.0, 0.0, 0.0, 0.0, 0.0])
    stacked = (PlanItem(4, None, near, ("imager",)),)
    cert = certify(Plan(stacked, "stack", 0.0), state, sc, d_safe_m=60.0)
    assert cert.coverage < cert.hold_coverage - 1e-3
    # the 2.8 km PD dash also spends more than 80 % of sat 4's tank (flown-fuel check)
    assert [r.split(":")[0] for r in cert.reasons] == ["fuel", "coverage"] and not cert.passed
    low = certify(Plan(stacked, "stack", 0.0), state, sc, d_safe_m=60.0, coverage_floor=0.0)
    assert reasons_of(low, "coverage") == []  # an explicit floor replaces the hold comparison
    assert low.coverage == cert.coverage and low.hold_coverage == cert.hold_coverage
    high = certify(hold(state), state, sc, d_safe_m=60.0, coverage_floor=0.99, **FAST)
    assert reasons_of(high, "coverage") and high.coverage == high.hold_coverage


def test_coverage_counts_only_capable_imagers_and_hold_uses_current_roles():
    sc = scn(2.0)
    state = swarm_state_from_engine(engine_at(sc, 0))
    base = certify(hold(state), state, sc, d_safe_m=60.0, **FAST)
    state.sats[1].payload_ok = False  # still labelled imager, but its payload is dead
    cert = certify(hold(state), state, sc, d_safe_m=60.0, **FAST)
    assert cert.coverage < base.coverage - 1e-3 and cert.coverage == cert.hold_coverage
    assert not cert.roles_ok  # and the roles check flags the incapable imager


# ---- 5. landing: CW-planned transfers miss in truth by an amount that grows with the size --------
def _transfer_plan(amp_km, f_max_n):
    """Sat 0 slot 0 -> slot 1 in one orbit, planned by lp_transfer in CW (no tuning), a_max of
    the LP = the sat's real cap F_max / m, flown by the certificate's thrust-limited model."""
    sc = scn(amp_km, a_max_mps2=0.01, spacecraft={"f_max_n": f_max_n})
    state = swarm_state_from_engine(engine_at(sc, 0))
    s0, s1 = slots(amp_km)[0], slots(amp_km)[1]
    tr = lp_transfer(s0, propagate(s1, PERIOD, N_MM), PERIOD, N_MM, max(0.01, f_max_n / 4), 1.0, 48)
    assert tr is not None
    return sc, state, Plan((PlanItem(0, tr, s1, ("leader",)),), "cw", 0.0)


# (formation km, F_max N) -> measured truth landing error [m]. F_max 0.04 N is the scenario
# default (a = 0.01 m/s^2: each LP impulse is a ~120 s burn); 4 N is near-impulsive (1-2 steps).
LANDING = [(8.0, 0.04, 697.1), (2.0, 0.04, 138.4), (8.0, 4.0, 274.2), (2.0, 4.0, 68.2),
           (1.0, 4.0, 31.6)]


@pytest.mark.slow
@pytest.mark.parametrize(("amp", "f_max", "measured"), LANDING)
def test_landing_fails_for_cw_planned_transfers_but_1km_impulsive(amp, f_max, measured):
    """MEASURED, not tuned: a CW plan misses in truth by 697 m at 8 km and still by 138 m at
    2 km at default thrust (finite burns double the error: 68 m near-impulsive), 31.6 m only at
    1 km near-impulsive. The 50 m default tolerance therefore fails everything but the last, so
    even a 2 km plan must be MPC-corrected (kit 2.2 'smaller formation' = 1 km or less)."""
    sc, state, plan = _transfer_plan(amp, f_max)
    cert = certify(plan, state, sc, d_safe_m=60.0, horizon_orbits=1.0)
    print(f"\nlanding error, {amp:g} km formation, F_max {f_max:g} N: {cert.landing_error_m:.1f} m")
    assert cert.landing_error_m == pytest.approx(measured, rel=0.02)
    assert (reasons_of(cert, "landing") == []) == (measured <= 50.0)
    lax = certify(plan, state, sc, d_safe_m=cert.landing_error_m + 2.0, horizon_orbits=1.0,
                  landing_tol_m=cert.landing_error_m + 1.0)
    assert reasons_of(lax, "landing") == []  # the limit is the tolerance and nothing else
    assert lax.landing_error_m == cert.landing_error_m


def test_landing_error_grows_with_formation_size_fast():
    errs = []
    for amp in (1.0, 4.0):
        sc, state, plan = _transfer_plan(amp, 4.0)
        errs.append(certify(plan, state, sc, d_safe_m=60.0, horizon_orbits=1.0).landing_error_m)
    assert errs[1] > 3.0 * errs[0]


# ---- payload, completeness, determinism, cancel --------------------------------------------------
def test_event_payload_is_json_safe_and_complete():
    sc = scn(2.0, dt_s=10.0)
    state = swarm_state_from_engine(engine_at(sc, 0))
    cert = certify(hold(state), state, sc, d_safe_m=500.0)
    payload = cert.event_payload()
    assert set(payload) == {
        "passed", "level", "min_sep_m", "worst_fuel_margin_mps", "roles_ok", "coverage",
        "hold_coverage", "landing_error_m", "reasons",
    }
    assert payload["level"] == "hold" and payload["passed"] is True and payload["reasons"] == []
    assert json.loads(json.dumps(payload, allow_nan=False)) == payload
    assert all(type(payload[k]) is float for k in payload if k.endswith(("_m", "_mps", "coverage")))
    bad = Certificate(passed=False, reasons=["x"], min_sep_m=float("nan"))
    with pytest.raises(ValueError, match="min_sep_m"):
        bad.event_payload()
    for field in ("worst_fuel_margin_mps", "coverage", "hold_coverage", "landing_error_m"):
        with pytest.raises(ValueError, match=field):
            Certificate(passed=True, **{field: float("inf")}).event_payload()


def test_all_checks_evaluated_after_first_failure():
    sc = scn(2.0, dt_s=10.0)
    state = swarm_state_from_engine(engine_at(sc, 0))
    seats = slots(2.0)
    items = [PlanItem(i, None, seats[1], ("imager",)) for i in (3, 4)]  # stacked imagers
    items.append(PlanItem(1, burn([5.0, 0, 0]), seats[0], ()))  # fits the tank, lands far off
    items.append(PlanItem(2, burn([30.0, 0, 0]), seats[2], ()))  # 30 m/s > tank: not flown
    items.append(PlanItem(0, None, seats[0], ()))  # leader dropped
    cert = certify(Plan(tuple(items), "all", 0.0), state, sc, d_safe_m=1e5)
    kinds = {r.split(":")[0] for r in cert.reasons}
    print("\nall-checks reasons:", cert.reasons)
    assert kinds == {"separation", "fuel", "roles", "coverage", "landing", "settled"}
    assert not cert.passed and not cert.roles_ok


def test_single_failure_leaves_the_other_checks_green():
    sc = scn(2.0, dt_s=10.0)
    state = swarm_state_from_engine(engine_at(sc, 0))
    cert = certify(hold(state), state, sc, d_safe_m=1e5)  # only separation can fail
    assert [r.split(":")[0] for r in cert.reasons] == ["separation"] and not cert.passed
    assert cert.roles_ok and cert.landing_error_m == 0.0


def test_deterministic_twice_equal():
    sc = scn(2.0)
    state = swarm_state_from_engine(engine_at(sc, 0))
    plan = Plan((mover(0, burn([0.2, 0, 0], [0, 0.1, 0])),), "x", 0.0)
    a = certify(plan, state, sc, d_safe_m=500.0, horizon_orbits=0.3)
    b = certify(plan, state, sc, d_safe_m=500.0, horizon_orbits=0.3)
    assert a == b and json.dumps(a.event_payload()) == json.dumps(b.event_payload())


class _SetAfter(threading.Event):
    def __init__(self, calls):
        super().__init__()
        self.calls, self.left = 0, calls

    def is_set(self):
        self.calls += 1
        return self.calls > self.left


def test_cancel_event_raises():
    sc = scn(2.0)
    state = swarm_state_from_engine(engine_at(sc, 0))
    assert issubclass(CertificateCancelled, RuntimeError)
    ev = threading.Event()
    ev.set()
    with pytest.raises(CertificateCancelled):
        certify(hold(state), state, sc, d_safe_m=500.0, cancel_event=ev)
    mid = _SetAfter(40)  # cancelled in the middle of the run, between steps
    with pytest.raises(CertificateCancelled):
        certify(hold(state), state, sc, d_safe_m=500.0, cancel_event=mid)
    assert mid.calls == 41  # stopped at the very next step


def test_item_seats_are_propagated_to_the_plan_start():
    """At t = 40 s an item whose seat is the formation slot (t = 0 convention) is the same plan as
    holding: the certificate must propagate it to the plan start, as the engine's `refs` are."""
    sc = scn(2.0)
    state = swarm_state_from_engine(engine_at(sc, 20))
    seats = slots(2.0)
    items = tuple(PlanItem(i, None, seats[i], tuple(state.roles[i])) for i in range(6))
    same = certify(Plan(items, "same", state.t_s), state, sc, d_safe_m=500.0, horizon_orbits=0.5)
    base = certify(hold(state), state, sc, d_safe_m=500.0, horizon_orbits=0.5)
    assert same.min_sep_m == pytest.approx(base.min_sep_m, abs=1e-3)
    assert same.coverage == pytest.approx(base.coverage, abs=1e-9)
    assert same.reasons == base.reasons and same.landing_error_m == 0.0


def test_dropping_an_imager_role_is_worse_than_holding_the_current_roles():
    sc = scn(2.0)
    state = swarm_state_from_engine(engine_at(sc, 0))
    items = (PlanItem(4, None, slots(2.0)[4], ("spare",)),)  # same seat, imager role dropped
    cert = certify(Plan(items, "drop", 0.0), state, sc, d_safe_m=60.0, **FAST)
    assert cert.coverage < cert.hold_coverage - 1e-3 and reasons_of(cert, "coverage")


def test_a_silent_sat_keeps_its_old_seat_whatever_the_plan_says():
    sc = scn(2.0, failures=[{"t": 0.0, "sat_id": 5, "mode": "RADIO_FAIL"}])
    state = swarm_state_from_engine(engine_at(sc, 20))
    items = (PlanItem(5, None, slots(2.0)[0], tuple(state.roles[5])),)  # "go to sat 0's slot"
    plan = Plan(items, "x", state.t_s)
    cert = certify(plan, state, sc, d_safe_m=60.0, horizon_orbits=0.5)
    base = certify(hold(state), state, sc, d_safe_m=60.0, horizon_orbits=0.5)
    assert cert.min_sep_m == pytest.approx(base.min_sep_m, abs=1e-3)
