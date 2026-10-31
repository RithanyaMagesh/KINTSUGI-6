"""Phase 5d-1: Review Focus inputs and malformed input for the certificate (never a crash)."""

from __future__ import annotations

import json
import time

import numpy as np
import pytest
from certify_fixtures import NOMINAL, SENSOR, engine_at, scn, slots

from cubesat import truth
from cubesat.certify import Plan, PlanItem, certify, swarm_state_from_engine
from cubesat.scenario import Scenario
from cubesat.transfer import Transfer

FAST = {"horizon_orbits": 0.1}


def hold(state) -> Plan:
    return Plan((), "hold", state.t_s)


def dead(*ids, t=0.0):
    return [{"t": t, "sat_id": i, "mode": "DEAD"} for i in ids]


def test_all_but_one_sat_dead_does_not_crash_and_keeps_every_role_on_the_survivor():
    sc = scn(2.0, failures=dead(1, 2, 3, 4, 5))
    state = swarm_state_from_engine(engine_at(sc, 20))
    cert = certify(hold(state), state, sc, d_safe_m=500.0, **FAST)
    assert cert.roles_ok and cert.vacant_roles == []
    assert set(state.roles[0]) >= {"leader", "downlink"}
    assert cert.coverage > 0.0 and cert.min_sep_m > 0.0


def test_every_sat_dead_has_vacant_roles_and_zero_coverage():
    sc = scn(2.0, failures=dead(0, 1, 2, 3, 4, 5))
    state = swarm_state_from_engine(engine_at(sc, 20))
    cert = certify(hold(state), state, sc, d_safe_m=500.0, **FAST)
    assert not cert.roles_ok and set(cert.vacant_roles) == {"leader", "downlink"}
    assert cert.coverage == 0.0 and cert.hold_coverage == 0.0
    assert not cert.passed and any(r.startswith("roles") for r in cert.reasons)
    assert not any(r.startswith("coverage") for r in cert.reasons)  # 0 >= 0: not worse than hold
    json.dumps(cert.event_payload(), allow_nan=False)  # finite even with nothing alive


@pytest.mark.slow
def test_32_sats_runtime_reported():
    n = 32
    roles = ["leader", "downlink", *["imager"] * (n - 2)]
    sc = Scenario.model_validate(
        {**NOMINAL, "engine": "v2", "roles": roles, "sensor": SENSOR, "a_max_mps2": 0.01,
         "formation": {"n_slots": n, "radial_amp_km": 4.0, "phase_offset_deg": 0.0},
         "duration_s": 12000.0, "failures": dead(5, 17), "allocation": {"min_sep_km": 0.1},
         "truth": {"density_factor": 5}}
    )
    state = swarm_state_from_engine(engine_at(sc, 20))
    t0 = time.perf_counter()
    cert = certify(hold(state), state, sc, d_safe_m=100.0)
    secs = time.perf_counter() - t0
    print(f"\n32-sat certificate, 2 orbits ({cert.horizon_s / sc.dt_s:.0f} steps): {secs:.1f} s, "
          f"min sep {cert.min_sep_m:.1f} m, passed {cert.passed}")
    assert np.isfinite(cert.min_sep_m) and cert.horizon_s > 11000.0


def _base():
    sc = scn(2.0)
    return sc, swarm_state_from_engine(engine_at(sc, 0))


@pytest.mark.parametrize("h", [0.0, -1.0, float("nan"), float("inf")])
def test_bad_horizon_raises(h):
    sc, state = _base()
    with pytest.raises(ValueError, match="horizon_orbits"):
        certify(hold(state), state, sc, d_safe_m=500.0, horizon_orbits=h)


@pytest.mark.parametrize("d", [float("nan"), -1.0, float("inf")])
def test_bad_d_safe_raises(d):
    sc, state = _base()
    with pytest.raises(ValueError, match="d_safe_m"):
        certify(hold(state), state, sc, d_safe_m=d, **FAST)


@pytest.mark.parametrize(
    ("kw", "name"),
    [({"fuel_reserve": 1.0}, "fuel_reserve"), ({"fuel_reserve": -0.1}, "fuel_reserve"),
     ({"fuel_reserve": float("nan")}, "fuel_reserve"), ({"landing_tol_m": -1.0}, "landing_tol_m"),
     ({"landing_tol_m": float("nan")}, "landing_tol_m"),
     ({"coverage_floor": float("nan")}, "coverage_floor")],
)
def test_bad_parameters_raise(kw, name):
    sc, state = _base()
    with pytest.raises(ValueError, match=name):
        certify(hold(state), state, sc, d_safe_m=500.0, **FAST, **kw)


def _tr(dv, times=(0.0,)):
    return Transfer(np.array(dv, dtype=float), np.array(times, dtype=float), 1.0, 1.0, 1)


