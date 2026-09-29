"""Benchmark policy overrides for the replan seam (docs/ENDGAME_PLAN.md 3.2-3.3).

Pure functions with EXACTLY the cubesat.allocate.replan signature and 6-tuple
return; the driver (cubesat.benchmark) rebinds cubesat.sim.replan to one of
these inside the benchmark process only, with try/finally restore (the seam is
sim.py's module-global replan resolution at its call site). Core files on disk
are untouched -- P0 is zero-core-diff.

Determinism: index iteration only, no sets/dict-order dependence, no RNG, no
wall clock (AGENTS.md invariant 2). SI units (invariant 3), LVLH (invariant 4).
"""

from __future__ import annotations

import math

import numpy as np

from cubesat.allocate import (
    _SWEEP_SAMPLES,
    FormationPlan,
    _coverage_estimate,
    build_cost_matrix,
    propagate,
    seat_roles_for,
    select_formation,
    slot_initial_state,
    solve_assignment,
)  # noqa: I001

# Policy 5 weight, pinned for reproducibility (ENDGAME_PLAN 3.3): dimensionless,
# on the same O(1) normalized scale as the build_cost_matrix terms. If a sweep
# is ever needed it draws from {0.5, 1.0, 2.0} with the chosen value recorded in
# benchmark_manifest.json -- no unpinned knob ships.
W4 = 1.0


def _identity_pairs(k: int) -> list[tuple[int, int]]:
    return [(i, i) for i in range(k)]


def even_split_replan(
    survivor_states: list,
    survivor_roles: list[str],
    survivor_fuel: list[float],
    obstacle_states: list,
    original_roles: list[str],
    allocation,
    base_amp_m: float,
    r_f: float,
    grid: np.ndarray,
    n: float,
    a_max: float,
    t_replan: float,
) -> tuple[FormationPlan, list[tuple[int, int]], float, str, float, np.ndarray]:
    """Policy 2 -- even redistribution, ADAPTED from the RL-retasking literature's
    even-split rule (which splits TASK LOAD among survivors). The adaptation
    re-spaces the dead slots' phase duty across the ORIGINAL n_orig-slot ellipse
    in closed form: survivor i (in given id order) takes re-phased slot
    round(i * (n_orig - 1) / (k - 1)) on the fixed grid -- for 4 survivors on 6
    slots that is phase indices {0, 2, 3, 5}, i.e. NOT uniform spacing (gaps
    2, 1, 2, 1). Identity assignment, no optimization, NO formation sweep and NO
    feasibility check (deliberately forgoes allocate.select_formation) -- any
    min-separation or settling shortfall is a measured benchmark outcome.

    The common phase offset is allocation.phase_sweep_deg[0] (the base scenario's
    original formation offset is 0.0, which is that list's first entry)."""
    k = len(survivor_roles)
    n_orig = len(original_roles)
    seats = seat_roles_for(survivor_roles, original_roles)
    phase0 = math.radians(allocation.phase_sweep_deg[0])
    if k > 1:
        indices = [round(i * (n_orig - 1) / (k - 1)) for i in range(k)]
    else:
        indices = [0]
    slots = [
        slot_initial_state(base_amp_m, base_amp_m, phase0 + 2.0 * math.pi * j / n_orig, n)
        for j in indices
    ]
    coverage = _coverage_estimate(slots, seats, r_f=r_f, grid=grid, n=n, t_replan=t_replan)
    plan = FormationPlan(base_amp_m, phase0, slots, seats, coverage)
    pairs = _identity_pairs(k)
    surv_pos = np.array([np.asarray(s)[:3] for s in survivor_states])
    seat_pos = np.array([propagate(s, t_replan, n)[:3] for s in slots])
    cost = build_cost_matrix(
        surv_pos,
        seat_pos,
        survivor_fuel,
        survivor_roles,
        seats,
        w1=allocation.w1,
        w2=allocation.w2,
        w3=allocation.w3,
    )
    total = float(sum(cost[r, c] for r, c in pairs))
    d = np.linalg.norm(surv_pos[:, None, :] - seat_pos[None, :, :], axis=2)
    max_transfer = max((float(d[r, c]) for r, c in pairs), default=0.0)
    return plan, pairs, total, "even_split", max_transfer, cost


