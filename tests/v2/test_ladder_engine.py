"""Phase 5d-2: the recovery ladder inside EngineV2 (slow: every case flies several certificates).

Invariant over every log here: no plan executes without a passed CERTIFICATE (Task 5.G-d).
Adversarial seeds (Task 5.G-d): simultaneous failures, THRUSTER_OUT leader, zero fuel, cancel
mid-run (inside the ladder)."""

from __future__ import annotations

import json
import math
import threading

import numpy as np
import pytest
from ladder_fixtures import assert_every_plan_certified, events, ladder_scn, run_log

from cubesat import ladder_moves as mv
from cubesat import truth
from cubesat.certify import CertificateCancelled, Plan, PlanItem, swarm_state_from_engine
from cubesat.certify_sim import simulate
from cubesat.hcw import propagate
from cubesat.scenario import Failure
from cubesat.sim import RunCancelled
from cubesat.sim_v2 import EngineV2

pytestmark = pytest.mark.slow
DEAD_1_5 = [{"t": 600.0, "sat_id": 1, "mode": "DEAD"}, {"t": 900.0, "sat_id": 5, "mode": "DEAD"}]


def _crit_held(line):
    held = {r for s in line["sats"] if s["status"] == "NOMINAL" for r in s["roles"]}
    return {"leader", "downlink"} <= held


def test_two_deaths_plan_twice_certified_and_keep_the_critical_roles():
    lines = run_log(ladder_scn(failures=DEAD_1_5))
    assert assert_every_plan_certified(lines) == 2
    levels = [p["level"] for _, p in events(lines, "RECOVERY_LEVEL")]
    assert all(lv in ("L1", "L2", "L3") for lv in levels), levels
    assert _crit_held(lines[-2])  # downlink sat 5 died: re-elected


def test_simultaneous_failures_plan_once():
    fails = [{"t": 600.0, "sat_id": i, "mode": "DEAD"} for i in (1, 2)]
    lines = run_log(ladder_scn(failures=fails))
    assert [t for t, _ in events(lines, "RECOVERY_LEVEL")] == [606.0]
    assert assert_every_plan_certified(lines) == 1


def test_thruster_out_leader_keeps_its_seat_and_the_cripple_move_is_compared():
    fails = [{"t": 600.0, "sat_id": 0, "mode": "THRUSTER_OUT"},
             {"t": 600.0, "sat_id": 3, "mode": "DEAD"}]
    sc = ladder_scn(failures=fails)
    eng, lines = EngineV2(sc), []
    seat0 = eng.refs[0].copy()
    lines = [eng.step() for _ in range(eng.n_ticks)]
    assert assert_every_plan_certified(lines) >= 1
    (_, p), *_ = events(lines, "RECOVERY_LEVEL")
    assert p["cripple"]["sat_id"] == 0  # both options were built and reported
    assert any("cripple" in r["why"] for r in p["rejected"]) or p["cripple"]["dv_with_mps"]
    print("\ncripple report", json.dumps(p["cripple"]), p["level"])
    # the cripple never gets a new seat: its reference is the slot it started on, advanced
    assert np.allclose(eng.refs[0], propagate(seat0, (eng.n_ticks) * sc.dt_s, eng.n), atol=1e-3)
    assert "leader" in lines[-1]["sats"][0]["roles"]  # its radio works: it stays leader


def test_zero_fuel_holds_and_flags():
    lines = run_log(ladder_scn(orbits=2.2, spacecraft={"m_prop_kg": 0.0}))
    (_, p), = events(lines, "RECOVERY_LEVEL")  # all six report FUEL_DEPLETED at t = 0
    assert p["level"] in ("L1", "L4") and p["dv_planned_mps"] == 0.0
    whys = {r["level"]: r["why"] for r in p["rejected"]}
    assert whys["L2"] == whys["L3"] == "no sat can thrust and be commanded"
    assert assert_every_plan_certified(lines) == 1
    assert max(s["dv_used"] for s in lines[-2]["sats"]) == 0.0


