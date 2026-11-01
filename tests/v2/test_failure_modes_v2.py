"""Failure modes as resource damage (Phase 2, Task 2.3): one semantics test per mode."""

import json
import math
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from cubesat.coverage import coverage_fraction, footprint_radius, target_grid
from cubesat.scenario import FailureMode, Scenario
from cubesat.sim import build_slots
from cubesat.sim_v2 import EngineV2
from cubesat.spacecraft import G0, SatState, apply_failure, thrust_limited

DT = 2.0
BIG = np.array([1.0, 0.0, 0.0])  # a command far above any cap, m/s^2


def _scn_dict(**kw):
    root = Path(__file__).resolve().parents[2]
    return {**json.loads((root / "data/scenarios/nominal.json").read_text()), **kw}


# --- failure modes as resource damage --------------------------------------------------------
VEC = np.array([0.0, 3.0, 4.0])


@pytest.mark.parametrize(
    "mode, k, payload_ok, radio_ok",
    [("DEAD", 0.0, False, False), ("EPS_DEGRADE", 0.0, False, False),  # fade ends in death
     ("THRUSTER_OUT", 0.0, True, True)],
)
def test_mode_flag_semantics_dead_eps_degrade_thruster_out(mode, k, payload_ok, radio_ok):
    sat = SatState()
    apply_failure(sat, FailureMode(mode))
    assert (sat.k, sat.payload_ok, sat.radio_ok, sat.stuck_vec) == (k, payload_ok, radio_ok, None)
    assert not thrust_limited(sat, BIG, DT)[0].any()


def test_mode_PARTIAL_THRUST_semantics():
    sat = SatState()
    apply_failure(sat, FailureMode.PARTIAL_THRUST)
    assert sat.k == 0.5 and sat.payload_ok and sat.radio_ok
    a, _ = thrust_limited(sat, BIG, DT)
    assert np.linalg.norm(a) == pytest.approx(0.005, rel=1e-12)  # half the max acceleration


def test_mode_PAYLOAD_FAIL_semantics():
    sat = SatState()
    apply_failure(sat, FailureMode.PAYLOAD_FAIL)
    assert not sat.payload_ok and sat.radio_ok and sat.k == 1.0  # still flies, still thrusts
    assert np.linalg.norm(thrust_limited(sat, BIG, DT)[0]) == pytest.approx(0.01)


def test_mode_RADIO_FAIL_semantics():
    sat = SatState()
    apply_failure(sat, FailureMode.RADIO_FAIL)
    assert not sat.radio_ok and sat.payload_ok and sat.k == 1.0  # alive and flying
    assert np.linalg.norm(thrust_limited(sat, BIG, DT)[0]) == pytest.approx(0.01)


def test_mode_THRUSTER_STUCK_OPEN_semantics():
    with pytest.raises(ValueError, match="stuck_vec"):
        apply_failure(SatState(), FailureMode.THRUSTER_STUCK_OPEN)
    sat = SatState(m_prop_kg=0.01)
    apply_failure(sat, FailureMode.THRUSTER_STUCK_OPEN, VEC)
    assert np.linalg.norm(sat.stuck_vec) == pytest.approx(1.0)  # stored as a unit ECI vector
    a, dm = thrust_limited(sat, np.zeros(3), DT)  # the command is ignored
    assert np.allclose(a, VEC / 5.0 * 0.04 / 4.0, rtol=1e-12)  # constant F_max / m along stuck_vec
    assert dm == pytest.approx(0.04 * DT / (40.0 * G0), rel=1e-12)
    m = sat.m_kg
    a2, _ = thrust_limited(sat, -BIG, DT)  # a different command changes nothing
    assert np.allclose(a2, VEC / 5.0 * 0.04 / m, rtol=1e-12)
    n, last = 0, a2
    while not sat.depleted and n < 10_000:  # stops when the propellant is empty
        last = thrust_limited(sat, np.zeros(3), DT)[0]
        n += 1
    assert sat.depleted and n < 10_000 and last.any() and sat.m_prop_kg == 0.0
    assert not thrust_limited(sat, np.zeros(3), DT)[0].any()  # valve stuck open, tank dry


