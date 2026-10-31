"""W2: v2 statuses, per-sat resource keys, event wording and multi-event lines on the wire."""

import pytest

from cubesat.wire import SessionEnrich, to_messages

V2_SAT_KEYS = ("fuel_kg", "fuel_mps_left", "k", "payload_ok", "radio_ok", "stuck")


def _sat(i=0, status="NOMINAL", **extra):
    return {"id": i, "role": "imager", "status": status, "r": [1.0, 2.0, 3.0],
            "v": [0.0, 0.0, 0.0], "dv_used": 0.0, **extra}


def _line(sats, **extra):
    return {"v": 1, "t": 10.0, "state": "NOMINAL", "coverage": 0.1, "min_sep": 50.0,
            "sats": sats, **extra}


def _sim_state(sats):
    return to_messages(_line(sats), SessionEnrich())[0]


# --- item 1: status mapping ---------------------------------------------------------------
@pytest.mark.parametrize("raw,wire", [
    ("NOMINAL", "healthy"), ("DEGRADED", "degraded"), ("DEAD", "failed"),
    ("THRUSTER_OUT", "failed"),
    ("REENTERED", "failed"), ("FUEL_DEPLETED", "degraded"),
    ("PAYLOAD_FAILED", "degraded"), ("RADIO_SILENT", "degraded"),
])
def test_status_maps_to_a_ui_status_and_failure_type_keeps_raw(raw, wire):
    row = _sim_state([_sat(status=raw)])["sats"][0]
    assert row["status"] == wire
    if raw == "NOMINAL":
        assert "failure_type" not in row
    else:
        assert row["failure_type"] == raw


def test_unknown_future_status_passes_through_unchanged():
    row = _sim_state([_sat(status="WARP_CORE_BREACH")])["sats"][0]
    assert row["status"] == "WARP_CORE_BREACH"


# --- item 2: per-sat optional resource keys -------------------------------------------------
V2_VALUES = {"fuel_kg": 0.25, "fuel_mps_left": 12.5, "k": 0.5, "payload_ok": False,
             "radio_ok": True, "stuck": False}


def test_v1_sat_has_no_resource_keys():
    row = _sim_state([_sat()])["sats"][0]
    assert not set(V2_SAT_KEYS) & set(row)


def test_v2_sat_passes_every_resource_key_through_unchanged():
    row = _sim_state([_sat(**V2_VALUES)])["sats"][0]
    assert {k: row[k] for k in V2_SAT_KEYS} == V2_VALUES


def test_only_present_resource_keys_are_passed():
    row = _sim_state([_sat(fuel_kg=1.0)])["sats"][0]
    assert row["fuel_kg"] == 1.0 and not set(V2_SAT_KEYS[1:]) & set(row)


# --- item 3: v2 event wording and levels ----------------------------------------------------
def _events(frame):
    return [m for m in to_messages(frame, SessionEnrich()) if m["type"] == "event"]


def _detected(sat_id, mode, **payload):
    return {"type": "FAILURE_DETECTED",
            "payload": {"sat_id": sat_id, "mode": mode, "t_fail": 8.0, "t_detect": 10.0, **payload}}


V2_EVENTS = [
    (_detected(2, "PAYLOAD_FAIL", self_report=True), "warning",
     "SAT-3 camera failed; it keeps flying but can no longer image"),
    (_detected(2, "RADIO_FAIL"), "warning",
     "SAT-3 lost its radio; it keeps flying but is silent"),
    (_detected(2, "THRUSTER_STUCK_OPEN"), "critical",
     "SAT-3 thruster stuck open; it is burning fuel it cannot control"),
    (_detected(2, "PARTIAL_THRUST"), "warning", "SAT-3 lost half its thrust"),
    (_detected(2, "FUEL_DEPLETED", self_report=True), "warning",
     "SAT-3 ran out of propellant and can no longer maneuver"),
    ({"type": "FUEL_DEPLETED", "payload": {"sat_id": 2, "t": 10.0}}, "warning",
     "SAT-3 ran out of propellant and can no longer maneuver"),
    (_detected(2, "REENTRY"), "critical", "SAT-3 re-entered the atmosphere"),
    ({"type": "REENTRY", "payload": {"sat_id": 2, "t": 10.0, "altitude_m": 1e5}}, "critical",
     "SAT-3 re-entered the atmosphere"),
]


@pytest.mark.parametrize("event,level,message", V2_EVENTS)
def test_v2_event_wording_level_and_sat_id(event, level, message):
    (ev,) = _events(_line([_sat(2)], event=event))
    assert (ev["level"], ev["message"], ev["sat_id"]) == (level, message, "SAT-3")


@pytest.mark.parametrize("event,level,message", V2_EVENTS)
def test_v2_event_with_missing_or_odd_payload_never_raises(event, level, message):
    for bad in ({}, {"sat_id": None, "mode": ["x"]}, {"sat_id": "SAT-9", "mode": 7}):
        ev = {"type": event["type"], "payload": bad}
        msgs = _events(_line([_sat()], event=ev))
        assert len(msgs) == 1 and msgs[0]["level"] in ("info", "warning", "critical")


def test_v1_failure_event_wording_unchanged():
    (ev,) = _events(_line([_sat()], event=_detected(0, "DEAD")))
    assert (ev["level"], ev["message"]) == ("critical", "SAT-1 DEAD failure detected")
    (ev,) = _events(_line([_sat()], event=_detected(0, "THRUSTER_OUT", self_report=True)))
    assert ev["message"] == "SAT-1 THRUSTER_OUT failure detected (self-reported)"
