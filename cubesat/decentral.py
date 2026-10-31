"""Leaderless recovery: the leader's job split into functions, auctioned over the laser mesh.

Pure, deterministic; FunctionState (end of file) is the EngineV2 glue (track C4).

Mechanism (consensus-based auction, the CBBA family; Choi, Brunet & How 2009):
  tasks are auctioned in a fixed priority order; for each task every sat bids
  bid[i, t] - load_penalty * (tasks i already won); bids spread by synchronous max-consensus
  over the CURRENT link graph (each round a sat adopts the best (bid, -id) among itself and its
  linked neighbours) until nothing changes. The winner of each connected component holds the
  task there. Rounds are counted, because consensus is not free: that cost is part of the claim.
With one connected component this equals the central sequential-greedy result; CBBA's
convergence result is that it agrees with sequential greedy under diminishing marginal gains,
which the constant load penalty gives.

If the graph is split, each component elects its own holder: `split_brain` counts tasks held
in more than one component. The centralised star (every sat linked to the leader) splits into
singletons when the hub dies; a ring/mesh does not. That is why the leader must be decentralised
once links are point-to-point.
"""

from __future__ import annotations

import math

import numpy as np

from cubesat.isl import components

LEADER_FUNCTIONS = (
    "failure_detection",
    "time_sync",
    "formation_reference",
    "collision_arbitration",
    "task_scheduling",
    "ground_relay",
)
NO_BID = -math.inf


def neighbours(n: int, links: set[tuple[int, int]], alive: list[bool]) -> list[list[int]]:
    adj = [[] for _ in range(n)]
    for i, j in sorted(links):
        if alive[i] and alive[j]:
            adj[i].append(j)
            adj[j].append(i)
    return adj


def default_bids(
    degree: list[int], fuel_frac: list[float], ground_wait_s: list[float], radio_ok: list[bool]
) -> np.ndarray:
    """(n, len(LEADER_FUNCTIONS)) bids from mission goals, not role names.

    Detection / time sync / scheduling favour well-connected sats (they hear the most
    heartbeats); formation reference and collision arbitration favour fuel (they may have to
    move); ground relay favours the shortest wait to the next ground pass. No radio, no bid."""
    n = len(degree)
    b = np.full((n, len(LEADER_FUNCTIONS)), NO_BID)
    for i in range(n):
        if not radio_ok[i]:
            continue
        conn = float(degree[i])
        relay = 1.0 / (1.0 + ground_wait_s[i] / 3600.0)
        b[i] = [conn, conn, fuel_frac[i], fuel_frac[i], conn, relay]
    return b


def auction(
    bids: np.ndarray,
    links: set[tuple[int, int]],
    alive: list[bool],
    load_penalty: float = 0.5,
    tasks: tuple[str, ...] = LEADER_FUNCTIONS,
) -> dict:
    """Run the auction. Returns {holders: {task: [sat per component]}, held: [[task] per sat],
    rounds: total consensus rounds, split_brain: tasks with >1 holder, vacant: tasks no
    component could fill}."""
    n = bids.shape[0]
    if bids.shape[1] != len(tasks) or len(alive) != n:
        raise ValueError("bids must be (n_sats, n_tasks) and alive must have n_sats entries")
    adj = neighbours(n, links, alive)
    comps = components(n, links, alive)
    load = [0] * n
    held: list[list[str]] = [[] for _ in range(n)]
    holders: dict[str, list[int]] = {}
    rounds = 0
    for t, task in enumerate(tasks):
        own = [
            (bids[i, t] - load_penalty * load[i], -i) if alive[i] and bids[i, t] > NO_BID
            else (NO_BID, -i)
            for i in range(n)
        ]
        best = list(own)
        while True:
            nxt = [max([best[i]] + [best[j] for j in adj[i]]) for i in range(n)]
            if nxt == best:
                break
            best = nxt
            rounds += 1
        holders[task] = []
        for comp in comps:
            value, neg_id = best[comp[0]]  # converged: every member agrees
            if value > NO_BID:
                w = -neg_id
                holders[task].append(w)
                held[w].append(task)
                load[w] += 1
    return {
        "holders": holders,
        "held": held,
        "rounds": rounds,
        "split_brain": sorted(k for k, v in holders.items() if len(v) > 1),
        "vacant": sorted(k for k, v in holders.items() if not v),
    }


