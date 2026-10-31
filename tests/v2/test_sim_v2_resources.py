"""Resources wired into EngineV2 (Phase 2, Task 2.4): fuel in the loop, log keys, FUEL_DEPLETED.
Defaults are illustrative: 4.0 kg wet, 0.2 kg propellant, Isp 40 s, F_max 0.04 N."""

import json
import math
from pathlib import Path

import numpy as np
import pytest

from cubesat.coverage import coverage_fraction, footprint_radius, target_grid
from cubesat.scenario import Failure, Scenario
from cubesat.sim import build_slots, run_scenario
from cubesat.sim_v2 import EngineV2
from cubesat.spacecraft import G0

ROOT = Path(__file__).resolve().parents[2]
NOMINAL = json.loads((ROOT / "data" / "scenarios" / "nominal.json").read_text())
SMALL_SENSOR = {"fov_half_angle_deg": 1.5, "grid_step_km": 5.0, "grid_extent_km": 5.0}
NO_ENV = {"j2_enabled": False, "density_factor": 0.0}  # only thrust moves the sats


def _scn(small_sensor=True, **kw) -> Scenario:
    extra = {"sensor": SMALL_SENSOR} if small_sensor else {}
    return Scenario.model_validate({**NOMINAL, "engine": "v2", **extra, **kw})


def _displaced(s: Scenario, sat=1):
    """Start states with `sat` pushed off its slot so its PD command saturates."""
    start = np.array(build_slots(s, EngineV2(s).n))
    start[sat, :3] += [-500.0, 300.0, -200.0]
    return start


def _events(lines, kind):
    return [(x["t"], e) for x in lines if "events" in x for e in x["events"] if e["type"] == kind]


def _track(lines, i):
    return {x["t"]: x["sats"][i] for x in lines if "sats" in x}


def test_log_carries_fuel_keys_and_v1_does_not():
    line = EngineV2(_scn()).step()["sats"][0]
    assert line["fuel_kg"] == 0.2 and line["k"] == 1.0
    assert line["fuel_mps_left"] == pytest.approx(40.0 * G0 * math.log(4.0 / 3.8), abs=1e-9)
    v1 = run_scenario(Scenario.model_validate({**NOMINAL, "duration_s": 10.0}))
    assert set(v1[1]["sats"][0]) == {"id", "role", "status", "r", "v", "dv_used"}


def test_fuel_never_negative_and_depleted_status_and_event_once():
    s = _scn(duration_s=400.0, spacecraft={"m_prop_kg": 0.0005}, truth=NO_ENV)  # 0.49 m/s tank
    lines = list(EngineV2(s, initial_lvlh=_displaced(s)).run())
    track = _track(lines, 1)
    fuel = [track[t]["fuel_kg"] for t in sorted(track)]
    assert min(fuel) >= 0.0 and fuel[-1] == 0.0 and fuel[0] == 0.0005
    first = next(t for t in sorted(track) if track[t]["fuel_kg"] == 0.0)
    assert track[first]["status"] == "FUEL_DEPLETED"
    assert track[first - 2.0]["status"] == "NOMINAL"
    assert track[first]["k"] == 0.0 and track[first - 2.0]["k"] == 1.0  # k = 0 at depletion
    det = [(t, e["payload"]) for t, e in _events(lines, "FAILURE_DETECTED")]
    assert det == [
        (first, {"sat_id": 1, "mode": "FUEL_DEPLETED", "t_fail": first, "t_detect": first,
                 "self_report": True})
    ]  # self-reported once, like THRUSTER_OUT
    assert next(x for x in lines if x.get("t") == first)["state"] == "FAILURE_DETECTED"
    assert next(x for x in lines if x.get("t") == first - 2.0)["state"] == "NOMINAL"
    ev = [(t, e) for t, e in _events(lines, "FUEL_DEPLETED") if e["payload"]["sat_id"] == 1]
    assert [t for t, _ in ev] == [first]  # once, on the first tick the tank reads empty
    assert track[first]["dv_used"] == track[400.0]["dv_used"]  # no thrust afterwards
    assert track[400.0]["dv_used"] == pytest.approx(40.0 * G0 * math.log(4.0 / 3.9995), rel=1e-3)
    assert track[400.0]["fuel_mps_left"] == 0.0
    assert track[first]["r"] != track[400.0]["r"]  # it still flies (coasts)


