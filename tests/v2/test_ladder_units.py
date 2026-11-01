"""Phase 5d-2: recovery ladder pieces that are cheap to test (fast suite)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from certify_fixtures import N_MM, scn
from ladder_fixtures import ladder_scn

from cubesat import ladder, ladder_moves
from cubesat.allocate_v2 import candidate_slots
from cubesat.certify import Certificate, Plan, PlanItem
from cubesat.hcw import propagate
from cubesat.scenario import Scenario
from cubesat.sim_v2 import EngineV2
from cubesat.transfer import Transfer


def test_ring_equals_candidate_slots_bit_for_bit():
    for psi in (0.0, 30.0, 90.0):
        a = ladder_moves.ring(8000.0, 0.3, math.radians(psi), 5, N_MM)
        b = candidate_slots(8000.0, 0.3, psi, 5, N_MM)
        assert all(np.array_equal(x, y) for x, y in zip(a, b, strict=True))


def test_ring_through_a_seat_starts_on_that_seat():
    th = 1.1 + 2.0 * math.pi * 4 / 6
    seat = candidate_slots(3000.0, 1.1, 30.0, 6, N_MM)[4]
    ring = ladder_moves.ring_through(seat, 5, N_MM)
    want = candidate_slots(3000.0, th, 30.0, 5, N_MM)  # the same ellipse, phased through it
    assert all(np.allclose(a, b, atol=1e-6) for a, b in zip(ring, want, strict=True))


def test_clear_rejects_seats_or_obstacles_inside_d_safe():
    s = candidate_slots(2000.0, 0.0, 0.0, 6, N_MM)
    ts = [m * 2.0 * math.pi / N_MM / 72 for m in range(72)]
    brute = min(np.linalg.norm(propagate(s[i], t, N_MM)[:3] - propagate(s[j], t, N_MM)[:3])
                for t in ts for i in range(6) for j in range(i + 1, 6))
    assert ladder_moves.clear(s, [], N_MM, brute - 1.0)
    assert not ladder_moves.clear(s, [], N_MM, brute + 1.0)
    assert not ladder_moves.clear(s[:1], [s[0] + np.array([500.0, 0, 0, 0, 0, 0])], N_MM, 1000.0)


def test_ladder_is_opt_in_and_inert_by_default():
    plain = scn(2.0)
    central = scn(2.0, recovery={"authority": "central"})
    off = scn(2.0, recovery={"authority": "central", "ladder": False})
    assert EngineV2(plain).rec is None and EngineV2(off).rec is None
    # the default flag stays out of the dump: fingerprints (snapshot guard) do not change
    assert central.model_dump_json(exclude_none=True) == off.model_dump_json(exclude_none=True)
    assert EngineV2(ladder_scn()).rec is not None


def test_ladder_needs_engine_v2_and_central_authority():
    d = scn(2.0).model_dump(exclude_none=True)
    with pytest.raises(ValueError, match="requires engine"):
        Scenario.model_validate({**d, "engine": "v1", "recovery": {"ladder": True}})
    with pytest.raises(ValueError, match="central"):
        Scenario.model_validate(
            {**d, "comms": {"model": "laser"},
             "recovery": {"ladder": True, "authority": "decentral"}}
        )


def test_an_uncertified_plan_is_never_executed(monkeypatch):
    """Even if the ladder returned a plan whose certificate failed, the engine must not fly it."""
    sc = ladder_scn(failures=[{"t": 0.0, "sat_id": 1, "mode": "DEAD"}])
    eng = EngineV2(sc)
    far = propagate(eng.refs[2], 0.0, eng.n) + np.array([900.0, 0, 0, 0, 0, 0])
    tr = Transfer(np.array([[0.5, 0.0, 0.0]]), np.array([0.0]), 0.5, 100.0, 1)

    def fake(state, scenario, cancel=None, inflight=None, believed=None):
        plan = Plan((PlanItem(2, tr, far, ("imager",)),), "L3", state.t_s)
        bad = Certificate(False, ["separation: fake"], level="L3")
        return ladder.Decision("L3", plan, bad, "x")

    monkeypatch.setattr(ladder, "run_ladder", fake)
    refs0, lines = None, []
    for _ in range(12):
        refs0 = eng.refs.copy() if refs0 is None else refs0
        lines.append(eng.step())
    kinds = [e["type"] for ln in lines for e in ln.get("events", ())]
    assert "RECOVERY_LEVEL" in kinds and "CERTIFICATE" not in kinds
    assert not eng.rec.burns
    assert lines[-1]["sats"][2]["dv_used"] < 0.01  # PD hold only, no 0.5 m/s burn


def test_inflight_burns_round_trip_as_transfers():
    rec = __import__("cubesat.recovery_v2", fromlist=["Recovery"]).Recovery()
    burn = np.zeros((10, 3))
    burn[2], burn[7] = [1e-3, 0, 0], [0, -2e-3, 0]
    rec.k0, rec.burns = 100, {3: (burn, 9)}
    tr = rec.inflight(101, 2.0)[3]  # from step j = 1: the burns at j = 2 and 7, PD at j = 9
    assert np.allclose(tr.times, [2.0, 12.0, 16.0])
    assert np.allclose(tr.dv / 2.0, [burn[2], burn[7], np.zeros(3)])
