"""Leaderless recovery: the leader's job split into functions, auctioned over the laser mesh.

Pure, deterministic. Not wired into the engines yet (track C plan, step C4).

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