def keepout_penalties(
    seat_slots: list,
    obstacle_states: list,
    *,
    r_ko_m: float,
    n: float,
    t_replan: float,
    samples: int = _SWEEP_SAMPLES,
) -> list[float]:
    """Per-seat keep-out penalty clamp((r_ko - d)/r_ko, 0, 1), where d = the
    seat's min distance to any propagated dead-sat state over one sampled orbit
    from t_replan (the module's standard sampling convention, _SWEEP_SAMPLES;
    a conservative superset of the reconfig window). Seat slots are t=0 states;
    obstacle states are coasting states AT t_replan -- the same conventions as
    allocate._min_separation_ok. Index iteration only; no obstacles -> all zeros."""
    period = 2.0 * math.pi / n
    penalties: list[float] = []
    for slot in seat_slots:
        d_min = math.inf
        for m in range(samples):
            tau = m * period / samples
            seat = propagate(slot, t_replan + tau, n)[:3]
            for obstacle in obstacle_states:
                dead = propagate(obstacle, tau, n)[:3]
                d_min = min(d_min, float(np.linalg.norm(seat - dead)))
        penalty = (r_ko_m - d_min) / r_ko_m
        penalties.append(min(1.0, max(0.0, penalty)))
    return penalties


def hungarian_keepout_replan(
    survivor_states: list,
    survivor_roles: list[str],
    survivor_fuel: list[float],
    obstacle_states: list,
    original_roles: list[str],
    allocation,
    base_amp_m: float,
    r_f: float,
    grid: np.ndarray,
    n: float,
    a_max: float,
    t_replan: float,
) -> tuple[FormationPlan, list[tuple[int, int]], float, str, float, np.ndarray]:
    """Policy 5 -- the shipped Hungarian path with ONE extra additive cost term:
    C = build_cost_matrix(...) + W4 * keep-out penalty per seat (dead satellites
    coast as obstacles, AGENTS.md invariant 5; keep-out radius = allocation.min_sep_km,
    the same threshold the sim's min_sep gate enforces). Step 1 keeps the FULL
    formation sweep (unchanged from allocate.replan); only the step-2 cost is
    augmented, and the assignment stays linear_sum_assignment."""
    seats = seat_roles_for(survivor_roles, original_roles)
    plan = select_formation(
        survivor_states,
        seats,
        obstacle_states,
        base_amp_m=base_amp_m,
        amp_mults=list(allocation.amp_sweep),
        phase_offsets_deg=list(allocation.phase_sweep_deg),
        min_sep_m=allocation.min_sep_km * 1000.0,
        dv_budget_mps=allocation.dv_budget_mps,
        a_max=a_max,
        r_f=r_f,
        grid=grid,
        n=n,
        t_replan=t_replan,
    )
    surv_pos = np.array([np.asarray(s)[:3] for s in survivor_states])
    seat_pos = np.array([propagate(s, t_replan, n)[:3] for s in plan.slots])
    cost = build_cost_matrix(
        surv_pos,
        seat_pos,
        survivor_fuel,
        survivor_roles,
        plan.seat_roles,
        w1=allocation.w1,
        w2=allocation.w2,
        w3=allocation.w3,
    )
    penalties = keepout_penalties(
        plan.slots,
        obstacle_states,
        r_ko_m=allocation.min_sep_km * 1000.0,
        n=n,
        t_replan=t_replan,
    )
    cost = cost + W4 * np.asarray(penalties, dtype=float)[None, :]
    pairs, total, _ = solve_assignment(cost, "hungarian")
    d = np.linalg.norm(surv_pos[:, None, :] - seat_pos[None, :, :], axis=2)
    max_transfer = max((float(d[r, c]) for r, c in pairs), default=0.0)
    return plan, pairs, total, "hungarian_keepout", max_transfer, cost
