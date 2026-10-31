"""Capability roles for engine v2 (physics Phase 5a). Pure functions, no RNG, no state.

POWER IS NOT MODELLED (no battery in cubesat/spacecraft.py, Task 2.2 is unbuilt): the
"power" need of the master-map role table is treated as always satisfied here.

Role table (ROLE_SPECS): critical = losing it is a mission-level event (ROLE_HANDOFF);
stackable = may share a sat with another role without penalty; needs = hardware required.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from scipy.optimize import linear_sum_assignment

ROLE_SPECS: dict[str, dict] = {
    "leader": {"critical": True, "stackable": True, "needs": ("radio",)},  # software role
    "downlink": {"critical": True, "stackable": False, "needs": ("radio",)},  # + power (unmodelled)
    "imager": {"critical": False, "stackable": False, "needs": ("payload",)},  # counts to SLA
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


DEFAULT_PRIORITY = ("downlink", "imager", "leader")
INCAPABLE = 1e6  # finite on purpose: linear_sum_assignment must never see inf
_EPS = 1e-9  # row-major index tie-break (AGENTS.md invariant 6)
_STACK_PENALTY = 2.0  # per non-stackable role the sat already holds (above the 0/1 incumbent gap)


def assign_roles(sats: list[dict], priority: Sequence[str] = DEFAULT_PRIORITY) -> list[list[str]]:
    """Roles held by each sat (index = position in `sats`), a pure function of its input.

    Each sat dict needs `status`, `payload_ok`, `radio_ok` and `roles` (the roles it holds NOW:
    the incumbents; a dead sat's stale labels are ignored because it is incapable). Roles are
    filled in `priority` order. Per role, seats = 1 for a critical role and
    max(1, capable incumbents) otherwise (an imager never multiplies, a lost imager is not
    replaced: this phase does not replan). Rows = sats, columns = seats,
    scipy linear_sum_assignment; cost = INCAPABLE (1e6) if the sat cannot hold the role, else
    0 for an incumbent, else 1 + 2 per non-stackable role it already holds or critical role it
    holds now (so a role stacks on a busy sat only when no free capable sat exists), plus a
    1e-9 row-major index epsilon (ties go to the lowest id). A seat that lands on an incapable
    sat stays VACANT: see vacant_roles. A capable sat left with nothing holds ["spare"]; an
    incapable or dead one []."""
    priority = tuple(dict.fromkeys(priority))
    for role in priority:
        if role not in ROLE_SPECS or role == "spare":
            raise ValueError(f"unknown role {role!r} in priority; known: {list(DEFAULT_PRIORITY)}")
        n = len(sats)
    held: list[list[str]] = [[] for _ in range(n)]
    for role in priority if n else ():
        ok = [capability(s["status"], s["payload_ok"], s["radio_ok"], role) for s in sats]
        inc = [o and role in s.get("roles", ()) for o, s in zip(ok, sats, strict=True)]
        seats = 1 if ROLE_SPECS[role]["critical"] else max(1, sum(inc))
        cost = np.empty((n, seats))
        for i in range(n):
            busy = sum(not ROLE_SPECS[r]["stackable"] for r in held[i])
            # a critical role the sat holds now also makes it busy (no leader+downlink pile-up)
            busy += sum(
                ROLE_SPECS[r]["critical"] and r != role and r not in held[i]
                for r in sats[i].get("roles", ())
            )
            cost[i] = INCAPABLE if not ok[i] else 0.0 if inc[i] else 1.0 + _STACK_PENALTY * busy
        cost += _EPS * (np.arange(n)[:, None] * seats + np.arange(seats)[None, :])
        for i, _ in zip(*linear_sum_assignment(cost), strict=True):
            if ok[i]:  # a seat that landed on an incapable sat stays vacant
                held[i].append(role)
    for i, s in enumerate(sats):
        if not held[i] and capability(s["status"], s["payload_ok"], s["radio_ok"], "spare"):
            held[i] = ["spare"]
    return held


def handoff_events(
    old_roles: list[list[str]], new_roles: list[list[str]], statuses: list[str],
    priority: Sequence[str] = DEFAULT_PRIORITY,
) -> list[dict]:
    """ROLE_HANDOFF payloads {role, from_sat, to_sat, reason}, one per critical role whose
    holder (lowest sat id holding it) changed between `old_roles` and `new_roles`, in priority
    order. to_sat None = vacant now, from_sat None = was vacant (reason "VACANT"); otherwise
    reason = the old holder's status. Non-critical roles (imager) never hand off."""
    out = []
    for role in (r for r in priority if ROLE_SPECS[r]["critical"]):
        old_i = next((i for i, rs in enumerate(old_roles) if role in rs), None)
        new_i = next((i for i, rs in enumerate(new_roles) if role in rs), None)
        if old_i != new_i:
            reason = "VACANT" if old_i is None else statuses[old_i]
            out.append({"role": role, "from_sat": old_i, "to_sat": new_i, "reason": reason})
    return out