def test_zero_fuel_at_start_does_not_crash_and_coasts_unreported_seats():
    """Review Focus: m_prop 0 -> every sat FUEL_DEPLETED at t=0, no seat correction (the run is
    bit-identical to a run where every thruster is out), no crash, reported once each."""
    s = _scn(duration_s=120.0, spacecraft={"m_prop_kg": 0.0}, truth=NO_ENV)
    out_all = [{"t": 0.0, "sat_id": i, "mode": "THRUSTER_OUT"} for i in range(6)]
    ref = _scn(duration_s=120.0, failures=out_all, truth=NO_ENV)
    start = _displaced(s)
    a = list(EngineV2(s, initial_lvlh=start).run())
    b = list(EngineV2(ref, initial_lvlh=start).run())
    ticks_a, ticks_b = [x for x in a if "sats" in x], [x for x in b if "sats" in x]
    assert all(
        sa["r"] == sb["r"] and sa["v"] == sb["v"]
        for xa, xb in zip(ticks_a, ticks_b, strict=True)
        for sa, sb in zip(xa["sats"], xb["sats"], strict=True)
    )
    assert ticks_a[-1]["sats"][1]["dv_used"] == 0.0
    assert {s_["status"] for s_ in ticks_a[0]["sats"]} == {"FUEL_DEPLETED"}
    assert sorted(e["payload"]["sat_id"] for _, e in _events(a, "FUEL_DEPLETED")) == list(range(6))
    assert all(t == 0.0 for t, _ in _events(a, "FUEL_DEPLETED"))
    assert ticks_a[0]["sats"][0]["fuel_mps_left"] == 0.0


def test_all_but_one_fuel_depleted_the_survivor_still_holds_its_seat():
    s = _scn(duration_s=100.0, truth=NO_ENV)
    start = _displaced(s, sat=1)
    eng = EngineV2(s, initial_lvlh=start)
    for i in (0, 2, 3, 4, 5):
        eng.faults.sats[i].m_prop_kg = 0.0
    lines = list(eng.run())
    last = lines[-2]["sats"]
    assert [x["status"] for x in last] == ["FUEL_DEPLETED"] + ["NOMINAL"] + ["FUEL_DEPLETED"] * 4
    assert last[1]["dv_used"] > 0.5 and last[1]["fuel_kg"] < 0.2  # sat 1 burned
    assert all(last[i]["dv_used"] == 0.0 for i in (0, 2, 3, 4, 5))
    assert len(_events(lines, "FUEL_DEPLETED")) == 5


def test_propellant_exactly_exhausted_mid_burn_truncates_that_step():
    s = _scn(duration_s=20.0, spacecraft={"m_prop_kg": 1e-4}, truth=NO_ENV)
    lines = list(EngineV2(s, initial_lvlh=_displaced(s)).run())
    track = _track(lines, 1)
    assert track[0.0]["fuel_kg"] == 1e-4 and track[2.0]["fuel_kg"] == 0.0  # emptied by tick 0
    full = 0.01 * 2.0  # a full-thrust step
    frac = 1e-4 / (0.04 * 2.0 / (40.0 * G0))  # tank / one full step of propellant
    assert 0.0 < frac < 1.0
    assert track[2.0]["dv_used"] == pytest.approx(full * frac, rel=1e-9)  # the clipped dv
    assert track[2.0]["dv_used"] == pytest.approx(40.0 * G0 * math.log(4.0 / 3.9999), rel=1e-4)
    assert track[18.0]["dv_used"] == track[2.0]["dv_used"]
    assert track[2.0]["status"] == "FUEL_DEPLETED"


