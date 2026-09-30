"""Wire-format tests (BACKEND_SPEC v1.1 sections 5.1, 6.1, 11).

cubesat.wire is the SINGLE log-line -> WS-message authority; these tests pin the
section 6.1 normalization table, including a golden fixture built from a real
data/logs/two_failure.jsonl line (tests/fixtures/wire_golden.json).
"""

import json
from pathlib import Path

from cubesat.wire import SessionEnrich, display_sat_id, to_event, to_messages, to_sim_state

FIXTURES = Path(__file__).parent / "fixtures"


def _nominal_tick_line() -> dict:
    return {
        "v": 1,
        "t": 42.0,
        "state": "NOMINAL",
        "coverage": 0.3839750260145682,
        "min_sep": 11313.708498984759,
        "sats": [
            {
                "id": 0,
                "role": "leader",
                "status": "NOMINAL",
                "r": [8000.0, -0.0, 8000.0],
                "v": [-0.0, -17.708535141359047, -0.0],
                "dv_used": 0.0,
            },
            {
                "id": 5,
                "role": "downlink",
                "status": "THRUSTER_OUT",
                "r": [4000.0, 13856.4, 4000.0],
                "v": [7.668, -8.854, 7.668],
                "dv_used": 12.5,
            },
        ],
    }


def test_display_sat_id_is_one_based_string():
    assert display_sat_id(0) == "SAT-1"
    assert display_sat_id(5) == "SAT-6"


def test_wire_sim_state_matches_spec_example():
    """Golden: a real two_failure.jsonl tick line -> the exact FRONTEND_SPEC
    16.1 shape. The fixture commits both the raw log line and the expected
    message sequence; regenerate only with a spec change, never silently."""
    fixture = json.loads((FIXTURES / "wire_golden.json").read_text(encoding="utf-8"))
    enrich = SessionEnrich(scenario="two_failure.json", seed=42)
    messages = to_messages(fixture["line"], enrich)
    assert messages == fixture["expected_messages"]


def test_wire_status_and_id_normalization():
    enrich = SessionEnrich(scenario="two_failure.json", seed=42)
    state = to_sim_state(_nominal_tick_line(), enrich)
    assert state["type"] == "sim_state"
    assert state["sim_time"] == 42.0
    assert state["state"] == "NOMINAL"
    assert state["scenario"] == "two_failure.json"
    assert state["seed"] == 42
    sat0, sat5 = state["sats"]
    assert sat0["id"] == "SAT-1" and sat0["status"] == "healthy"
    assert sat5["id"] == "SAT-6" and sat5["status"] == "failed"
    assert sat5["failure_type"] == "THRUSTER_OUT"  # preserved per section 6.1
    # "failure_type" only on failed sats; SI r/v/dv_used pass through untouched.
    assert "failure_type" not in sat0
    assert sat5["r"] == [4000.0, 13856.4, 4000.0]
    assert sat5["dv_used"] == 12.5
    assert state["coverage"] == 0.3839750260145682
    assert state["min_sep"] == 11313.708498984759
    # section 6.1 deliberate cuts: unmeasured latencies ship null
    assert state["metrics"] == {"detection_latency_s": None, "replanning_latency_ms": None}
    # no target_slot without an assignment yet
    assert "target_slot" not in sat0


def test_wire_target_slot_comes_from_assignment_map():
    enrich = SessionEnrich(assignment_map={5: "slot_3"})
    state = to_sim_state(_nominal_tick_line(), enrich)
    assert state["sats"][1]["target_slot"] == "slot_3"
    assert "target_slot" not in state["sats"][0]


