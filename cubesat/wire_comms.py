"""Laser-comms and decentral-authority pass-through for the wire (track C6; engine v2, laser).

Additive only: a log line without `links` / `components` gains no key, so v1 and non-laser v2
wire bytes are unchanged. Sat ids become display ids ("SAT-n") like every other wire id. A
non-finite range or rate becomes null (a NaN would make api._wire_text drop the whole frame);
a malformed row or component is dropped, never invented, never a crash (section 7.1).
"""

from __future__ import annotations

import math


def _sat(i: object) -> str | None:
    ok = isinstance(i, int) and not isinstance(i, bool)
    return f"SAT-{i + 1}" if ok else None


def _num(x: object) -> float | None:
    if not isinstance(x, (int, float)) or isinstance(x, bool):
        return None
    try:
        return x if math.isfinite(x) else None
    except OverflowError:  # a 400-digit JSON integer
        return None


def _pair(link: object) -> list[str] | None:
    if not isinstance(link, (list, tuple)) or len(link) != 2:
        return None
    a, b = _sat(link[0]), _sat(link[1])
    return [a, b] if a and b else None


def _link_row(row: object) -> list | None:
    if not isinstance(row, (list, tuple)) or len(row) != 5 or not isinstance(row[2], str):
        return None
    pair = _pair(row[:2])
    return None if pair is None else [*pair, row[2], _num(row[3]), _num(row[4])]


def _components(comps: object) -> list[list[str]] | None:
    if not isinstance(comps, list):
        return None
    out = [[s for s in map(_sat, c) if s] for c in comps if isinstance(c, list)]
    return [c for c in out if c]


def tick_fields(frame: dict) -> dict:
    """{links, components, consensus_rounds, split_brain, functions_vacant} for sim_state, only
    for the keys the log line carries."""
    out: dict = {}
    if isinstance(frame.get("links"), list):
        out["links"] = [r for r in map(_link_row, frame["links"]) if r is not None]
    if "components" in frame:
        comps = _components(frame["components"])
        if comps is not None:
            out["components"] = comps
    if "consensus_rounds" in frame:  # decentral authority (C4): a count, not seconds
        out["consensus_rounds"] = _num(frame["consensus_rounds"])
    for key in ("split_brain", "functions_vacant"):
        if isinstance(frame.get(key), list):
            out[key] = [f for f in frame[key] if isinstance(f, str)]
    return out


_LOST = {
    "sun": ("warning", "lost: the sun is in a receiver's view"),
    "partner_down": ("warning", "lost: a partner is down"),
    "budget": ("warning", "lost: out of link budget"),
    "replan": ("info", "dropped: the network re-routed"),
}


def _ev(t: object, level: str, message: str, **extra) -> dict:
    """Same shape as wire.to_event, plus additive structured fields."""
    return {"type": "event", "sim_time": t, "level": level, "message": message, **extra}


def _sats(ids: object) -> list[str] | None:
    if not isinstance(ids, list):
        return None
    out = [_sat(i) for i in ids]
    return None if None in out else out


def _handoff(t: object, payload: dict) -> dict:
    """FUNCTION_HANDOFF{function, from: [ids], to: [ids]} (C4; one holder per component)."""
    f, a, b = payload.get("function"), _sats(payload.get("from")), _sats(payload.get("to"))
    if not isinstance(f, str) or a is None or b is None:
        return _ev(t, "info", "Consensus auction: a leader function changed holder")
    name, extra = f.replace("_", " "), {"function": f, "from": a, "to": b}
    if not b:
        was = f" (was {', '.join(a)})" if a else ""
        return _ev(t, "warning", f"{name} is vacant: no satellite holds it{was}", **extra)
    if not a:
        return _ev(t, "info", f"Consensus auction: {', '.join(b)} took over {name}", **extra)
    msg = f"Consensus auction: {name} moved from {', '.join(a)} to {', '.join(b)}"
    if len(b) > 1:
        return _ev(t, "warning", msg + " (split-brain: one holder per group)", **extra)
    return _ev(t, "info", msg, **extra)


def comms_event(t: object, etype: str, payload: dict) -> dict | None:
    """LINK_LOCKED / LINK_LOST / PARTITION / FUNCTION_HANDOFF -> event message; None otherwise."""
    if etype == "FUNCTION_HANDOFF":
        return _handoff(t, payload)
    if etype == "PARTITION":
        comps = _components(payload.get("components"))
        if len(comps or []) < 2:  # a split needs two groups
            return _ev(t, "warning", "Swarm split")
        groups = " | ".join(", ".join(c) for c in comps)
        return _ev(t, "warning", f"Swarm split into {len(comps)} groups: {groups}",
                   components=comps)
    if etype not in ("LINK_LOCKED", "LINK_LOST"):
        return None
    pair = _pair(payload.get("link"))
    name = f"Laser link {pair[0]} to {pair[1]}" if pair else "Laser link"
    extra: dict = {"link": pair} if pair else {}
    if etype == "LINK_LOCKED":
        return _ev(t, "info", f"{name} locked", **extra)
    reason = payload.get("reason")
    level, text = ("warning", "lost")
    if isinstance(reason, str):
        level, text = _LOST.get(reason, (level, text))
        extra["reason"] = reason
    return _ev(t, level, f"{name} {text}", **extra)


def isolated_event(t: object, payload: dict) -> dict:
    """FAILURE_DETECTED{cause: "isolated"}: a healthy sat nobody hears ("cut off", not failed)."""
    who = _sat(payload.get("sat_id"))
    msg = f"{who or 'A satellite'} cut off: no laser link reaches it, so the swarm cannot hear it"
    return _ev(t, "warning", msg, **({"sat_id": who} if who else {}), cause="isolated")