def test_imager_in_a_fuel_depleted_sat_still_counts_for_coverage():
    s = _scn(small_sensor=False, duration_s=10.0, spacecraft={"m_prop_kg": 0.0})
    line = EngineV2(s).step()
    assert {x["status"] for x in line["sats"]} == {"FUEL_DEPLETED"}
    grid = target_grid(s.sensor.grid_step_km * 1e3, s.sensor.grid_extent_km * 1e3)
    r_f = footprint_radius(500e3, math.radians(s.sensor.fov_half_angle_deg))
    imagers = [i for i, r in enumerate(s.roles) if r == "imager"]
    want = coverage_fraction([line["sats"][i]["r"][1:] for i in imagers], grid, r_f)
    assert want > 0.0 and line["coverage"] == want  # it flies, the camera works


def _resource_scn():
    return _scn(
        duration_s=300.0,
        spacecraft={"m_prop_kg": 0.002},
        failures=[
            {"t": 40.0, "sat_id": 2, "mode": "PARTIAL_THRUST"},
            {"t": 60.0, "sat_id": 3, "mode": "THRUSTER_STUCK_OPEN"},
            {"t": 80.0, "sat_id": 4, "mode": "PAYLOAD_FAIL"},
            {"t": 100.0, "sat_id": 5, "mode": "RADIO_FAIL"},
        ],
    )


def test_v2_with_resources_twice_byte_identical():
    s = _resource_scn()
    a = json.dumps(list(EngineV2(s, initial_lvlh=_displaced(s)).run()), sort_keys=True)
    b = json.dumps(list(EngineV2(s, initial_lvlh=_displaced(s)).run()), sort_keys=True)
    assert a == b


@pytest.mark.parametrize("ticks", [35, 60])
def test_snapshot_restore_carries_fuel_state(ticks):
    """35: sat 3 is stuck open and burning (its tank empties after the snapshot); 60: every
    failure has fired, sat 3 is already empty."""
    s = _resource_scn()
    start = _displaced(s)
    a = EngineV2(s, initial_lvlh=start)
    for _ in range(ticks):
        a.step()
    blob = a.snapshot()
    tail_a = list(a.run())
    b = EngineV2(s, initial_lvlh=start)
    b.restore(blob)
    saved = [sat.to_dict() for sat in b.faults.sats]
    assert saved[1]["m_prop_kg"] < 0.002 and saved[1]["m_kg"] < 4.0  # burned before the snapshot
    assert saved[3]["stuck_vec"] is not None and saved[2]["k"] == 0.5
    assert [x["radio_ok"] for x in saved][5] is (ticks < 50)
    assert [x["payload_ok"] for x in saved][4] is (ticks < 40)
    assert b.faults.fuel_out == a_fuel_out(blob)
    assert json.dumps(tail_a, sort_keys=True) == json.dumps(list(b.run()), sort_keys=True)
    # sat 3's tank empties at t = 60 + ~20 s: reported before the snapshot at 60, after at 35
    assert (len(_events(tail_a, "FUEL_DEPLETED")) >= 1) is (ticks == 35)


def a_fuel_out(blob):
    return json.loads(blob)["state"]["faults"]["fuel_out"]


