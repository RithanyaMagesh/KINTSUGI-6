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
        "sat_id": "SAT-2",  # additive (2026-10-31); the four keys above are unchanged
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
        # additive structured fields (2026-10-31); the four keys above are unchanged
        "from": "FAILURE_DETECTED",
        "to": "REPLANNING",
        "label": "Planning recovery",
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
    assert [m["type"] for m in messages] == ["run_summary", "event"]
    assert messages[-1]["message"] == "Run complete"
    # SUMMARY is never sent as a sim_state
    assert all(m["type"] != "sim_state" for m in messages)


def test_to_event_shape():
    assert to_event("critical", 120.0, "boom") == {
        "type": "event",
        "sim_time": 120.0,
        "level": "critical",
        "message": "boom",
    }


def test_wire_degraded_status_maps_to_degraded():
    """Addendum v1.2: the new per-sat status DEGRADED maps to wire status
    'degraded' with failure_type preserved; old statuses are untouched."""
    line = _nominal_tick_line()
    line["sats"][0]["status"] = "DEGRADED"
    state = to_sim_state(line, SessionEnrich())
    sat0, sat5 = state["sats"]
    assert sat0["status"] == "degraded"
    assert sat0["failure_type"] == "DEGRADED"  # preserved per section 6.1
    assert sat5["status"] == "failed"  # existing rows unchanged
    assert sat5["failure_type"] == "THRUSTER_OUT"


def test_wire_self_report_failure_message():
    """Addendum v1.2: a FAILURE_DETECTED payload with self_report: true appends
    '(self-reported)' to the message; payloads without the key render exactly
    as before (additive key, old logs unchanged)."""
    enrich = SessionEnrich()

    def _line(payload):
        return {
            "v": 1,
            "t": 6.0,
            "state": "FAILURE_DETECTED",
            "coverage": 0.5,
            "min_sep": 10.0,
            "sats": [],
            "event": {"type": "FAILURE_DETECTED", "payload": payload},
        }

    reported = to_messages(
        _line({"sat_id": 3, "mode": "THRUSTER_OUT", "t_fail": 6.0, "t_detect": 6.0,
               "self_report": True}),
        enrich,
    )
    assert reported[1]["message"] == "SAT-4 THRUSTER_OUT failure detected (self-reported)"
    assert enrich.detection_latency_s == 0.0  # t_detect == t_fail

    plain = to_messages(
        _line({"sat_id": 1, "mode": "DEAD", "t_fail": 2.0, "t_detect": 6.0}),
        SessionEnrich(),
    )
    assert plain[1]["message"] == "SAT-2 DEAD failure detected"  # unchanged shape


# --- Wire additions (2026-10-31): additive optional keys, never a changed one ---


def _tick(t, sats=(), event=None, state="NOMINAL"):
    line = {"v": 1, "t": t, "state": state, "coverage": 0.5, "min_sep": 1.0,
            "sats": [{"id": i, "role": r, "status": s, "r": [0, 0, 0], "v": [0, 0, 0],
                      "dv_used": 0.0} for i, r, s in sats]}
    if event:
        line["event"] = event
    return line


def _assignment(method, **extra):
    payload = {"assignments": [{"role": "leader", "sat_id": 2, "slot_index": 2}],
               "cost_total": 0.0, "method": method,
               "formation": {"phase_offset_rad": 0.5, "radial_amp_m": 8000.0},
               "transfer_lower_bound_s": 12.5, **extra}
    return {"type": "ASSIGNMENT", "payload": payload}


def test_role_reassignment_passes_method_formation_and_bound():
    msgs = to_messages(_tick(1.0, event=_assignment("hungarian")), SessionEnrich())
    r = msgs[1]
    assert r["method"] == "hungarian"
    assert r["kept_formation"] is False
    assert r["formation"] == {"radial_amp_m": 8000.0, "phase_offset_rad": 0.5}
    assert r["transfer_lower_bound_s"] == 12.5


def test_role_reassignment_do_no_harm_hold_sets_kept_formation():
    msgs = to_messages(_tick(1.0, event=_assignment("do_no_harm_hold")), SessionEnrich())
    assert msgs[1]["method"] == "do_no_harm_hold"
    assert msgs[1]["kept_formation"] is True


def test_role_reassignment_without_method_adds_no_new_keys():
    payload = {"assignments": [{"role": "leader", "sat_id": 2, "slot_index": 2}]}
    msgs = to_messages(_tick(1.0, event={"type": "ASSIGNMENT", "payload": payload}),
                       SessionEnrich())
    assert set(msgs[1]) == {"type", "sim_time", "assignments"}


