"""Phase 5a.3: roles in the v2 log, ROLE_HANDOFF events, no motion change, snapshot/restore."""

import json
from pathlib import Path

import numpy as np
import pytest

from cubesat.canon import canonical_log_hash
from cubesat.coverage import coverage_fraction, footprint_radius, target_grid
from cubesat.scenario import Failure, Scenario
from cubesat.sim import run_scenario
from cubesat.sim_v2 import EngineV2, run_scenario_v2

ROOT = Path(__file__).resolve().parents[2]
NOMINAL = json.loads((ROOT / "data" / "scenarios" / "nominal.json").read_text())
SENSOR = {"fov_half_angle_deg": 1.5, "grid_step_km": 5.0, "grid_extent_km": 5.0}
# Phase-2 engine (merge-base af45148) canonical hash of every (r, v, dv_used) of this run
PHASE2_MOTION_PIN = "4b8351a853a8de30c8b05d9ae3049f62cfe0135708bb96d09cba0e5786605374"
FAILS = [
    {"t": 100.0, "sat_id": 0, "mode": "DEAD"},
    {"t": 200.0, "sat_id": 5, "mode": "RADIO_FAIL"},
    {"t": 300.0, "sat_id": 2, "mode": "PAYLOAD_FAIL"},
    {"t": 400.0, "sat_id": 3, "mode": "THRUSTER_OUT"},
]


def _scn(failures=(), **kw) -> Scenario:
    d = {**NOMINAL, "engine": "v2", "duration_s": 600.0, "sensor": SENSOR, "failures": failures}
    return Scenario.model_validate({**d, **kw})


def _ticks(lines):
    return [x for x in lines if "sats" in x]


def _handoffs(lines):
    return [
        (x["t"], e["payload"])
        for x in _ticks(lines)
        for e in x.get("events", [])
        if e["type"] == "ROLE_HANDOFF"
    ]


def test_roles_keys_in_v2_lines_and_absent_in_v1():
    lines = _ticks(run_scenario_v2(_scn(duration_s=20.0)))
    for s, orig in zip(lines[0]["sats"], NOMINAL["roles"], strict=True):
        assert s["roles"] == [orig] and s["role"] == orig and s["original_role"] == orig
    v1 = _ticks(run_scenario(Scenario.model_validate({**NOMINAL, "duration_s": 20.0})))
    assert all({"roles", "original_role"}.isdisjoint(s) for x in v1 for s in x["sats"])


def test_dead_sat_shows_no_role_but_keeps_original_role():
    lines = _ticks(run_scenario_v2(_scn(FAILS[:1], duration_s=200.0)))
    s0 = lines[-1]["sats"][0]
    assert (s0["roles"], s0["role"], s0["original_role"]) == ([], "none", "leader")
    s1 = lines[-1]["sats"][1]  # the leader moved to the lowest imager and stacks on it
    assert s1["roles"] == ["imager", "leader"] and s1["role"] == "leader"  # display order


def test_motion_is_byte_identical_to_the_phase2_engine():
    lines = _ticks(run_scenario_v2(_scn(FAILS)))
    motion = [
        {"t": x["t"], "s": [(s["r"], s["v"], s["dv_used"]) for s in x["sats"]]} for x in lines
    ]
    assert canonical_log_hash(motion) == PHASE2_MOTION_PIN


def _independent_coverage(lines, scn):
    """The Phase-2 rule: scenario imagers that are not dead/re-entered and have a payload."""
    r_f = footprint_radius(scn.chief.altitude_km * 1e3, np.radians(scn.sensor.fov_half_angle_deg))
    grid = target_grid(scn.sensor.grid_step_km * 1e3, scn.sensor.grid_extent_km * 1e3)
    out = []
    for x in lines:
        ids = [
            s["id"]
            for s in x["sats"]
            if s["original_role"] == "imager"
            and s["status"] not in ("DEAD", "REENTERED")
            and s["payload_ok"]
        ]
        pos = np.array([x["sats"][i]["r"][1:3] for i in ids]).reshape(-1, 2)
        out.append(coverage_fraction(pos, grid, r_f))
    return out


