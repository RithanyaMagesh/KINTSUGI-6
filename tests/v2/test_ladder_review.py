"""Phase 5d-2 review round 1 (fresh adversarial reviewer): one regression test per Important
finding, each failing before its fix."""

from __future__ import annotations

import numpy as np
import pytest
from ladder_fixtures import assert_every_plan_certified, events, ladder_scn

from cubesat.certify import swarm_state_from_engine
from cubesat.certify_checks import commandable, passive
from cubesat.certify_sim import burn_span
from cubesat.recovery_v2 import Recovery
from cubesat.scenario import Failure
from cubesat.sim_v2 import EngineV2
from cubesat.spacecraft import SatState


def test_inflight_keeps_the_coast_to_the_plan_end():
    """Finding 1: the converted transfer must hand over to PD at the ORIGINAL step, also when
    the last burns are zero, and a sat with only coast left stays in flight."""
    rec = Recovery()
    burn = np.zeros((10, 3))
    burn[2] = [1e-3, 0, 0]
    rec.k0, rec.burns = 100, {3: (burn, 9), 4: (np.zeros((10, 3)), 9)}
    sat = SatState(4.0, 0.2, 40.0, 0.04)
    fl = rec.inflight(101, 2.0)
    assert set(fl) == {3, 4}
    for tr in fl.values():
        assert burn_span(tr, sat, 2.0)[2] == 9 - 1  # PD from the same step as the original


def test_a_dry_stuck_open_sat_is_passive_and_a_wet_one_is_not():
    """Finding 2: stuck_vec stays set after the tank runs dry; that sat must be passive (it can
    never thrust again). A stuck sat with fuel is not passive (the ladder treats it as an
    uncommanded obstacle, never a mover)."""
    s = SatState(4.0, 0.0, 40.0, 0.04, k=0.0, stuck_vec=np.array([1.0, 0.0, 0.0]))
    assert passive(s)
    wet = SatState(4.0, 0.1, 40.0, 0.04, stuck_vec=np.array([1.0, 0.0, 0.0]))
    assert not passive(wet) and commandable("DEGRADED", False)


def test_an_isolated_sat_is_not_commandable():
    """Finding 4: a declared (silent to the swarm) sat with a working radio is unreachable."""
    assert not commandable("NOMINAL", True) and commandable("NOMINAL", False)
    eng = EngineV2(ladder_scn())
    eng.faults.declared[3] = True
    assert swarm_state_from_engine(eng).declared == [False, False, False, True, False, False]


@pytest.mark.slow
def test_roles_follow_the_swarms_belief_not_an_undetected_failure():
    """Finding 3: sat 1 self-reports THRUSTER_OUT at 100 s (plan at 102 s) while sat 5's radio
    died silently at 100 s (declared at 104 s): the 102 s plan must not hand the downlink over
    before the heartbeat says so."""
    fails = [{"t": 100.0, "sat_id": 1, "mode": "THRUSTER_OUT"},
             {"t": 100.0, "sat_id": 5, "mode": "RADIO_FAIL"}]
    eng = EngineV2(ladder_scn(orbits=0.4, failures=fails))
    lines = [eng.step() for _ in range(eng.n_ticks)]
    hand = [(t, p) for t, p in events(lines, "ROLE_HANDOFF") if p["role"] == "downlink"]
    det = [t for t, p in events(lines, "FAILURE_DETECTED") if p["sat_id"] == 5]
    assert hand and det and hand[0][0] >= det[0], (hand, det)
    assert assert_every_plan_certified(lines) >= 1


@pytest.mark.slow
def test_an_undelivered_burn_triggers_a_replan():
    """Finding 5: PARTIAL_THRUST on a mover is silent (no FAILURE_DETECTED), but the commanded
    burn is not delivered: the executor must notice and re-plan (re-certify)."""
    fails = [{"t": 0.0, "sat_id": 1, "mode": "DEAD"}]
    sc = ladder_scn(orbits=1.0, failures=fails)
    eng = EngineV2(sc)
    while not eng.rec.burns:  # the ladder's first plan must be a move for this test
        assert eng.k < 20, "no move planned"
        eng.step()
    mover = min(i for i, (b, last) in eng.rec.burns.items() if np.abs(b).sum() > 0)
    eng.inject(Failure(t=eng.k * sc.dt_s, sat_id=mover, mode="PARTIAL_THRUST"))
    lines = [eng.step() for _ in range(eng.n_ticks - eng.k)]
    assert events(lines, "RECOVERY_LEVEL"), "no re-plan after the burn was not delivered"
    assert assert_every_plan_certified(lines) >= 1