@pytest.mark.parametrize(
    "mode", ["PAYLOAD_FAIL", "PARTIAL_THRUST", "THRUSTER_STUCK_OPEN", "RADIO_FAIL"]
)
def test_v1_scenarios_with_v2_modes_are_rejected_with_a_plain_message(mode):
    fail = [{"t": 10.0, "sat_id": 1, "mode": mode}]
    with pytest.raises(ValidationError, match=f'{mode}.*engine "v2"'):
        Scenario.model_validate(_scn_dict(failures=fail))  # engine defaults to v1
    assert Scenario.model_validate(_scn_dict(failures=fail, engine="v2")).failures[0].mode == mode


def test_v1_modes_still_valid_in_v1():
    fail = [{"t": 1.0, "sat_id": i, "mode": m} for i, m in enumerate(["DEAD", "THRUSTER_OUT"])]
    assert Scenario.model_validate(_scn_dict(failures=fail)).engine == "v1"


# --- engine level (EngineV2) -----------------------------------------------------------------
SMALL_SENSOR = {"fov_half_angle_deg": 1.5, "grid_step_km": 5.0, "grid_extent_km": 5.0}


def _scn(small_sensor=True, **kw) -> Scenario:
    extra = {"sensor": SMALL_SENSOR} if small_sensor else {}
    return Scenario.model_validate(_scn_dict(engine="v2", **extra, **kw))


def _displaced(s: Scenario):
    """Start states with sat 1 pushed off its slot so the PD command saturates."""
    probe = EngineV2(s)
    start = np.array(build_slots(s, probe.n))
    start[1, :3] += [-500.0, 300.0, -200.0]
    return start


def _events(lines, kind):
    return [(x["t"], e) for x in lines for e in x.get("events", []) if e["type"] == kind]


def _track(lines, i):
    return {x["t"]: x["sats"][i] for x in lines if "sats" in x}


def test_payload_failed_sat_excluded_from_coverage_but_still_seat_holds():
    s = _scn(
        small_sensor=False,
        duration_s=60.0,
        failures=[{"t": 0.0, "sat_id": 1, "mode": "PAYLOAD_FAIL"}],
        truth={"j2_enabled": False, "density_factor": 0.0},
    )
    start = _displaced(s)
    lines = list(EngineV2(s, initial_lvlh=start).run())
    first = lines[1]
    grid = target_grid(s.sensor.grid_step_km * 1e3, s.sensor.grid_extent_km * 1e3)
    r_f = footprint_radius(500e3, math.radians(s.sensor.fov_half_angle_deg))
    yz = {i: first["sats"][i]["r"][1:] for i in range(6)}
    without = coverage_fraction([yz[i] for i in (2, 3, 4)], grid, r_f)
    with_it = coverage_fraction([yz[i] for i in (1, 2, 3, 4)], grid, r_f)
    refilled = coverage_fraction([yz[i] for i in (0, 2, 3, 4)], grid, r_f)
    assert without < with_it  # the failed imager's footprint matters in this geometry
    # Phase 5a: the lost seat is refilled by the leader-only sat 0 (label change, no motion);
    # the failed payload itself still takes no images and sat 1 no longer holds the role
    assert "imager" not in first["sats"][1]["roles"]
    assert first["sats"][0]["roles"] == ["imager", "leader"]
    assert first["coverage"] == refilled
    assert first["sats"][1]["status"] == "PAYLOAD_FAILED"
    base = list(
        EngineV2(
            Scenario.model_validate({**s.model_dump(), "failures": []}), initial_lvlh=start
        ).run()
    )
    ta, tb = _track(lines, 1), _track(base, 1)
    assert all(ta[t]["r"] == tb[t]["r"] and ta[t]["v"] == tb[t]["v"] for t in ta)  # seat-held
    assert ta[58.0]["dv_used"] == tb[58.0]["dv_used"] > 0.5  # still flies and thrusts