@pytest.mark.parametrize("failures", [[], [FAILS[0], FAILS[2], FAILS[3]]])
def test_coverage_reproduces_the_phase2_rule(failures):
    scn = _scn(failures)
    lines = _ticks(run_scenario_v2(scn))
    assert [x["coverage"] for x in lines] == _independent_coverage(lines, scn)


def test_handoff_when_the_leader_dies_and_not_for_imager_changes():
    lines = run_scenario_v2(_scn(FAILS))
    got = _handoffs(lines)
    assert got[0] == (104.0, {"role": "leader", "from_sat": 0, "to_sat": 1, "reason": "DEAD"})
    assert got[1][0] == 204.0  # radio fail at 200: declared by the same K = 3 rule
    assert got[1][1]["from_sat"] == 5 and got[1][1]["reason"] == "RADIO_SILENT"
    assert got[1][1]["to_sat"] in (1, 2, 3, 4)
    # payload failure on an imager (t=300) and thruster-out (t=400) emit nothing
    assert all(t < 300.0 for t, _ in got)


def test_handoff_event_is_the_tick_event_when_alone():
    lines = _ticks(run_scenario_v2(_scn(FAILS[:1], duration_s=110.0)))
    hit = [x for x in lines if x["t"] == 104.0][0]
    assert [e["type"] for e in hit["events"]] == ["FAILURE_DETECTED", "ROLE_HANDOFF"]


def test_no_handoff_without_a_critical_change():
    scn = _scn(
        [
            {"t": 100.0, "sat_id": 1, "mode": "DEAD"},  # the first imager: its role changes holder
            {"t": 150.0, "sat_id": 2, "mode": "PAYLOAD_FAIL"},
        ]
    )
    assert _handoffs(run_scenario_v2(scn)) == []


def test_total_loss_leaves_critical_roles_vacant_and_says_so():
    scn = _scn([{"t": 100.0, "sat_id": i, "mode": "DEAD"} for i in range(6)], duration_s=120.0)
    got = {p["role"]: (t, p) for t, p in _handoffs(run_scenario_v2(scn))}
    for role, sat in (("leader", 0), ("downlink", 5)):
        t, p = got[role]
        assert t == 104.0 and p == {"role": role, "from_sat": sat, "to_sat": None, "reason": "DEAD"}


def test_deterministic():
    a = json.dumps(run_scenario_v2(_scn(FAILS)))
    assert a == json.dumps(run_scenario_v2(_scn(FAILS)))


def test_snapshot_carries_role_state():
    scn = _scn(FAILS[:1])
    eng = EngineV2(scn)
    for _ in range(150):  # t = 0..298: the leader died at t = 100
        eng.step()
    blob = eng.snapshot()
    assert json.loads(blob)["state"]["roles"][1] == ["imager", "leader"]
    twin = EngineV2(scn)
    twin.restore(blob)
    rest_a = [eng.step() for _ in range(20)]
    rest_b = [twin.step() for _ in range(20)]
    assert json.dumps(rest_a) == json.dumps(rest_b)
    assert not _handoffs(rest_b) and rest_b[0]["sats"][1]["roles"] == ["imager", "leader"]


def test_restore_rejects_a_snapshot_without_roles_and_stays_untouched():
    eng = EngineV2(_scn())
    for _ in range(5):
        eng.step()
    doc = json.loads(eng.snapshot())
    del doc["state"]["roles"]
    other = EngineV2(_scn())
    with pytest.raises(ValueError):
        other.restore(json.dumps(doc).encode())
    assert other.k == 0


def test_injected_failure_hands_off_like_a_scheduled_one():
    eng = EngineV2(_scn())
    for _ in range(10):
        eng.step()
    eng.inject(Failure(t=0.0, sat_id=5, mode="DEAD"))
    lines = [eng.step() for _ in range(4)]  # injected at t = 20, declared at t = 24
    got = [(x["t"], e["payload"]["role"]) for x in lines for e in x.get("events", [])
           if e["type"] == "ROLE_HANDOFF"]
    assert got == [(24.0, "downlink")]


# --- roles follow what the swarm BELIEVES: silent failures act when declared ----------------------
def _first_event(lines, kind, sat=None):
    for x in _ticks(lines):
        for e in x.get("events", []):
            p = e["payload"]
            if e["type"] == kind and (sat is None or p.get("sat_id", p.get("from_sat")) == sat):
                return x["t"]
    return None


