"""Two-step allocation (docs/MASTER_PROMPT.md section 3.3, gate G4).

Step 1 -- survivor formation: candidates are k phase-spaced slots on ONE passive
2:1 ellipse, swept over radial-amplitude multipliers and phase offsets (small
deterministic grids from the scenario). A candidate is feasible when
  (a) pairwise separation over a sampled orbit stays >= min_sep, with coasting
      dead satellites included as obstacles (they never freeze, AGENTS.md 5), and
  (b) a perfect survivor->seat matching exists whose per-transfer bang-bang
      delta-v estimate 2*sqrt(d*a_max) fits the scenario delta-v budget.
Among feasible candidates the sweep keeps the highest measured coverage (union
of the imager seats' footprints, time-averaged over one orbit); exact ties keep
the FIRST candidate in sweep order (deterministic, AGENTS.md 2).

Step 2 -- assignment: C[i,j] = w1*dist_norm + w2*dist_norm/fuel_i + w3*mismatch,
first two terms normalized to [0, 1] across the matrix, plus a tiny row-major
index epsilon; rows = survivors, cols = candidate seats; rectangular
scipy.optimize.linear_sum_assignment. The greedy nearest-seat fallback runs
behind the scenario `method` toggle; a deterministic size cap (not a wall-clock
timeout -- that would break reproducibility, AGENTS.md 2) forces the fallback on
pathological inputs.

Re-election: a critical role (unique in the original formation) whose holder
died takes a seat from the majority role before seats are laid out; imager
seats are interleaved onto even indices so the coverage-bearing seats are as
spread as the evenly-spaced slots allow.

SI units (AGENTS.md 3), LVLH frame (AGENTS.md 4), no wall clock / no RNG
(AGENTS.md 2).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import linear_sum_assignment

from cubesat.coverage import coverage_fraction
from cubesat.hcw import propagate, slot_initial_state

_TIE_EPS = 1e-9  # index-based epsilon breaking cost ties (MASTER_PROMPT 3.3)
_MAX_COST_CELLS = 4096  # deterministic size cap standing in for a timeout guard
_SWEEP_SAMPLES = 72  # orbit samples for feasibility + coverage estimates


@dataclass
class FormationPlan:
    """The selected survivor formation: seat states at t = 0 (sim convention) and
    each seat's role; coverage is the sweep's measured objective value."""

    radial_amp_m: float
    phase0_rad: float
    slots: list  # list[np.ndarray], one 6-D state per seat
    seat_roles: list[str]
    coverage: float
    method: str = ""


def seat_roles_for(survivor_roles: list[str], original_roles: list[str]) -> list[str]:
    """New role multiset for the k seats. Critical roles (unique in original_roles)
    whose holder died are re-elected first, each taking a seat from the majority
    role; surviving critical roles keep their seat. The multiset is then laid out
    with imager seats on even indices (imagers are the coverage-bearing role)."""
    seats = list(survivor_roles)
    for role in dict.fromkeys(original_roles):  # first-occurrence order, no sets
        if original_roles.count(role) == 1 and role not in seats:
            counts = {r: seats.count(r) for r in dict.fromkeys(seats)}
            majority = max(counts, key=counts.get)  # ties: insertion order, stable
            seats[seats.index(majority)] = role
    imagers = [r for r in seats if r == "imager"]
    others = [r for r in seats if r != "imager"]
    out: list[str] = []
    for j in range(len(seats)):
        if j % 2 == 0 and imagers:
            out.append(imagers.pop(0))
        else:
            out.append(others.pop(0) if others else imagers.pop(0))
    return out


def _min_separation_ok(
    seat_slots: list, obstacle_states: list, *, min_sep_m: float, n: float, t_replan: float
) -> bool:
    """Pairwise separation >= min_sep_m over one sampled orbit. Seat slots are
    t=0 states (propagated to absolute times); obstacle states are coasting
    states AT t_replan (propagated by the elapsed sample time)."""
    period = 2.0 * math.pi / n
    for m in range(_SWEEP_SAMPLES):
        tau = m * period / _SWEEP_SAMPLES
        pts = [propagate(s, t_replan + tau, n)[:3] for s in seat_slots]
        pts += [propagate(o, tau, n)[:3] for o in obstacle_states]
        for a in range(len(pts)):
            for b in range(a + 1, len(pts)):
                if float(np.linalg.norm(pts[a] - pts[b])) < min_sep_m:
                    return False
    return True


def _reachability_ok(
    survivor_states: list,
    seat_slots: list,
    *,
    a_max: float,
    dv_budget_mps: float,
    n: float,
    t_replan: float,
) -> bool:
    """A perfect matching must exist with every transfer's bang-bang delta-v
    estimate 2*sqrt(d*a_max) within the budget (MASTER_PROMPT 3.3, patch #1)."""
    surv = np.array([np.asarray(s)[:3] for s in survivor_states])
    seats = np.array([propagate(s, t_replan, n)[:3] for s in seat_slots])
    d = np.linalg.norm(surv[:, None, :] - seats[None, :, :], axis=2)
    dv = 2.0 * np.sqrt(d * a_max)
    over = (dv > dv_budget_mps).astype(float)
    rows, cols = linear_sum_assignment(over)
    return float(over[rows, cols].sum()) == 0.0


def _coverage_estimate(
    seat_slots: list, seat_roles: list[str], *, r_f: float, grid: np.ndarray, n: float,
    t_replan: float,
) -> float:
    """Time-averaged coverage of the imager seats' footprints over one orbit."""
    imager_seats = [j for j, role in enumerate(seat_roles) if role == "imager"]
    period = 2.0 * math.pi / n
    total = 0.0
    for m in range(_SWEEP_SAMPLES):
        t_abs = t_replan + m * period / _SWEEP_SAMPLES
        centers = np.array([propagate(seat_slots[j], t_abs, n)[1:3] for j in imager_seats])
        total += coverage_fraction(centers, grid, r_f)
    return total / _SWEEP_SAMPLES


def select_formation(
    survivor_states: list,
    seat_roles: list[str],
    obstacle_states: list,
    *,
    base_amp_m: float,
    amp_mults: list[float],
    phase_offsets_deg: list[float],
    min_sep_m: float,
    dv_budget_mps: float,
    a_max: float,
    r_f: float,
    grid: np.ndarray,
    n: float,
    t_replan: float,
) -> FormationPlan:
    """Step 1: best feasible (amplitude, phase offset) formation for the k seats."""
    k = len(seat_roles)
    best: FormationPlan | None = None
    for amp_mult in amp_mults:  # scenario order; ties keep the first (strictly >)
        amp = amp_mult * base_amp_m
        for phi0_deg in phase_offsets_deg:
            phi0 = math.radians(phi0_deg)
            slots = [
                slot_initial_state(amp, amp, phi0 + 2.0 * math.pi * j / k, n)
                for j in range(k)
            ]
            if not _min_separation_ok(
                slots, obstacle_states, min_sep_m=min_sep_m, n=n, t_replan=t_replan
            ):
                continue
            if not _reachability_ok(
                survivor_states,
                slots,
                a_max=a_max,
                dv_budget_mps=dv_budget_mps,
                n=n,
                t_replan=t_replan,
            ):
                continue
            cov = _coverage_estimate(slots, seat_roles, r_f=r_f, grid=grid, n=n, t_replan=t_replan)
            if best is None or cov > best.coverage:
                best = FormationPlan(amp, phi0, slots, list(seat_roles), cov)
    if best is None:
        raise RuntimeError("no feasible survivor formation in the sweep grid")
    return best


def build_cost_matrix(
    survivor_pos, seat_pos, fuel, survivor_roles: list[str], seat_roles: list[str], *,
    w1: float, w2: float, w3: float,
) -> np.ndarray:
    """C[i,j] = w1*dist_norm + w2*dist_norm/fuel_i + w3*role_mismatch, the first
    two terms normalized to [0, 1] across the matrix, plus a tiny row-major index
    epsilon (MASTER_PROMPT 3.3). Rows = survivors, cols = seats."""
    surv = np.asarray(survivor_pos, dtype=float)
    seats = np.asarray(seat_pos, dtype=float)
    d = np.linalg.norm(surv[:, None, :] - seats[None, :, :], axis=2)
    d_max = float(d.max())
    dist_norm = d / d_max if d_max > 0.0 else d * 0.0
    fuel_arr = np.maximum(np.asarray(fuel, dtype=float), 1e-12)
    fuel_term = dist_norm / fuel_arr[:, None]
    f_max = float(fuel_term.max())
    fuel_norm = fuel_term / f_max if f_max > 0.0 else fuel_term * 0.0
    mismatch = np.array(
        [[0.0 if sr == tr else 1.0 for tr in seat_roles] for sr in survivor_roles]
    )
    k, m = d.shape
    eps = _TIE_EPS * (np.arange(k)[:, None] * m + np.arange(m)[None, :])
    return w1 * dist_norm + w2 * fuel_norm + w3 * mismatch + eps


def solve_assignment(cost, method: str = "hungarian") -> tuple[list[tuple[int, int]], float, str]:
    """Assignment on the rectangular cost matrix; returns (pairs, total, method).
    Hungarian: linear_sum_assignment (rows = survivors, cols = seats). Greedy
    fallback: survivors in row order take their nearest available seat. The
    deterministic size cap replaces a wall-clock timeout (AGENTS.md 2)."""
    cost = np.asarray(cost, dtype=float)
    if method == "hungarian" and cost.size > _MAX_COST_CELLS:
        method = "greedy"
    k, m = cost.shape
    pairs: list[tuple[int, int]]
    if method == "hungarian":
        rows, cols = linear_sum_assignment(cost)
        pairs = [(int(r), int(c)) for r, c in zip(rows, cols, strict=True)]
    else:
        pairs = []
        used: set[int] = set()
        for r in range(k):
            avail = [c for c in range(m) if c not in used]
            if not avail:
                break
            c = min(avail, key=lambda c: (cost[r, c], c))
            pairs.append((r, int(c)))
            used.add(int(c))
    total = float(sum(cost[r, c] for r, c in pairs))
    return pairs, total, method


def replan(
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
    current_slots: list | None = None,
) -> tuple[FormationPlan, list[tuple[int, int]], float, str, float, np.ndarray]:
    """Full two-step allocation at t_replan; returns (plan, pairs, cost_total,
    method, max_transfer_m, cost_matrix). pairs index the GIVEN survivor order."""
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
    if current_slots is not None:
        cov_curr = _coverage_estimate(
            current_slots, survivor_roles, r_f=r_f, grid=grid, n=n, t_replan=t_replan
        )
        if plan.coverage < cov_curr:
            k = len(survivor_roles)
            hold = FormationPlan(
                base_amp_m, 0.0, current_slots, seats, cov_curr, "do_no_harm_hold"
            )
            return hold, [(i, i) for i in range(k)], 0.0, "do_no_harm_hold", 0.0, np.zeros((k, k))
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
    pairs, total, method = solve_assignment(cost, allocation.method)
    d = np.linalg.norm(surv_pos[:, None, :] - seat_pos[None, :, :], axis=2)
    max_transfer = max((float(d[r, c]) for r, c in pairs), default=0.0)
    return plan, pairs, total, method, max_transfer, cost