@pytest.mark.parametrize("sat_id", [-1, 6, 99])
def test_unknown_sat_id_raises(sat_id):
    sc, state = _base()
    plan = Plan((PlanItem(sat_id, None, slots(2.0)[0], ()),), "x", 0.0)
    with pytest.raises(ValueError, match="unknown sat id"):
        certify(plan, state, sc, d_safe_m=1e-6, **FAST)


def test_duplicate_item_raises():
    sc, state = _base()
    it = PlanItem(1, None, slots(2.0)[1], ())
    with pytest.raises(ValueError, match="two items"):
        certify(Plan((it, it), "x", 0.0), state, sc, d_safe_m=1e-6, **FAST)


@pytest.mark.parametrize(
    "tr",
    [
        _tr([[np.nan, 0, 0]]),
        _tr([[np.inf, 0, 0]]),
        _tr([[1, 0, 0]], times=(np.nan,)),
        _tr([[1, 0, 0]], times=(-5.0,)),
        _tr([[1, 0]]),
        _tr(np.zeros((0, 3)), times=()),
    ],
    ids=["nan dv", "inf dv", "nan time", "negative time", "bad shape", "no nodes"],
)
def test_malformed_transfer_raises(tr):
    sc, state = _base()
    plan = Plan((PlanItem(0, tr, slots(2.0)[0], ()),), "x", 0.0)
    with pytest.raises(ValueError, match="transfer"):
        certify(plan, state, sc, d_safe_m=1e-6, **FAST)


def test_malformed_seat_role_and_time_raise():
    sc, state = _base()
    good = slots(2.0)[0]
    for item, match in [
        (PlanItem(0, None, good[:5], ()), "seat"),
        (PlanItem(0, None, np.full(6, np.nan), ()), "seat"),
        (PlanItem(0, None, good, ("captain",)), "unknown role"),
    ]:
        with pytest.raises(ValueError, match=match):
            certify(Plan((item,), "x", 0.0), state, sc, d_safe_m=1e-6, **FAST)
    with pytest.raises(ValueError, match="t_start_s"):
        certify(Plan((), "x", 50.0), state, sc, d_safe_m=1e-6, **FAST)
    with pytest.raises(ValueError, match="t_start_s"):
        certify(Plan((), "x", float("nan")), state, sc, d_safe_m=1e-6, **FAST)


def test_malformed_state_raises():
    sc, state = _base()
    state.sat_eci[2, 0] = np.nan
    with pytest.raises(ValueError, match="sat_eci"):
        certify(hold(state), state, sc, d_safe_m=1e-6, **FAST)
    _, state = _base()
    state.status.pop()
    with pytest.raises(ValueError, match="6 entries"):
        certify(hold(state), state, sc, d_safe_m=1e-6, **FAST)
    _, state = _base()
    state.sats[0].m_prop_kg = float("nan")
    with pytest.raises(ValueError, match="SatState"):
        certify(hold(state), state, sc, d_safe_m=1e-6, **FAST)


def test_swarm_state_is_a_copy_of_the_engine():
    eng = engine_at(scn(2.0), 3)
    state = swarm_state_from_engine(eng)
    x0, p0 = state.sat_eci.copy(), state.sats[0].m_prop_kg
    eng.step()
    eng.faults.sats[0].m_prop_kg -= 0.01
    eng.roles[0].append("spare")
    assert np.array_equal(state.sat_eci, x0) and state.sats[0].m_prop_kg == p0
    assert "spare" not in state.roles[0]
    assert state.t_s == 3 * eng.dt


def _brute_min_pair(eci, ids):
    best = (np.inf, None)
    for a in ids:
        for b in ids:
            if a < b:
                best = min(best, (float(np.linalg.norm(eci[a, :3] - eci[b, :3])), (a, b)))
    return best


def test_pair_indices_are_sat_ids_when_a_reentered_sat_is_excluded():
    from cubesat.certify_sim import simulate

    sc, state = _base()
    state.status[0] = "REENTERED"  # excluded from the separation, so ids must not shift
    res = simulate(sc, state, state.refs, {}, 0)
    want, pair = _brute_min_pair(state.sat_eci, range(1, 6))
    assert res.min_sep_pair == pair and 0 not in pair
    assert res.min_sep_m == pytest.approx(want, abs=1e-6)


def test_with_fewer_than_two_flying_sats_the_separation_uses_every_sat_at_its_frozen_state():
    from cubesat.certify_sim import simulate

    sc, state = _base()
    state.status = ["REENTERED"] * 5 + ["NOMINAL"]  # engine rule: <2 flying -> all sats count
    c = state.chief
    state.hold = truth.eci_to_lvlh(state.sat_eci[:, :3], state.sat_eci[:, 3:], c[:3], c[3:])
    res = simulate(sc, state, state.refs, {}, 0)
    want, pair = _brute_min_pair(state.sat_eci, range(6))
    assert res.min_sep_pair == pair and res.min_sep_m == pytest.approx(want, abs=1e-6)