def test_old_role_only_on_tick_where_role_changed():
    enrich = SessionEnrich()
    nom = [(0, "leader", "NOMINAL"), (1, "imager", "NOMINAL"), (2, "imager", "NOMINAL")]
    first = to_messages(_tick(1.0, nom), enrich)[0]
    assert all("old_role" not in s for s in first["sats"])  # no previous frame yet
    same = to_messages(_tick(2.0, nom), enrich)[0]
    assert all("old_role" not in s for s in same["sats"])
    swapped = [(0, "imager", "NOMINAL"), (1, "leader", "NOMINAL"), (2, "imager", "NOMINAL")]
    sats = to_messages(_tick(3.0, swapped), enrich)[0]["sats"]
    assert [s.get("old_role") for s in sats] == ["leader", "imager", None]
    again = to_messages(_tick(4.0, swapped), enrich)[0]
    assert all("old_role" not in s for s in again["sats"])  # gone the next tick


def test_leader_loss_produces_leader_handoff():
    enrich = SessionEnrich()
    live = [(0, "leader", "NOMINAL"), (1, "imager", "NOMINAL"), (2, "imager", "NOMINAL")]
    to_messages(_tick(1.0, live), enrich)
    # sat 0 dies but keeps its role label in the log; sat 2 becomes leader
    dead = [(0, "leader", "DEAD"), (1, "imager", "NOMINAL"), (2, "imager", "NOMINAL")]
    to_messages(_tick(2.0, dead), enrich)
    after = [(0, "leader", "DEAD"), (1, "imager", "NOMINAL"), (2, "leader", "NOMINAL")]
    ev = {"type": "ASSIGNMENT", "payload": {"assignments": [
        {"role": "leader", "sat_id": 2, "slot_index": 0},
        {"role": "imager", "sat_id": 1, "slot_index": 1}]}}
    msgs = to_messages(_tick(3.0, after, ev), enrich)
    assert msgs[0]["sats"][2]["old_role"] == "imager"
    assert msgs[1]["role_handoffs"] == [{"role": "leader", "from_sat": "SAT-1", "to_sat": "SAT-3"}]


def test_no_handoff_when_roles_unchanged():
    enrich = SessionEnrich()
    live = [(0, "leader", "NOMINAL"), (1, "imager", "NOMINAL")]
    to_messages(_tick(1.0, live), enrich)
    ev = {"type": "ASSIGNMENT", "payload": {"assignments": [
        {"role": "leader", "sat_id": 0, "slot_index": 0}]}}
    msgs = to_messages(_tick(2.0, live, ev), enrich)
    assert "role_handoffs" not in msgs[1]
    assert all("old_role" not in s for s in msgs[0]["sats"])


def test_run_summary_message_precedes_run_complete_event():
    enrich = SessionEnrich(scenario="two_failure.json", seed=42)
    summary = {"v": 1, "t": 17028.0, "state": "SUMMARY", "coverage_mean_last_orbit": 0.27}
    msgs = to_messages(summary, enrich)
    assert [m["type"] for m in msgs] == ["run_summary", "event"]
    assert msgs[1]["message"] == "Run complete"  # existing event kept, still the last message
    assert msgs[0] == {"type": "run_summary", "coverage_mean_last_orbit": 0.27,
                       "sim_time": 17028.0, "scenario": "two_failure.json", "seed": 42}
    bare = to_messages({"v": 1, "t": 5.0, "state": "SUMMARY"}, SessionEnrich())
    assert bare[0]["coverage_mean_last_orbit"] is None  # truncated line never raises


def _state_event(frm, to):
    return to_messages(_tick(5.0, event={"type": "STATE", "payload": {"from": frm, "to": to}}),
                       SessionEnrich())[1]


def test_state_events_carry_structured_from_to_label():
    for frm, to, label in [
        ("FAILURE_DETECTED", "REPLANNING", "Planning recovery"),
        ("REPLANNING", "RECONFIGURING", "Moving to new positions"),
        ("RECONFIGURING", "RECOVERED", "Recovered"),
    ]:
        ev = _state_event(frm, to)
        assert ev["message"] == f"State {frm} -> {to}"  # text unchanged
        assert (ev["from"], ev["to"], ev["label"]) == (frm, to, label)


def test_unknown_state_transition_keeps_text_only():
    ev = _state_event("NOMINAL", "MYSTERY")
    assert ev == {"type": "event", "sim_time": 5.0, "level": "info",
                  "message": "State NOMINAL -> MYSTERY"}
    assert _state_event(None, None)["message"] == "State None -> None"  # truncated payload
    assert "label" not in _state_event(["x"], {"y": 1})  # unhashable junk never raises


def _ev(etype, payload, t=600.0):
    msgs = to_messages(_tick(t, event={"type": etype, "payload": payload}), SessionEnrich())
    return msgs[1]


