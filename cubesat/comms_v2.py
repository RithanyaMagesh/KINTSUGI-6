"""Laser crosslinks inside EngineV2 (track C2; opt-in `comms.model = "laser"`).

Each tick, after the failures of the tick have fired and before the heartbeat rule runs:
  1. every planned link steps its state machine (cubesat/isl.py): unusable when a partner is
     down (dead, radio dead, re-entered), the budget does not close, or the sun is inside either
     end's receive cone (sun vector from cubesat/geo_v2.py, rotated to LVLH);
  2. the topology is replanned only on a topology event: the set of talking sats changed, a
     LOCKED link was lost, or (star) the hub moved. Mesh keeps the LOCKED links (isl.plan_topology
     keep=); star links every talking sat to the current leader holder;
  3. components = connected sets of talking sats over LOCKED links. A talking sat alone in its
     component is ISOLATED: nobody hears its heartbeat (cubesat/faults_v2.py detect()).
Assumptions (label them wherever shown): the sim starts in steady state, so the first topology
starts LOCKED; a dark terminal is visible to the planner (no beacon), so replans route around a
silent sat at once; the star hub carries n-1 terminals; heartbeats cross a component in one tick.
Link state on line t is the state after this tick's step: a link usable from line t locks on
line t + (ceil(acquire_s / dt) - 1) dt.
"""

from __future__ import annotations

import numpy as np

from cubesat import geo_v2, isl, truth
from cubesat.faults_v2 import STATUS_REENTERED
from cubesat.sim import STATUS_DEAD


def sun_lvlh(chief: np.ndarray, epoch_utc: str, t: float) -> np.ndarray:
    """Unit sun direction in the chief's LVLH frame at sim time t (chief = ECI [r, v])."""
    return truth.lvlh_dcm(chief[:3], chief[3:]) @ np.array(geo_v2.sun_direction_eci(epoch_utc, t))


class CommsState:
    """Planned links, their state machines and the last topology (JSON-serialisable)."""

    def __init__(self, scenario) -> None:
        cfg = scenario.comms
        self.term = isl.Terminal(**cfg.terminal.model_dump())
        self.star = cfg.topology == "star"
        self.epoch = scenario.chief.epoch_utc
        self.links: dict[tuple[int, int], list] = {}  # (i, j) i < j -> [state, timer_s]
        self.up: list[bool] | None = None  # talking sats at the last tick (None = not started)
        self.hub: int | None = None
        self.n_comp = 0

    def tick(self, t, dt, pos, chief, status, sats, roles) -> tuple[dict, list[dict], list[bool]]:
        """-> (log fields {links, components}, events, isolated per sat)."""
        n = len(status)
        up = [st not in (STATUS_DEAD, STATUS_REENTERED) and s.radio_ok
              for st, s in zip(status, sats, strict=True)]
        sun = sun_lvlh(chief, self.epoch, t)
        events: list[dict] = []
        first = self.up is None
        lost = any([self._step(e, link, pos, up, sun, dt, events) for e, link in
                    sorted(self.links.items())])
        hub = next((i for i, r in enumerate(roles) if "leader" in r), None) if self.star else None
        if first or lost or up != self.up or hub != self.hub:
            if not self.star:
                keep = {e for e, link in self.links.items() if link[0] == isl.LOCKED}
                plan = isl.plan_topology(pos, up, self.term, keep=keep)
            elif hub is not None and up[hub]:
                plan = {e for e in isl.star_topology(hub, n) if up[e[0]] and up[e[1]]}
            else:
                plan = set()
            old = self.links
            init = [isl.LOCKED if first else isl.DOWN, 0.0]  # steady-state start: assumption
            self.links = {e: old.get(e, list(init)) for e in sorted(plan)}
            for e in sorted(plan - old.keys()):  # new links start acquiring this tick
                self._step(e, self.links[e], pos, up, sun, dt, events)
        self.up, self.hub = up, hub
        locked = {e for e, link in self.links.items() if link[0] == isl.LOCKED}
        comps = isl.components(n, locked, up)
        if not first and len(comps) > self.n_comp:
            events.append({"type": "PARTITION", "payload": {"components": comps}})
        self.n_comp = len(comps)
        rows = []
        for (i, j), (state, _) in self.links.items():
            r = float(np.linalg.norm(pos[i] - pos[j]))
            rate = isl.data_rate_bps(r, self.term) if state == isl.LOCKED else 0.0
            rows.append([i, j, state, r, rate])
        isolated = [False] * n
        for c in comps:
            if len(c) == 1:
                isolated[c[0]] = True
        return {"links": rows, "components": comps}, events, isolated

    def _step(self, e, link, pos, up, sun, dt, events) -> bool:
        """Step one link in place, append LINK_LOCKED / LINK_LOST; True if a LOCKED link fell."""
        reason = self._blocked(*e, pos, up, sun)
        was = link[0]
        link[:] = isl.step_link(was, link[1], reason is None, dt, self.term)
        if was != isl.LOCKED and link[0] == isl.LOCKED:
            events.append({"type": "LINK_LOCKED", "payload": {"link": list(e)}})
        if was == isl.LOCKED and link[0] == isl.DOWN:
            events.append({"type": "LINK_LOST", "payload": {"link": list(e), "reason": reason}})
            return True
        return False

    def _blocked(self, i, j, pos, up, sun) -> str | None:
        """Why link (i, j) is unusable now, or None."""
        if not (up[i] and up[j]):
            return "partner_down"
        los = pos[j] - pos[i]
        r = float(np.linalg.norm(los))
        if r <= 0.0 or isl.margin_db(r, self.term) < 0.0:
            return "budget"
        if isl.sun_blinded(los, sun, self.term) or isl.sun_blinded(-los, sun, self.term):
            return "sun"
        return None

    def state(self) -> dict:
        links = [[i, j, s, tm] for (i, j), (s, tm) in sorted(self.links.items())]
        return {"links": links, "up": self.up, "hub": self.hub, "n_comp": self.n_comp}

    def load(self, state: dict) -> None:
        """Replace every field; raises ValueError and leaves self unchanged on a bad state."""
        try:
            links = {(int(i), int(j)): [str(s), float(tm)] for i, j, s, tm in state["links"]}
            up = None if state["up"] is None else [bool(u) for u in state["up"]]
            hub = None if state["hub"] is None else int(state["hub"])
            n_comp = int(state["n_comp"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"bad comms state in snapshot: {exc!r}") from exc
        self.links, self.up, self.hub, self.n_comp = links, up, hub, n_comp


def fault_tick(comms, faults, t, dt, lvlh, chief, roles, vel_eci) -> tuple[list[dict], dict]:
    """EngineV2's hook: faults.tick() unchanged without laser comms (-> events, {}); with them
    fire failures, step the links, then run the heartbeat rule over the link graph."""
    if comms is None:
        return faults.tick(t, vel_eci), {}
    events = faults.fire(t, vel_eci)
    fields, link_events, isolated = comms.tick(
        t, dt, lvlh[:, :3], chief, faults.status, faults.sats, roles
    )
    return events + link_events + faults.detect(t, isolated), fields