# -- engine state (track C4: EngineV2 with recovery.authority = "decentral") ------------------
class FunctionState:
    """Who holds each leader function inside EngineV2, plus the auction still converging.

    The auction inputs are the LOCKED link set, the talking sats and who can thrust. When they
    change an auction starts; its result takes effect `rounds` ticks later (one consensus hop
    per tick: assumption). Auctions run one at a time: a change while one converges marks the
    state dirty and the next auction starts the tick the current one lands. Until then the old
    holders keep their functions; a holder that stopped talking performs nothing, so its
    functions are VACANT. The first auction (t = 0) takes effect at once (steady-state start:
    assumption). Bids (default_bids): degree over LOCKED links, fuel fraction of the tank at
    the auction start (0 for a sat that cannot thrust), ground wait 0 for every sat
    (assumption: sats km apart under a ~1000 km pass footprint share one wait, which leaves
    the argmax unchanged). The inputs are TRUE state (talking sats, thrust), not believed
    state: a sat learns its neighbour's thruster loss with no detection delay (assumption).
    Holder lists are sorted, so FUNCTION_HANDOFF `from` / `to` compare as sets."""

    def __init__(self, scenario) -> None:
        self.m_prop0 = scenario.spacecraft.m_prop_kg
        self.holders: dict[str, list[int]] = {}
        self.pending: dict | None = None  # {"k_done", "holders", "rounds"}
        self.rounds = 0  # consensus rounds of the auction now in effect
        self.key: list | None = None  # [locked links, up, can thrust] last seen
        self.dirty = False  # inputs changed since the running auction started

    def tick(self, k: int, locked, up: list[bool], sats):
        """-> (FUNCTION_HANDOFF events, {"functions": per sat, consensus_rounds, split_brain,
        functions_vacant}). locked: LOCKED links (i, j); up: talking sats; sats: SatState."""
        n = len(up)
        key = [[list(e) for e in sorted(locked)], list(up), [s.k > 0 for s in sats]]
        first = self.key is None
        if key != self.key:
            self.key, self.dirty = key, True
        out: list[dict] = []
        for _ in range(2):  # land the running auction, then start the next if dirty
            if self.pending is None and self.dirty:
                deg = [sum(i in e for e in locked) for i in range(n)]
                fuel = [s.m_prop_kg / self.m_prop0 if self.m_prop0 > 0 and s.k > 0 else 0.0
                        for s in sats]
                res = auction(default_bids(deg, fuel, [0.0] * n, up), set(locked), up)
                k_done = k if first else k + res["rounds"]
                self.pending = {"k_done": k_done, "holders": res["holders"],
                                "rounds": res["rounds"]}
                self.dirty = False
            if self.pending is None or k < self.pending["k_done"]:
                break
            new = {f: sorted(h) for f, h in self.pending["holders"].items()}
            for f in LEADER_FUNCTIONS if self.holders else ():
                if self.holders[f] != new[f]:
                    payload = {"function": f, "from": self.holders[f], "to": new[f]}
                    out.append({"type": "FUNCTION_HANDOFF", "payload": payload})
            self.holders, self.rounds, self.pending = new, self.pending["rounds"], None
        live = {f: [i for i in h if up[i]] for f, h in self.holders.items()}
        return out, {
            "functions": [[f for f in LEADER_FUNCTIONS if i in live[f]] for i in range(n)],
            "consensus_rounds": self.rounds,
            "split_brain": [f for f in LEADER_FUNCTIONS if len(live[f]) > 1],
            "functions_vacant": [f for f in LEADER_FUNCTIONS if not live[f]],
        }

    def state(self) -> dict:
        return {"holders": self.holders, "pending": self.pending, "rounds": self.rounds,
                "key": self.key, "dirty": self.dirty}

    def load(self, state: dict, n: int) -> None:
        """Replace every field; raises ValueError and leaves self unchanged on a bad state."""

        def ids(v, what):
            if not isinstance(v, list) or any(type(i) is not int or not 0 <= i < n for i in v):
                raise ValueError(f"{what} must be a list of sat ids")
            return list(v)

        def flags(v, what):
            if not isinstance(v, list) or len(v) != n or any(type(b) is not bool for b in v):
                raise ValueError(f"{what} must hold {n} booleans")
            return list(v)

        def holders(h):
            if not isinstance(h, dict) or sorted(h) != sorted(LEADER_FUNCTIONS):
                raise ValueError("holders must map every leader function to sat ids")
            return {f: ids(h[f], f) for f in LEADER_FUNCTIONS}

        def count(v, what):
            if type(v) is not int or v < 0:
                raise ValueError(f"{what} must be an int >= 0")
            return v

        try:
            key, p = state["key"], state["pending"]
            started = key is not None
            hold = holders(state["holders"]) if started or state["holders"] else {}
            pending = None if p is None else {"k_done": count(p["k_done"], "k_done"),
                                              "holders": holders(p["holders"]),
                                              "rounds": count(p["rounds"], "rounds")}
            rounds, dirty = count(state["rounds"], "rounds"), state["dirty"]
            if type(dirty) is not bool:
                raise ValueError("dirty must be a boolean")
            if started:
                links, up, thrust = key
                for e in links:
                    if len(ids(e, "link")) != 2 or not e[0] < e[1]:
                        raise ValueError("links must be [i, j] with i < j")
                key = [[list(e) for e in links], flags(up, "up"), flags(thrust, "thrust")]
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ValueError(f"bad function state in snapshot: {exc!r}") from exc
        self.holders, self.pending, self.rounds, self.key = hold, pending, rounds, key
        self.dirty = dirty