def test_wire_event_and_role_reassignment():
    enrich = SessionEnrich(scenario="two_failure.json", seed=42)
    failure_line = {
        "v": 1,
        "t": 1204.0,
        "state": "FAILURE_DETECTED",
        "coverage": 0.27,
        "min_sep": 11753.5,
        "sats": [],
        "event": {
            "type": "FAILURE_DETECTED",
            "payload": {"sat_id": 1, "mode": "DEAD", "t_fail": 1200.0, "t_detect": 1204.0},
        },
    }
    messages = to_messages(failure_line, enrich)
    assert [m["type"] for m in messages] == ["sim_state", "event"]
    event = messages[1]
    assert event == {
        "type": "event",
        "sim_time": 1204.0,
        "level": "critical",
        "message": "SAT-2 DEAD failure detected",
    }
    # latency = t_detect - t_fail, both timestamps present in the payload
    assert enrich.detection_latency_s == 4.0
    assert messages[0]["metrics"]["detection_latency_s"] == 4.0
    assert messages[0]["metrics"]["replanning_latency_ms"] is None  # deliberate cut

    assignment_line = {
        "v": 1,
        "t": 1208.0,
        "state": "RECONFIGURING",
        "coverage": 0.27,
        "min_sep": 11766.4,
        "sats": [
            {"id": 2, "role": "imager", "status": "NOMINAL", "r": [0, 0, 0], "v": [0, 0, 0],
             "dv_used": 0.0},
        ],
        "event": {
            "type": "ASSIGNMENT",
            "payload": {
                "assignments": [
                    {"role": "leader", "sat_id": 0, "slot_index": 1},
                    {"role": "imager", "sat_id": 2, "slot_index": 0},
                ],
                "cost_total": 3.7726621102252276,
                "method": "hungarian",
                "formation": {"phase_offset_rad": 0.0, "radial_amp_m": 8000.0},
                "transfer_lower_bound_s": 983.977675971543,
            },
        },
    }
    messages = to_messages(assignment_line, enrich)
    assert [m["type"] for m in messages] == ["sim_state", "role_reassignment"]
    reassign = messages[1]
    assert reassign["sim_time"] == 1208.0
    # payload fields that exist are mapped; old_role/cost per sat don't exist
    # in the log payload and are NOT invented (section 6.1)
    assert reassign["assignments"] == [
        {"satellite_id": "SAT-1", "new_role": "leader", "target_slot": "slot_1"},
        {"satellite_id": "SAT-3", "new_role": "imager", "target_slot": "slot_0"},
    ]
    assert reassign["cost_total"] == 3.7726621102252276
    # the assignment map feeds target_slot on later sim_states
    assert messages[0]["sats"][0]["target_slot"] == "slot_0"
    assert enrich.assignment_map == {0: "slot_1", 2: "slot_0"}


def test_wire_unknown_event_and_payload_keys_do_not_crash():
    enrich = SessionEnrich()
    line = {
        "v": 1,
        "t": 9.0,
        "state": "NOMINAL",
        "coverage": 0.1,
        "min_sep": 1.0,
        "sats": [],
        "event": {"type": "MYSTERY", "payload": {"weird": [1, 2], "nested": {"a": 1}}},
    }
    messages = to_messages(line, enrich)
    assert [m["type"] for m in messages] == ["sim_state", "event"]
    assert messages[1]["level"] == "info"
    assert messages[1]["message"] == "MYSTERY"


def test_wire_state_transition_event_maps_to_info_event():
    enrich = SessionEnrich()
    line = {
        "v": 1,
        "t": 1206.0,
        "state": "REPLANNING",
        "coverage": 0.27,
        "min_sep": 1.0,
        "sats": [],
        "event": {"type": "STATE", "payload": {"from": "FAILURE_DETECTED", "to": "REPLANNING"}},
    }
    messages = to_messages(line, enrich)
    assert messages[1] == {
        "type": "event",
        "sim_time": 1206.0,
        "level": "info",
        "message": "State FAILURE_DETECTED -> REPLANNING",
    }


def test_wire_init_header_maps_to_empty_state_and_summary_to_final_event():
    enrich = SessionEnrich(scenario="two_failure.json", seed=42)
    header = {"v": 1, "t": 0.0, "state": "INIT", "scenario": "two_failure", "seed": 42,
              "n_sats": 6}
    messages = to_messages(header, enrich)
    assert len(messages) == 1
    init_state = messages[0]
    assert init_state["type"] == "sim_state"
    assert init_state["state"] == "NOMINAL"  # section 6.1: INIT never appears on the wire
    assert init_state["sats"] == []
    assert init_state["coverage"] is None and init_state["min_sep"] is None

    summary = {"v": 1, "t": 17028.0, "state": "SUMMARY",
               "coverage_mean_last_orbit": 0.26979718716450923}
    messages = to_messages(summary, enrich)
    assert len(messages) == 1
    assert messages[0]["type"] == "event"
    assert messages[0]["message"] == "Run complete"
    # SUMMARY is never sent as a sim_state
    assert all(m["type"] != "sim_state" for m in messages)


def test_to_event_shape():
    assert to_event("critical", 120.0, "boom") == {
        "type": "event",
        "sim_time": 120.0,
        "level": "critical",
        "message": "boom",
    }
