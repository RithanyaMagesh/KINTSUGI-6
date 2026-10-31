"""The single wire-format authority (BACKEND_SPEC v1.1 sections 5.1, 6.1).

Every log-line -> WS-message decision lives here and nowhere else. The
normalization table of section 6.1 is implemented exactly once, in this file,
and pinned by tests/test_wire.py (golden fixture from a real
data/logs/two_failure.jsonl line). Deliberate cuts (section 6.1, do not "fix"):
cost_matrix is OFF (the sim does not expose it), replanning_latency_ms stays
None (frontend renders "unmeasured"), per-sat reconfiguring/recovered statuses
are frontend-derived -- the backend only reports what the log carries.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field


def display_sat_id(i: int) -> str:
    """0-based log id -> 1-based display id (section 6.1)."""
    return f"SAT-{i + 1}"


@dataclass
class SessionEnrich:
    """Per-session context the log lines lack (section 5.1)."""

    scenario: str | None = None
    seed: int | None = None
    policy: str | None = None  # active recovery policy; None = unknown (replay/stopped)
    assignment_map: dict[int, str] = field(default_factory=dict)  # log sat id -> "slot_i"
    detection_latency_s: float | None = None
    replanning_latency_ms: float | None = None  # stays None in G5 (section 6.1 cut)
    prev_roles: dict[int, str] = field(default_factory=dict)  # log sat id -> role, last frame
    role_holder: dict[str, int] = field(default_factory=dict)  # role -> last sole live holder


# Live-selectable recovery policies (the benchmark's seam policies + the shipped
# default; cubesat.benchmark.POLICY_ORDER also carries do_nothing/greedy, which
# are measurement baselines, NOT live-selectable). POLICY_VALUES is the runtime
# mirror of Policy for the session-layer validation (session.py has no pydantic).
POLICY_VALUES = ("hungarian", "even_split", "hungarian_keepout")
Policy = Literal["hungarian", "even_split", "hungarian_keepout"]


class StartRequest(BaseModel):
    scenario: str | None = None
    seed: int | None = None
    speed: float = Field(default=100.0, gt=0)
    policy: Policy = "hungarian"
    predictor: bool = False  # display-only sats[].risk overlay (session.py seam)


class InjectRequest(BaseModel):
    sat_id: str
    mode: Literal["DEAD", "THRUSTER_OUT", "EPS_DEGRADE"] = "DEAD"
    degrade_s: float = Field(
        default=600.0, ge=0, description="EPS_DEGRADE fade length, s (ignored otherwise)"
    )


class SeekRequest(BaseModel):
    t: float


class SpeedRequest(BaseModel):
    speed: float = Field(gt=0)


class ReplayLoadRequest(BaseModel):
    filename: str
    speed: float = Field(default=100.0, gt=0)
    predictor: bool = False  # same display-only overlay, resolved via the log's scenario


# Addendum v1.2: DEGRADED (the EPS_DEGRADE fade) is additive -- old logs never
# carry it, so the new row is unreachable for them.
_STATUS_TO_WIRE = {
    "NOMINAL": "healthy",
    "DEGRADED": "degraded",
    "DEAD": "failed",
    "THRUSTER_OUT": "failed",
}

# Keys _sat_to_wire requires; id must be a 0-based int (display_sat_id does i + 1
# and assignment_map needs a hashable key), status must be hashable.
_SAT_REQUIRED_KEYS = ("role", "r", "v", "dv_used")


def sat_row_ok(sat: object) -> bool:
    """True when _sat_to_wire can render this sats entry without KeyError/TypeError."""
    return (
        isinstance(sat, dict)
        and isinstance(sat.get("id"), int)
        and isinstance(sat.get("status"), str)
        and all(k in sat for k in _SAT_REQUIRED_KEYS)
    )


def tick_frame_ok(frame: dict) -> bool:
    """True when to_messages can render this tick line end to end (section 7.1
    "corrupt replay file -> skip + warn, never crash"): every sats entry carries
    the required schema, and any event payload renders too. Replay load uses
    this to skip + count schema-malformed lines instead of killing the driver
    mid-stream with a KeyError."""
    if "state" not in frame:
        return False
    sats = frame.get("sats")
    if not isinstance(sats, list) or not all(sat_row_ok(s) for s in sats):
        return False
    event = frame.get("event")
    if event is not None:
        if not isinstance(event, dict):
            return False
        payload = event.get("payload")
        if payload is not None and not isinstance(payload, dict):
            return False
        if event.get("type") == "ASSIGNMENT":
            assignments = (payload or {}).get("assignments") or []
            if not isinstance(assignments, list):
                return False
            for a in assignments:
                if (
                    not isinstance(a, dict)
                    or not isinstance(a.get("sat_id"), int)
                    or "slot_index" not in a
                ):
                    return False
    return True


def to_event(level: str, sim_time: float, message: str) -> dict:
    """FRONTEND_SPEC section 16.2 event message."""
    return {"type": "event", "sim_time": sim_time, "level": level, "message": message}


def _metrics(enrich: SessionEnrich) -> dict:
    return {
        "detection_latency_s": enrich.detection_latency_s,
        "replanning_latency_ms": enrich.replanning_latency_ms,
    }


def _sat_to_wire(sat: dict, enrich: SessionEnrich) -> dict:
    status = sat["status"]
    out: dict = {
        "id": display_sat_id(sat["id"]),
        "role": sat["role"],
        "status": _STATUS_TO_WIRE.get(status, status),
        "r": sat["r"],  # SI passthrough, no conversion at this boundary
        "v": sat["v"],
        "dv_used": sat["dv_used"],
    }
    if status != "NOMINAL":
        out["failure_type"] = status  # preserved per section 6.1
    slot = enrich.assignment_map.get(sat["id"])
    if slot is not None:
        out["target_slot"] = slot
    if "risk" in sat:  # Appendix B optional passthrough; never synthesized
        out["risk"] = sat["risk"]
    return out


def _policy_field(enrich: SessionEnrich) -> dict:
    """Active recovery policy echo, deviation-only: the field is emitted ONLY
    when the session's policy is known AND differs from the shipped default
    "hungarian". Rationale: every pre-policy committed log was produced by the
    core hungarian replan, and the default-policy wire bytes are pinned
    (tests/fixtures/wire_golden.json; tests/test_session.py
    test_live_equals_replay_frames) -- deviation-only echo keeps those pins
    byte-identical while still carrying the field where it is informative.
    Absence means "the default": the frontend defaults to hungarian."""
    if enrich.policy is not None and enrich.policy != "hungarian":
        return {"policy": enrich.policy}
    return {}


def to_sim_state(frame: dict, enrich: SessionEnrich) -> dict:
    """FRONTEND_SPEC section 16.1 sim_state (INIT header maps to the empty state)."""
    policy = _policy_field(enrich)
    if frame.get("state") == "INIT":
        return {
            "type": "sim_state",
            "sim_time": frame.get("t", 0.0),
            "state": "NOMINAL",  # INIT never appears on the wire (section 6.1)
            "scenario": enrich.scenario,
            "seed": enrich.seed,
            **policy,
            "sats": [],
            "coverage": None,
            "min_sep": None,
            "metrics": _metrics(enrich),
        }
    return {
        "type": "sim_state",
        "sim_time": frame["t"],
        "state": frame["state"],
        "scenario": enrich.scenario,
        "seed": enrich.seed,
        **policy,
        "sats": [_sat_to_wire(s, enrich) for s in frame.get("sats", [])],
        "coverage": frame.get("coverage"),
        "min_sep": frame.get("min_sep"),
        "metrics": _metrics(enrich),
    }


def _sat_label(sat: object) -> str | None:
    """Raw log sat id -> display id; an already-display str passes; junk -> None."""
    if isinstance(sat, int) and not isinstance(sat, bool):
        return display_sat_id(sat)
    return sat if isinstance(sat, str) else None


def _with_sat(ev: dict, sat: object) -> dict:
    """Optional additive sat_id ('SAT-n') on events about one satellite."""
    label = _sat_label(sat)
    if label is not None:
        ev["sat_id"] = label
    return ev


def _mmss(seconds: object) -> str | None:
    if not isinstance(seconds, (int, float)) or not math.isfinite(seconds):
        return None
    m, s = divmod(int(round(max(seconds, 0.0))), 60)
    return f"{m:02d}:{s:02d}"


def _failure_event(frame: dict, payload: dict, enrich: SessionEnrich) -> dict:
    if isinstance(payload.get("t_fail"), (int, float)) and isinstance(
        payload.get("t_detect"), (int, float)
    ):
        enrich.detection_latency_s = payload["t_detect"] - payload["t_fail"]
    sat = payload.get("sat_id")
    who = display_sat_id(sat) if isinstance(sat, int) else sat
    mode = payload.get("mode")
    message = f"{who} {mode} failure detected" if mode else f"{who} failure detected"
    if payload.get("self_report"):  # Addendum v1.2: additive key, old payloads unchanged
        message += " (self-reported)"
    return _with_sat(to_event("critical", frame.get("t", 0.0), message), who)


def _role_reassignment(frame: dict, payload: dict, enrich: SessionEnrich) -> dict:
    """ASSIGNMENT -> role_reassignment (section 6.1): map the payload fields that
    exist; old_role/per-sat cost do not exist in the log and are NOT invented."""
    assignments = payload.get("assignments") or []
    for a in assignments:
        enrich.assignment_map[a["sat_id"]] = f"slot_{a['slot_index']}"
    msg: dict = {
        "type": "role_reassignment",
        "sim_time": frame.get("t", 0.0),
        "assignments": [
            {
                "satellite_id": display_sat_id(a["sat_id"]),
                "new_role": a.get("role"),
                "target_slot": f"slot_{a['slot_index']}",
            }
            for a in assignments
        ],
    }
    if "cost_total" in payload:
        msg["cost_total"] = payload["cost_total"]
    for key in ("method", "formation", "transfer_lower_bound_s"):  # additive passthrough
        if key in payload:
            msg[key] = payload[key]
    if "method" in payload:
        msg["kept_formation"] = payload["method"] == "do_no_harm_hold"
    return msg


def _track_roles(frame: dict, enrich: SessionEnrich) -> tuple[dict[int, str], list[dict]]:
    """Per-frame role diff, then advance enrich: ({sat id: old role} for sats whose
    role changed since the previous frame, role_handoffs). A handoff is only
    well-defined for a role with ONE live holder (leader/downlink); the from_sat
    is that last sole live holder, which survives the holder's death because the
    log keeps a dead sat's role label. No previous frame -> nothing to diff."""
    sats = frame.get("sats", [])
    old = {
        s["id"]: enrich.prev_roles[s["id"]]
        for s in sats
        if s["id"] in enrich.prev_roles and enrich.prev_roles[s["id"]] != s["role"]
    }
    handoffs = [
        {
            "role": s["role"],
            "from_sat": display_sat_id(enrich.role_holder[s["role"]]),
            "to_sat": display_sat_id(s["id"]),
        }
        for s in sats
        if s["id"] in old and enrich.role_holder.get(s["role"], s["id"]) != s["id"]
    ]
    enrich.prev_roles = {s["id"]: s["role"] for s in sats}
    live: dict[str, list[int]] = {}
    for s in sats:
        if s["status"] in ("NOMINAL", "DEGRADED"):
            live.setdefault(s["role"], []).append(s["id"])
    enrich.role_holder.update({r: ids[0] for r, ids in live.items() if len(ids) == 1})
    return old, handoffs


