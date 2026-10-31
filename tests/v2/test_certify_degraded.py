"""Phase 5d fix round 2: the certificate on degraded swarms (reviewer /tmp/certrev/v2 repros).

A sat that cannot thrust at the start (k = 0 or an empty tank) is PASSIVE: not judged by
`settled`, never given a new seat, reported in `notes` with its drift. Coverage compares like for
like (the same excluded sats on both sides), so an empty plan never fails against itself. For
active sats `settled` is the maximum error over the final orbit (no horizon-phase luck)."""

from __future__ import annotations

import itertools
import warnings

import numpy as np
import pytest
from certify_fixtures import N_MM, PERIOD, engine_at, scn, slots

from cubesat import truth
from cubesat.certify import Plan, PlanItem, certify, swarm_state_from_engine
from cubesat.certify_checks import check_roles
from cubesat.certify_sim import simulate
from cubesat.hcw import propagate
from cubesat.transfer import Transfer, lp_transfer


def kinds(cert):
    return sorted({r.split(":")[0] for r in cert.reasons})


def dead(*ids):
    return [{"t": 0.0, "sat_id": i, "mode": "DEAD"} for i in ids]


def one(mode, sat=2):
    return [{"t": 0.0, "sat_id": sat, "mode": mode}]


# the reviewer's degraded holds (deg.py): every one must pass as a plain hold
DEGRADED = {
    "2 dead of 6, x1": (2.0, {"failures": dead(1, 3)}, 20),
    "2 dead of 6, x30 storm": (2.0, {"failures": dead(1, 3), "truth": {"density_factor": 30}}, 20),
    "THRUSTER_OUT 2 km x1": (2.0, {"failures": one("THRUSTER_OUT")}, 20),
    "THRUSTER_OUT 8 km x1": (8.0, {"failures": one("THRUSTER_OUT")}, 20),
    "THRUSTER_OUT 2 km x5": (
        2.0, {"failures": one("THRUSTER_OUT"), "truth": {"density_factor": 5}}, 20
    ),
    "all FUEL_DEPLETED": (2.0, {"spacecraft": {"m_prop_kg": 0.0}}, 3),
}
OTHERS = {
    "PARTIAL_THRUST": (2.0, {"failures": one("PARTIAL_THRUST")}, 20),
    "PAYLOAD_FAIL": (2.0, {"failures": one("PAYLOAD_FAIL")}, 20),
    "RADIO_FAIL": (2.0, {"failures": one("RADIO_FAIL")}, 20),
    "THRUSTER_OUT + dead": (2.0, {"failures": one("THRUSTER_OUT") + dead(4)}, 20),
}


def _hold(amp, kw, ticks, dt=None, **ckw):
    sc = scn(amp, **kw) if dt is None else scn(amp, dt_s=dt, **kw)
    st = swarm_state_from_engine(engine_at(sc, ticks))
    return st, certify(Plan((), "hold", st.t_s), st, sc, d_safe_m=500.0, **ckw)


@pytest.mark.slow
@pytest.mark.parametrize("name", DEGRADED)
def test_degraded_hold_passes(name):
    _, c = _hold(*DEGRADED[name])
    print(f"\n{name}: settled {c.settled_error_m:.1f} m, notes {c.notes}")
    assert c.passed, c.reasons


@pytest.mark.parametrize("name", [*DEGRADED, *OTHERS])
def test_an_empty_plan_never_fails_coverage_against_itself(name):
    amp, kw, ticks = {**DEGRADED, **OTHERS}[name]
    _, c = _hold(amp, kw, ticks, dt=10.0)
    assert c.coverage == c.hold_coverage and "coverage" not in kinds(c)


def test_passive_sat_is_noted_with_its_drift_and_not_judged_settled():
    st, c = _hold(2.0, {"failures": one("THRUSTER_OUT")}, 20, dt=10.0)
    assert c.passed and any("sat 2" in n and "passive" in n and "drifts" in n for n in c.notes)


def _coincidence_seat(amp):
    """The reviewer's P1-B seat: a CW orbit through the point the coasting THRUSTER_OUT sat
    reaches at the horizon end (so the old end-instant check saw ~0 m)."""
    sc = scn(amp, failures=one("THRUSTER_OUT"))
    st = swarm_state_from_engine(engine_at(sc, 20))
    steps = round(2 * PERIOD / sc.dt_s)
    res = simulate(sc, st, np.array(st.refs), {}, steps)
    c = res.final_eci[0]
    lv = truth.eci_to_lvlh(res.final_eci[1:, :3], res.final_eci[1:, 3:], c[:3], c[3:])
    seat = propagate(lv[2], -(st.t_s + steps * sc.dt_s), N_MM)
    return sc, st, Plan((PlanItem(2, None, seat, tuple(st.roles[2])),), "coincide", st.t_s)


@pytest.mark.slow
@pytest.mark.parametrize("amp", [2.0, 8.0])
def test_a_new_seat_for_a_passive_sat_fails(amp):
    sc, st, plan = _coincidence_seat(amp)
    c = certify(plan, st, sc, d_safe_m=500.0)
    assert not c.passed and kinds(c) == ["seat"]
    assert any(r.startswith("seat: sat 2 cannot thrust") for r in c.reasons)


@pytest.mark.slow
def test_thruster_out_hold_verdict_does_not_depend_on_horizon_phase():
    sc = scn(2.0, failures=one("THRUSTER_OUT"))
    st = swarm_state_from_engine(engine_at(sc, 20))
    got = [
        certify(Plan((), "h", st.t_s), st, sc, d_safe_m=500.0, horizon_orbits=h).passed
        for h in (2.0, 2.25, 2.5, 2.75, 3.0)
    ]
    assert got == [True] * 5


