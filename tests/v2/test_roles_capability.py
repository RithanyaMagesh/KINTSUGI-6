"""Phase 5a.1: capability(status, payload_ok, radio_ok, role) and the role spec table."""

import pytest

from cubesat.roles_v2 import ROLE_SPECS, capability

FLYING = ["NOMINAL", "DEGRADED", "FUEL_DEPLETED", "THRUSTER_OUT", "PAYLOAD_FAILED"]


def test_role_spec_table():
    assert ROLE_SPECS["leader"] == {"critical": True, "stackable": True, "needs": ("radio",)}
    assert ROLE_SPECS["downlink"]["critical"] and not ROLE_SPECS["downlink"]["stackable"]
    imager = ROLE_SPECS["imager"]
    assert imager["critical"] is False and imager["needs"] == ("payload",)
    assert set(ROLE_SPECS) == {"leader", "downlink", "imager", "spare"}  # no relay


@pytest.mark.parametrize("status", ["NOMINAL", "DEGRADED", "FUEL_DEPLETED", "THRUSTER_OUT"])
def test_thrust_independent_roles_survive_lost_thrust(status):
    for role in ("imager", "downlink", "leader", "spare"):
        assert capability(status, True, True, role)


def test_payload_failed_cannot_image_but_can_talk():
    assert not capability("PAYLOAD_FAILED", False, True, "imager")
    assert capability("PAYLOAD_FAILED", False, True, "downlink")
    assert capability("PAYLOAD_FAILED", False, True, "leader")


def test_imager_needs_payload_flag_even_when_status_is_nominal():
    assert not capability("NOMINAL", False, True, "imager")


def test_radio_silent_holds_nothing_that_needs_radio_but_is_still_a_spare():
    for role in ("downlink", "leader", "imager"):
        assert not capability("RADIO_SILENT", True, False, role)
    assert capability("RADIO_SILENT", True, False, "spare")


def test_radio_flag_gates_radio_roles_whatever_the_status():
    for role in ("downlink", "leader"):
        assert not capability("NOMINAL", True, False, role)


@pytest.mark.parametrize("status", ["DEAD", "REENTERED"])
def test_dead_and_reentered_hold_nothing_even_with_stale_flags(status):
    for role in ROLE_SPECS:
        assert not capability(status, True, True, role)


def test_unknown_role_is_a_value_error():
    with pytest.raises(ValueError, match="unknown role"):
        capability("NOMINAL", True, True, "pilot")
