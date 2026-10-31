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