class _CountdownEvent(threading.Event):
    """is_set() turns True after `n` calls: lands inside the certificate, past the run loop."""

    def __init__(self, n):
        super().__init__()
        self.left = n

    def is_set(self):
        self.left -= 1
        return self.left < 0


def test_cancel_inside_the_ladder_raises_run_cancelled_without_output():
    sc = ladder_scn(failures=DEAD_1_5)
    ticks_to_plan = round(606.0 / sc.dt_s)  # one is_set() per tick before the planning tick
    out = []
    with pytest.raises(RunCancelled) as info:
        for line in EngineV2(sc).run(_CountdownEvent(ticks_to_plan + 500)):
            out.append(line)
    assert isinstance(info.value.__cause__, CertificateCancelled)
    assert out[-1]["t"] == 604.0  # nothing of the planning tick was yielded


def _manual_move(sc, ticks=10):
    """Engine past its own L1 plan for a dead sat 1, then a hand-built certified-path move of
    the five live sats onto a 5-seat ring, executed by the engine's executor."""
    eng = EngineV2(sc)
    for _ in range(ticks):
        eng.step()
    state = swarm_state_from_engine(eng)
    c = state.chief
    lvlh = truth.eci_to_lvlh(state.sat_eci[:, :3], state.sat_eci[:, 3:], c[:3], c[3:])
    live = [0, 2, 3, 4, 5]
    pool = mv.ring(2000.0, 0.4, 0.0, 5, eng.n)
    asg, _ = mv.assign(lvlh, live, [propagate(s, state.t_s, eng.n) for s in pool])
    targets = {i: pool[j] for i, j in asg.items()}
    ctx = type("C", (), {"n": eng.n, "dt": sc.dt_s, "scenario": sc, "landing_tol_m": 50.0})
    trs = mv.transfers(ctx, state, lvlh, targets, [lvlh[1]], 500.0)
    assert isinstance(trs, dict) and trs
    plan = Plan(tuple(PlanItem(i, trs.get(i), s, tuple(state.roles[i]))
                      for i, s in targets.items()), "L3", state.t_s)
    seats = np.array(state.refs)
    for i, s in targets.items():
        seats[i] = propagate(s, state.t_s, eng.n)
    eng.rec._execute(eng, plan)
    return eng, state, seats, trs


def test_executor_flies_exactly_what_the_certificate_simulated():
    sc = ladder_scn(failures=[{"t": 0.0, "sat_id": 1, "mode": "DEAD"}])
    eng, state, seats, trs = _manual_move(sc)
    steps = round(1.2 * 2.0 * math.pi / eng.n / sc.dt_s)
    res = simulate(sc, state, seats, trs, steps)
    for _ in range(steps):
        eng.step()
    err = float(np.abs(eng.X - res.final_eci).max())
    print(f"\nexecutor vs certificate after {steps} steps: {err:.3e} m (ECI, max component)")
    assert err < 1e-6


def test_snapshot_mid_burn_restores_to_the_same_log():
    sc = ladder_scn(failures=[{"t": 0.0, "sat_id": 1, "mode": "DEAD"}])
    eng, *_ = _manual_move(sc)
    for _ in range(40):
        eng.step()
    assert eng.rec.burns and eng.k - eng.rec.k0 < max(last for _, last in eng.rec.burns.values())
    blob = eng.snapshot()
    a = [eng.step() for _ in range(300)]
    other = EngineV2(sc)
    other.restore(blob)
    b = [other.step() for _ in range(300)]
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_inject_at_t_equals_a_fresh_run_with_that_injection_and_runs_twice_identically():
    sc = ladder_scn(orbits=1.0)
    live = EngineV2(sc)
    lines = [live.header()]
    while live.k < live.n_ticks:
        if live.k == 300:
            live.inject(Failure(t=600.0, sat_id=2, mode="DEAD"))
        lines.append(live.step())
    fresh = run_log(sc, live.injections)
    again = run_log(sc, live.injections)
    assert json.dumps(lines[1:], sort_keys=True) == json.dumps(fresh[1:-1], sort_keys=True)
    assert json.dumps(fresh, sort_keys=True) == json.dumps(again, sort_keys=True)
    assert assert_every_plan_certified(fresh) == 1
