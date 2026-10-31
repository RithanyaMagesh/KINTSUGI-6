"""Phase 5d-1: the certificate's forward simulation IS the engine's stepper (docs/PHYSICS_V2.md).

A HOLD plan (no items) must reproduce the engine's own run: minimum separation to 1 m and the
final ECI state to 1e-6 m. Three scenarios, one with a dead sat and drag, one with THRUSTER_OUT
and a radio-silent sat under a density storm."""

from __future__ import annotations

import copy

import numpy as np
import pytest
from certify_fixtures import PERIOD, engine_at, scn

from cubesat.certify import Plan, certify, swarm_state_from_engine
from cubesat.certify_sim import simulate

CASES = {
    "healthy": (scn(2.0), 0),
    "dead_with_drag": (
        scn(2.0, failures=[{"t": 0.0, "sat_id": 1, "mode": "DEAD"}], truth={"density_factor": 30}),
        20,
    ),
    "mixed_storm": (
        scn(
            2.0,
            failures=[
                {"t": 0.0, "sat_id": 3, "mode": "THRUSTER_OUT"},
                {"t": 0.0, "sat_id": 2, "mode": "RADIO_FAIL"},
                {"t": 0.0, "sat_id": 4, "mode": "PARTIAL_THRUST"},
            ],
            truth={"density_factor": 50},
        ),
        20,
    ),
}


def _run_engine(eng, steps):
    seps = [eng.step()["min_sep"] for _ in range(steps + 1)]  # ticks k0 .. k0 + steps
    return min(seps), eng


@pytest.mark.slow
@pytest.mark.parametrize("name", CASES)
def test_hold_plan_matches_the_engine_run(name):
    sc, ticks = CASES[name]
    eng = engine_at(sc, ticks)
    state = swarm_state_from_engine(eng)
    cert = certify(Plan((), "hold", state.t_s), state, sc, d_safe_m=500.0)
    steps = round(cert.horizon_s / sc.dt_s)
    assert steps == round(2.0 * PERIOD / sc.dt_s)
    engine_sep, _ = _run_engine(eng, steps)
    print(f"\n{name}: certificate min sep {cert.min_sep_m:.4f} m vs engine {engine_sep:.4f} m")
    assert abs(cert.min_sep_m - engine_sep) < 1.0
    assert cert.min_sep_t_s >= 0.0


@pytest.mark.slow
def test_certificate_executes_a_plan_like_the_engine():
    sc, ticks = CASES["mixed_storm"]
    eng = engine_at(sc, ticks)
    state = swarm_state_from_engine(eng)
    steps = round(2.0 * PERIOD / sc.dt_s)
    res = simulate(sc, state, state.refs, {}, steps)
    _run_engine(eng, steps - 1)  # engine.X is the state after `steps` more ticks
    assert eng.k == ticks + steps
    assert np.abs(res.final_eci - eng.X).max() < 1e-6
    for got, want in zip(res.final_sats, eng.faults.sats, strict=True):  # fuel use too
        assert abs(got.m_prop_kg - want.m_prop_kg) < 1e-12


def test_certify_does_not_mutate_its_inputs():
    sc = scn(2.0, failures=[{"t": 0.0, "sat_id": 1, "mode": "DEAD"}])
    state = swarm_state_from_engine(engine_at(sc, 10))
    before = copy.deepcopy(state)
    certify(Plan((), "hold", state.t_s), state, sc, d_safe_m=500.0, horizon_orbits=0.05)
    assert np.array_equal(state.sat_eci, before.sat_eci)
    assert np.array_equal(state.chief, before.chief)
    assert np.array_equal(state.refs, before.refs)
    assert state.status == before.status and state.roles == before.roles
    assert [s.to_dict() for s in state.sats] == [s.to_dict() for s in before.sats]