def _evasive_event(frame: dict, payload: dict) -> dict:
    """EVASIVE_MANEUVER -> info event 'SAT-x evasive maneuver (SAT-y, range Z m)'
    (Addendum v1.2: additive; old logs never carry the type, so the branch is
    unreachable for them). Graceful fallbacks follow _failure_event's style --
    section 7.1: a malformed payload degrades the message, never the driver."""
    who = payload.get("sat_id")
    other = payload.get("other_id")
    if isinstance(who, int):
        who = display_sat_id(who)
    if isinstance(other, int):
        other = display_sat_id(other)
    rng = payload.get("range_m")
    rng_txt = f"{rng:.0f}" if isinstance(rng, (int, float)) else str(rng)
    return _with_sat(
        to_event(
            "info",
            frame.get("t", 0.0),
            f"{who} evasive maneuver ({other}, range {rng_txt} m)",
        ),
        who,
    )


# Plain-wording labels for the transitions the UI narrates; others keep text only.
_STATE_LABELS = {
    ("FAILURE_DETECTED", "REPLANNING"): "Planning recovery",
    ("REPLANNING", "RECONFIGURING"): "Moving to new positions",
    ("RECONFIGURING", "RECOVERED"): "Recovered",
}


def _plain_event(frame: dict, etype: str, payload: dict) -> dict:
    if etype == "STATE":  # plain transitions: {from, to}
        frm, to = payload.get("from"), payload.get("to")
        ev = to_event("info", frame.get("t", 0.0), f"State {frm} -> {to}")
        ok = isinstance(frm, str) and isinstance(to, str)  # junk payloads: text only
        label = _STATE_LABELS.get((frm, to)) if ok else None
        if label is not None:  # additive structured fields
            ev.update({"from": frm, "to": to, "label": label})
        return ev
    t = frame.get("t", 0.0)
    if etype == "DEGRADE_START":  # {sat_id, t_fail, degrade_s}
        who = _sat_label(payload.get("sat_id"))
        msg = f"{who or 'A satellite'} battery fading"
        left = _mmss(payload["t_fail"] - t) if isinstance(payload.get("t_fail"), (int, float)) \
            and isinstance(t, (int, float)) else None
        if left is not None:
            msg += f"; failure expected at T+{left}"
        return _with_sat(to_event("warning", t, msg), who)
    if etype == "ORACLE_SWAP":  # {role, from_sat, to_sat, t, mode?}
        a, b = _sat_label(payload.get("from_sat")), _sat_label(payload.get("to_sat"))
        if payload.get("mode") == "degrade_trigger":
            why = " because its battery is fading"
        else:
            why = f" before {a} fails" if a else ""
        role = payload.get("role") or "critical"
        msg = f"{a or 'A satellite'} {role} role handed to {b or 'another satellite'}{why}"
        return _with_sat(to_event("info", t, msg), a)
    if etype == "ORACLE_ALERT":  # {sat_id, lead_s, t_fail, t_warn}
        who = _sat_label(payload.get("sat_id"))
        lead = _mmss(payload.get("lead_s"))
        msg = f"Early warning: {who or 'a satellite'} expected to fail"
        if lead is not None:
            msg += f" in {lead}"
        return _with_sat(to_event("info", t, msg + "; replanning early"), who)
    return to_event("info", t, etype)  # unknown types: pass the type