def test_degrade_start_plain_warning_with_countdown():
    ev = _ev("DEGRADE_START", {"sat_id": 0, "t_fail": 2400.0, "degrade_s": 1800.0})
    assert ev["level"] == "warning"
    assert ev["message"] == "SAT-1 battery fading; failure expected at T+30:00"
    assert ev["sat_id"] == "SAT-1"
    assert _ev("DEGRADE_START", {"sat_id": 2})["message"] == "SAT-3 battery fading"
    assert _ev("DEGRADE_START", {})["message"] == "A satellite battery fading"
    assert "sat_id" not in _ev("DEGRADE_START", {})
    junk = _ev("DEGRADE_START", {"sat_id": 1, "t_fail": float("nan")})
    assert junk["message"] == "SAT-2 battery fading"


def test_oracle_swap_plain_sentence_and_holder_sat_id():
    ev = _ev("ORACLE_SWAP", {"role": "leader", "from_sat": 0, "to_sat": 1, "t": 5.0})
    assert ev["level"] == "info"
    assert ev["message"] == "SAT-1 leader role handed to SAT-2 before SAT-1 fails"
    assert ev["sat_id"] == "SAT-1"
    deg = _ev("ORACLE_SWAP", {"role": "leader", "from_sat": 0, "to_sat": 1,
                              "mode": "degrade_trigger"})
    assert deg["message"] == "SAT-1 leader role handed to SAT-2 because its battery is fading"
    bare = _ev("ORACLE_SWAP", {})
    assert bare["message"] == "A satellite critical role handed to another satellite"
    assert "sat_id" not in bare


def test_oracle_alert_plain_sentence_with_lead_time():
    ev = _ev("ORACLE_ALERT", {"sat_id": 3, "lead_s": 600.0, "t_fail": 2400.0, "t_warn": 1800.0})
    assert ev["level"] == "info"
    assert ev["message"] == "Early warning: SAT-4 expected to fail in 10:00; replanning early"
    assert ev["sat_id"] == "SAT-4"
    assert _ev("ORACLE_ALERT", {"sat_id": 3})["message"] == (
        "Early warning: SAT-4 expected to fail; replanning early")
    assert _ev("ORACLE_ALERT", {})["message"] == (
        "Early warning: a satellite expected to fail; replanning early")


def test_failure_and_evasive_events_carry_sat_id():
    f = _ev("FAILURE_DETECTED", {"sat_id": 1, "mode": "DEAD", "t_fail": 1.0, "t_detect": 2.0})
    assert f["sat_id"] == "SAT-2" and f["message"] == "SAT-2 DEAD failure detected"
    e = _ev("EVASIVE_MANEUVER", {"sat_id": 4, "other_id": 5, "range_m": 959.37})
    assert e["sat_id"] == "SAT-5" and e["message"] == "SAT-5 evasive maneuver (SAT-6, range 959 m)"
    assert "sat_id" not in _ev("FAILURE_DETECTED", {})  # truncated payload: no key, no raise
    assert "sat_id" not in _ev("EVASIVE_MANEUVER", {})
    assert "sat_id" not in _ev("MYSTERY", {"sat_id": 1})  # unknown types untouched


def _contains(new, old, path="$"):
    """Assert `new` carries every key/value of `old` (extra keys in `new` are fine)."""
    if isinstance(old, dict):
        assert isinstance(new, dict), path
        for k, v in old.items():
            assert k in new, f"{path}.{k} missing from new output"
            _contains(new[k], v, f"{path}.{k}")
    elif isinstance(old, list):
        assert isinstance(new, list) and len(new) == len(old), path
        for i, (n, o) in enumerate(zip(new, old, strict=True)):
            _contains(n, o, f"{path}[{i}]")
    else:
        assert new == old, f"{path}: {new!r} != {old!r}"


def test_new_wire_output_is_a_superset_of_the_legacy_golden():
    """Additive-only proof: wire_golden_legacy_subset.json is the pre-2026-10-31
    golden, frozen. Every key/value it holds must still appear unchanged."""
    legacy = json.loads((FIXTURES / "wire_golden_legacy_subset.json").read_text("utf-8"))
    new = to_messages(legacy["line"], SessionEnrich(scenario="two_failure.json", seed=42))
    _contains(new, legacy["expected_messages"])


def test_old_role_tracking_resets_when_time_goes_backwards():
    """A replay seek back does not rebuild enrich (session.py); a frame older than the
    last one must start role tracking fresh, not report 'old_role' from the future."""
    enrich = SessionEnrich()
    a = [(0, "leader", "NOMINAL"), (1, "imager", "NOMINAL")]
    b = [(0, "imager", "NOMINAL"), (1, "leader", "NOMINAL")]
    to_messages(_tick(10.0, a), enrich)
    to_messages(_tick(20.0, b), enrich)
    back = to_messages(_tick(10.0, a), enrich)[0]
    assert all("old_role" not in s for s in back["sats"])