def test_radio_failed_sat_keeps_flying_and_is_declared_by_the_heartbeat_rule():
    """K=3, dt=2: RADIO_FAIL at t=100 is declared at t=104 (misses 100, 102, 104); the sat's
    trajectory is bit-identical to the no-failure run (it never stops holding its seat)."""
    base = dict(duration_s=300.0)
    fail = [{"t": 100.0, "sat_id": 2, "mode": "RADIO_FAIL"}]
    a = list(EngineV2(_scn(**base, failures=fail)).run())
    b = list(EngineV2(_scn(**base)).run())
    ((t, e),) = _events(a, "FAILURE_DETECTED")
    assert t == 104.0 and e["payload"]["sat_id"] == 2 and e["payload"]["mode"] == "RADIO_FAIL"
    assert e["payload"]["t_fail"] == 100.0 and "self_report" not in e["payload"]
    ta, tb = _track(a, 2), _track(b, 2)
    assert ta[98.0]["status"] == "NOMINAL" and ta[100.0]["status"] == "RADIO_SILENT"
    assert ta[100.0]["radio_ok"] is False and ta[98.0]["radio_ok"] is True
    assert all(ta[t]["r"] == tb[t]["r"] and ta[t]["v"] == tb[t]["v"] for t in ta)  # on track
    assert ta[300.0]["dv_used"] == tb[300.0]["dv_used"]


def test_partial_thrust_halves_the_engine_max_acceleration():
    kw = dict(
        formation={"n_slots": 2, "radial_amp_km": 1.0, "phase_offset_deg": 0.0},
        roles=["leader", "imager"],
        duration_s=10.0,
        truth={"j2_enabled": False, "density_factor": 0.0},
    )
    s = _scn(**kw)
    s_half = _scn(**kw, failures=[{"t": 0.0, "sat_id": 1, "mode": "PARTIAL_THRUST"}])
    start = _displaced(s)
    half_eng = EngineV2(s_half, initial_lvlh=start)
    half_eng.step()
    half = half_eng.step()["sats"][1]  # dv_used after one burn step
    full = EngineV2(s, initial_lvlh=start)
    full.step()
    full = full.step()["sats"][1]
    assert full["dv_used"] == pytest.approx(0.01 * 2.0, rel=1e-12)
    assert half["dv_used"] == pytest.approx(0.005 * 2.0, rel=1e-12)
    assert half["status"] == "DEGRADED"


def test_stuck_open_burns_constant_thrust_ignores_the_pd_and_stops_when_the_tank_empties():
    s = _scn(
        duration_s=60.0,
        truth={"j2_enabled": False, "density_factor": 0.0},
        spacecraft={"m_prop_kg": 0.002},  # 0.002 / (0.04 / (40 g0)) = 19.6 s of burn
        failures=[{"t": 0.0, "sat_id": 1, "mode": "THRUSTER_STUCK_OPEN"}],
    )
    lines = list(EngineV2(s).run())
    track = _track(lines, 1)
    dv = [track[t]["dv_used"] for t in sorted(track)]
    steps = np.diff(dv)  # dv[k] is the total before the burn of tick k
    assert track[0.0]["status"] == "DEGRADED"
    assert steps[0] == pytest.approx(0.01 * 2.0, rel=1e-3)  # constant F_max / m
    burn = [i for i, d in enumerate(steps) if d > 0]
    assert burn == list(range(len(burn))) and 8 <= len(burn) <= 11  # contiguous, ~9.8 steps
    assert steps[burn[-1]] < steps[burn[-2]] and not steps[len(burn) :].any()  # truncated step
    assert dv[-1] == dv[len(burn)]  # no thrust after the propellant is empty
    assert dv[-1] == pytest.approx(40.0 * G0 * math.log(4.0 / 3.998), rel=1e-3)  # whole tank
    other = _track(lines, 3)  # an unaffected sat is not stuck
    assert other[58.0]["status"] == "NOMINAL"


