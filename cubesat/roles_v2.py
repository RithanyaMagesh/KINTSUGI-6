"""Capability roles for engine v2 (physics Phase 5a). Pure functions, no RNG, no state.

POWER IS NOT MODELLED (no battery in cubesat/spacecraft.py, Task 2.2 is unbuilt): the
"power" need of the master-map role table is treated as always satisfied here.

Role table (ROLE_SPECS): critical = losing it is a mission-level event (ROLE_HANDOFF);
stackable = may share a sat with another role without penalty; needs = hardware required.
"""

from __future__ import annotations

ROLE_SPECS: dict[str, dict] = {
    "leader": {"critical": True, "stackable": True, "needs": ("radio",)},  # software role
    "downlink": {"critical": True, "stackable": False, "needs": ("radio",)},  # + power (unmodelled)
    "imager": {"critical": False, "stackable": False, "needs": ("payload",)},  # counts to SLA
    "relay": {"critical": False, "stackable": True, "needs": ("radio",)},
    "spare": {"critical": False, "stackable": True, "needs": ()},
}
# A sat in one of these statuses is flying AND reporting. THRUSTER_OUT and FUEL_DEPLETED sats
# cannot thrust but still image and talk (no role here needs thrust); RADIO_SILENT flies but
# nothing it does reaches ground; DEAD and REENTERED have no working hardware.
_REPORTING = ("NOMINAL", "DEGRADED", "FUEL_DEPLETED", "THRUSTER_OUT", "PAYLOAD_FAILED")
_FLYING = _REPORTING + ("RADIO_SILENT",)


def capability(status: str, payload_ok: bool, radio_ok: bool, role: str) -> bool:
    """Can a sat in `status` with these flags hold `role`?

    imager: payload_ok and a reporting sat (a dead payload takes no images; an image that
    cannot be reported is not coverage). downlink: radio_ok and a reporting sat (it must
    transmit to ground). leader: radio_ok and a reporting sat (software, but it must talk to
    the swarm; stackable on any capable sat). relay: radio_ok and a reporting sat. spare:
    any flying sat (RADIO_SILENT included). DEAD and REENTERED: nothing, whatever the flags
    say (a re-entered sat keeps stale flags). Raises ValueError for an unknown role."""
    if role not in ROLE_SPECS:
        raise ValueError(f"unknown role {role!r}; known: {sorted(ROLE_SPECS)}")
    if role == "spare":
        return status in _FLYING
    if status not in _REPORTING:
        return False
    have = {"payload": payload_ok, "radio": radio_ok}
    return all(have[need] for need in ROLE_SPECS[role]["needs"])