def test_dead_sat_keeps_its_roles_until_the_heartbeat_declares_it():
    lines = _ticks(run_scenario_v2(_scn(FAILS[:1], duration_s=130.0)))
    by_t = {x["t"]: x["sats"][0] for x in lines}
    for t in (100.0, 102.0):  # dead, not yet declared: label kept, status already DEAD
        assert by_t[t]["status"] == "DEAD" and by_t[t]["roles"] == ["leader"]
    assert by_t[104.0]["roles"] == [] and by_t[104.0]["role"] == "none"
    assert _first_event(lines, "ROLE_HANDOFF") == _first_event(lines, "FAILURE_DETECTED") == 104.0


def test_radio_failure_hands_off_when_declared_not_before():
    lines = run_scenario_v2(_scn(FAILS[1:2], duration_s=230.0))
    assert _first_event(lines, "ROLE_HANDOFF") == _first_event(lines, "FAILURE_DETECTED") == 204.0
    row = {x["t"]: x["sats"][5] for x in _ticks(lines)}
    assert row[202.0]["roles"] == ["downlink"] and row[204.0]["roles"] == ["spare"]


def test_self_reported_payload_failure_drops_the_imager_role_at_once():
    lines = run_scenario_v2(_scn([FAILS[2]], duration_s=310.0))
    assert _first_event(lines, "FAILURE_DETECTED") == 300.0
    row = {x["t"]: x["sats"][2] for x in _ticks(lines)}
    assert "imager" in row[298.0]["roles"] and "imager" not in row[300.0]["roles"]


def test_a_silent_sat_cannot_announce_a_payload_failure():
    fails = [
        {"t": 100.0, "sat_id": 1, "mode": "RADIO_FAIL"},
        {"t": 101.0, "sat_id": 1, "mode": "PAYLOAD_FAIL"},
    ]
    row = {x["t"]: x["sats"][1] for x in _ticks(run_scenario_v2(_scn(fails, duration_s=110.0)))}
    assert row[102.0]["roles"] == ["imager"]  # nothing announced yet
    assert "imager" not in row[104.0]["roles"]  # declared: truth is believed from now on


def test_fuel_depletion_changes_no_role():
    row = _ticks(run_scenario_v2(_scn([], duration_s=20.0)))[-1]["sats"]
    eng = EngineV2(_scn([]))
    eng.faults.sats[3].m_prop_kg = 0.0
    assert eng.step()["sats"][3]["roles"] == ["imager"] and row[3]["roles"] == ["imager"]


def test_coverage_drops_at_the_failure_even_though_the_role_is_kept_for_a_few_ticks():
    fine = {"fov_half_angle_deg": 1.5, "grid_step_km": 2.0, "grid_extent_km": 30.0}
    scn = _scn([{"t": 100.0, "sat_id": 1, "mode": "DEAD"}], duration_s=110.0, sensor=fine)
    lines = _ticks(run_scenario_v2(scn))
    assert [x["coverage"] for x in lines] == _independent_coverage(lines, scn)
    by_t = {x["t"]: x for x in lines}
    assert by_t[102.0]["sats"][1]["roles"] == ["imager"]
    assert by_t[102.0]["coverage"] < by_t[98.0]["coverage"]


def test_snapshot_inside_the_undeclared_window_resumes_the_handoff():
    scn = _scn(FAILS[:1], duration_s=130.0)
    eng = EngineV2(scn)
    for _ in range(52):  # ticks 0..102: dead at 100, declared at 104
        eng.step()
    twin = EngineV2(scn)
    twin.restore(eng.snapshot())
    a, b = [eng.step() for _ in range(5)], [twin.step() for _ in range(5)]
    assert json.dumps(a) == json.dumps(b)
    hit = [x["t"] for x in b if "events" in x and x["events"][-1]["type"] == "ROLE_HANDOFF"]
    assert hit == [104.0]


@pytest.mark.parametrize("key", ["roles", "believed"])
def test_restore_refuses_a_state_list_of_the_wrong_length(key):
    eng = EngineV2(_scn())
    eng.step()
    doc = json.loads(eng.snapshot())
    doc["state"][key] = doc["state"][key][:-1]
    other = EngineV2(_scn())
    with pytest.raises(ValueError):
        other.restore(json.dumps(doc).encode())
    assert other.k == 0