def test_active_settled_is_the_max_over_the_final_orbit_not_one_instant():
    """2 km slot 0 -> slot 1, near-impulsive 4 N: the truth miss at the plan end (68.2 m, the
    PHYSICS_V2 landing table) falls inside the final orbit, so settled is at least that. Pinned
    between 50 and 100 m: a settled tolerance of 2x the limit would pass it."""
    sc = scn(2.0, spacecraft={"f_max_n": 4.0})
    st = swarm_state_from_engine(engine_at(sc, 0))
    s = slots(2.0)
    tr = lp_transfer(s[0], propagate(s[1], PERIOD, N_MM), PERIOD, N_MM, 1.0, 1.0, 48)
    c = certify(Plan((PlanItem(0, tr, s[1], ("leader",)),), "x", 0.0), st, sc, d_safe_m=60.0)
    assert c.landing_error_m == pytest.approx(68.2, rel=0.02)
    assert c.settled_error_m >= c.landing_error_m - 1e-9
    assert c.settled_error_m == pytest.approx(68.2, rel=0.02)
    assert "settled" in kinds(c) and not c.passed


# ---- P2 ------------------------------------------------------------------------------------------
def _weak_mover(k):
    sc = scn(2.0)
    st = swarm_state_from_engine(engine_at(sc, 0))
    st.sats[1].k = k
    tr = Transfer(np.array([[1.0, 0, 0]]), np.array([0.0]), 1.0, 0.0, 1)
    return certify(Plan((PlanItem(1, tr, slots(2.0)[1], ("imager",)),), "x", 0.0), st, sc,
                   d_safe_m=500.0)


@pytest.mark.parametrize("k", [1e-300, 2.008e-4])
def test_absurdly_weak_thrusters_fail_the_fuel_check_without_warnings_or_errors(k):
    """k = 1e-300 overflowed the int64 cast (a RuntimeWarning, a garbage count); k = 2.008e-4
    fits the burn cap but not cap + tail and raised ValueError instead of failing."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        c = _weak_mover(k)
    assert not c.passed and any(r.startswith("fuel") and "steps" in r for r in c.reasons)


def test_landing_tolerance_must_be_below_the_separation_limit():
    sc = scn(2.0, dt_s=10.0)
    st = swarm_state_from_engine(engine_at(sc, 0))
    for tol in (500.0, 600.0):
        with pytest.raises(ValueError, match="landing_tol_m"):
            certify(Plan((), "h", 0.0), st, sc, d_safe_m=500.0, landing_tol_m=tol)


def test_roles_follow_the_engine_rule_downlink_holder_does_not_image_while_others_can():
    """roles3.py: sats 0 and 5 dead; the engine keeps the downlink holder off imaging because
    other imager-capable sats exist (assign_roles' eligibility), so a plan that adds it fails."""
    sc = scn(2.0, dt_s=10.0, failures=dead(0, 5))
    st = swarm_state_from_engine(engine_at(sc, 30))
    dl = next(i for i, r in enumerate(st.roles) if "downlink" in r)
    item = PlanItem(dl, None, slots(2.0)[dl], tuple(sorted({*st.roles[dl], "imager"})))
    c = certify(Plan((item,), "stack", st.t_s), st, sc, d_safe_m=500.0)
    assert not c.roles_ok and kinds(c) == ["roles"]
    assert certify(Plan((), "h", st.t_s), st, sc, d_safe_m=500.0).roles_ok  # engine's own


def _engine_states(cases):
    for sc_kw, ticks in cases:
        sc = scn(2.0, dt_s=10.0, **sc_kw)
        yield sc, swarm_state_from_engine(engine_at(sc, ticks))


def _agree(cases):
    bad = []
    for sc, st in _engine_states(cases):
        reasons = []
        _, ok = check_roles([list(r) for r in st.roles], st, sc, reasons)
        if not ok:
            bad.append((st.status, st.roles, reasons))
    return bad


def test_roles_check_agrees_with_the_engine_on_a_subset_of_failure_states():
    cases = [({"failures": dead(*p)}, 30) for p in ((0, 5), (1, 2), (0, 1, 5), (1, 2, 3, 4, 5))]
    cases += [({"failures": one("RADIO_FAIL", 0) + one("PAYLOAD_FAIL", 3)}, 30)]
    assert _agree(cases) == []


@pytest.mark.slow
def test_roles_check_agrees_with_the_engine_everywhere():
    """The reviewer's sweep: 6 priority orders x 15 dead pairs (90), 3/4/5 dead (20 + 15 + 6 =
    41), DEAD/RADIO_FAIL/PAYLOAD_FAIL pairs on ordered sat pairs after detection (270)."""
    perms = itertools.permutations(["downlink", "imager", "leader"])
    a = [({"role_priority": list(p), "failures": dead(*q)}, 30)
         for p in perms for q in itertools.combinations(range(6), 2)]
    b = [({"failures": dead(*q)}, 30)
         for k in (3, 4, 5) for q in itertools.combinations(range(6), k)]
    modes = ["DEAD", "RADIO_FAIL", "PAYLOAD_FAIL"]
    c = [({"failures": one(m1, i) + one(m2, j)}, 30)
         for m1, m2 in itertools.product(modes, modes)
         for i, j in itertools.permutations(range(6), 2)]
    assert (len(a), len(b), len(c)) == (90, 41, 270)
    for cases in (a, b, c):
        assert _agree(cases) == []