def test_inject_partial_and_stuck_open_replays_identically():
    s = _scn(duration_s=200.0, spacecraft={"m_prop_kg": 0.002})
    start = _displaced(s)
    live = EngineV2(s, initial_lvlh=start)
    lines = [live.header()]
    for k in range(101):
        if k == 20:
            live.inject(Failure(t=0.0, sat_id=1, mode="PARTIAL_THRUST"))  # clamps to now
        if k == 50:
            live.inject(Failure(t=0.0, sat_id=3, mode="THRUSTER_STUCK_OPEN"))
        lines.append(live.step())
    lines += list(live.run())  # resumes at tick 101: no second header
    assert [(f.t, f.mode.value) for f in live.injections] == [
        (40.0, "PARTIAL_THRUST"),
        (100.0, "THRUSTER_STUCK_OPEN"),
    ]
    replay = list(EngineV2(s, live.injections, initial_lvlh=start).run())
    assert json.dumps(lines, sort_keys=True) == json.dumps(replay, sort_keys=True)
    track = _track(lines, 3)
    assert track[100.0]["status"] == "DEGRADED" and track[198.0]["status"] == "FUEL_DEPLETED"


def test_zero_fuel_start_is_announced_at_t0_with_k_zero():
    s = _scn(duration_s=10.0, spacecraft={"m_prop_kg": 0.0})
    lines = list(EngineV2(s).run())
    first = lines[1]
    assert first["state"] == "FAILURE_DETECTED" and first["t"] == 0.0
    assert [x["k"] for x in first["sats"]] == [0.0] * 6
    got = sorted(e["payload"]["sat_id"] for _, e in _events(lines, "FAILURE_DETECTED"))
    assert got == list(range(6))  # each sat announces once, nothing repeats


def test_radio_silent_sat_that_runs_dry_stays_silent_and_announces_nothing():
    s = _scn(
        duration_s=60.0,
        failures=[{"t": 0.0, "sat_id": 1, "mode": "RADIO_FAIL"}],
        spacecraft={"m_prop_kg": 0.0005},
    )
    lines = list(EngineV2(s, initial_lvlh=_displaced(s)).run())
    track = _track(lines, 1)
    assert track[0.0]["status"] == track[58.0]["status"] == "RADIO_SILENT"  # label not lowered
    assert track[58.0]["fuel_kg"] == 0.0 and track[58.0]["k"] == 0.0
    mine = [e for _, e in _events(lines, "FUEL_DEPLETED") if e["payload"]["sat_id"] == 1]
    assert mine == []  # a silent sat cannot self-report
    det = [(t, e["payload"]["mode"]) for t, e in _events(lines, "FAILURE_DETECTED")
           if e["payload"]["sat_id"] == 1]
    assert det == [(4.0, "RADIO_FAIL")]  # only the heartbeat rule speaks for it


def test_depleted_then_dead_is_still_declared():
    s = _scn(
        duration_s=300.0,
        spacecraft={"m_prop_kg": 0.0005},
        failures=[{"t": 200.0, "sat_id": 1, "mode": "DEAD"}],
    )
    lines = list(EngineV2(s, initial_lvlh=_displaced(s)).run())
    det = [(e["payload"]["mode"], e["payload"].get("self_report"))
           for _, e in _events(lines, "FAILURE_DETECTED") if e["payload"]["sat_id"] == 1]
    assert det == [("FUEL_DEPLETED", True), ("DEAD", None)]


@pytest.mark.parametrize(
    "mode", ["PAYLOAD_FAIL", "PARTIAL_THRUST", "THRUSTER_STUCK_OPEN", "RADIO_FAIL"]
)
def test_live_inject_of_every_v2_mode_equals_replay_of_recorded_injections(mode):
    s = _scn(duration_s=200.0, spacecraft={"m_prop_kg": 0.002})
    start = _displaced(s)
    live = EngineV2(s, initial_lvlh=start)
    lines = [live.header()]
    for k in range(101):
        if k == 30:
            live.inject(Failure(t=0.0, sat_id=1, mode=mode))
        lines.append(live.step())
    lines += list(live.run())
    replay = list(EngineV2(s, live.injections, initial_lvlh=start).run())
    assert json.dumps(lines, sort_keys=True) == json.dumps(replay, sort_keys=True)
    assert [(f.t, f.mode.value) for f in live.injections] == [(60.0, mode)]