def test_self_reported_and_silent_modes():
    """PAYLOAD_FAIL self-reports at once (radio works); PARTIAL_THRUST and THRUSTER_STUCK_OPEN
    raise no event (only a motion residual can see them, Phase 4); a radio-failed sat cannot
    self-report a later THRUSTER_OUT, the heartbeat rule declares it."""
    s = _scn(
        duration_s=120.0,
        failures=[
            {"t": 10.0, "sat_id": 1, "mode": "PAYLOAD_FAIL"},
            {"t": 10.0, "sat_id": 2, "mode": "PARTIAL_THRUST"},
            {"t": 10.0, "sat_id": 3, "mode": "THRUSTER_STUCK_OPEN"},
            {"t": 20.0, "sat_id": 4, "mode": "RADIO_FAIL"},
            {"t": 30.0, "sat_id": 4, "mode": "THRUSTER_OUT"},
        ],
    )
    lines = list(EngineV2(s).run())
    got = [(t, e["payload"]["sat_id"], e["payload"].get("self_report")) for t, e in
           _events(lines, "FAILURE_DETECTED")]
    assert got == [(10.0, 1, True), (24.0, 4, None)]  # sat 4: silent from t=20, K=3 misses
    assert _track(lines, 4)[100.0]["status"] == "RADIO_SILENT"  # label stays the higher rank
    assert _track(lines, 2)[100.0]["status"] == _track(lines, 3)[100.0]["status"] == "DEGRADED"


# --- a benign self-report must not hide a later fatal failure (review fix A1) -------------------
def _detections(lines):
    return [
        (t, e["payload"]["sat_id"], e["payload"]["mode"], e["payload"].get("self_report"))
        for t, e in _events(lines, "FAILURE_DETECTED")
    ]


def test_self_report_then_eps_fade_death_is_still_declared():
    s = _scn(
        duration_s=500.0,
        failures=[
            {"t": 400.0, "sat_id": 0, "mode": "EPS_DEGRADE", "degrade_s": 100.0},
            {"t": 100.0, "sat_id": 0, "mode": "PAYLOAD_FAIL"},
        ],
    )
    lines = list(EngineV2(s).run())
    assert _detections(lines) == [
        (100.0, 0, "PAYLOAD_FAIL", True),
        (404.0, 0, "EPS_DEGRADE", None),  # DEAD at 400, K=3 misses
    ]
    assert lines[-2]["state"] == "FAILURE_DETECTED"


def test_payload_then_radio_then_dead_declares_the_silence():
    s = _scn(
        duration_s=100.0,
        failures=[
            {"t": 20.0, "sat_id": 0, "mode": "PAYLOAD_FAIL"},
            {"t": 30.0, "sat_id": 0, "mode": "RADIO_FAIL"},
            {"t": 60.0, "sat_id": 0, "mode": "DEAD"},
        ],
    )
    assert _detections(list(EngineV2(s).run())) == [
        (20.0, 0, "PAYLOAD_FAIL", True),
        (34.0, 0, "RADIO_FAIL", None),  # silent from 30, K=3 misses
    ]


def test_thruster_out_then_dead_declares_the_death():
    s = _scn(
        duration_s=150.0,
        failures=[
            {"t": 50.0, "sat_id": 0, "mode": "THRUSTER_OUT"},
            {"t": 100.0, "sat_id": 0, "mode": "DEAD"},
        ],
    )
    assert _detections(list(EngineV2(s).run())) == [
        (50.0, 0, "THRUSTER_OUT", True),
        (104.0, 0, "DEAD", None),
    ]