def to_messages(frame: dict, enrich: SessionEnrich) -> list[dict]:
    """One log line -> [sim_state, (event?), (role_reassignment?)] (section 5.1).

    Event payloads are applied to `enrich` BEFORE the sim_state is built so the
    same tick carries the fresh target_slot / detection latency.
    """
    state = frame.get("state")
    if state == "INIT":
        return [to_sim_state(frame, enrich)]
    if state == "SUMMARY":
        # SUMMARY is never sent as a sim_state (section 6.1). run_summary goes FIRST:
        # the "Run complete" event stays the stream's last message (clients and tests
        # treat it as the terminator).
        return [
            {
                "type": "run_summary",
                "coverage_mean_last_orbit": frame.get("coverage_mean_last_orbit"),
                "sim_time": frame.get("t", 0.0),
                "scenario": enrich.scenario,
                "seed": enrich.seed,
            },
            to_event("info", frame.get("t", 0.0), "Run complete"),
        ]

    event = frame.get("event")
    reassignment: dict | None = None
    event_msg: dict | None = None
    if event:
        etype = event.get("type", "")
        payload = event.get("payload") or {}
        if etype == "FAILURE_DETECTED":
            event_msg = _failure_event(frame, payload, enrich)
        elif etype == "EVASIVE_MANEUVER":
            event_msg = _evasive_event(frame, payload)
        elif etype == "ASSIGNMENT":
            reassignment = _role_reassignment(frame, payload, enrich)
        else:
            event_msg = _plain_event(frame, etype, payload)

    old_roles, handoffs = _track_roles(frame, enrich)
    msgs = [to_sim_state(frame, enrich)]
    for row, sat in zip(msgs[0]["sats"], frame.get("sats", []), strict=True):
        if sat["id"] in old_roles:
            row["old_role"] = old_roles[sat["id"]]
    if reassignment is not None and handoffs:
        reassignment["role_handoffs"] = handoffs
    if event_msg is not None:
        msgs.append(event_msg)
    if reassignment is not None:
        msgs.append(reassignment)
    return msgs
