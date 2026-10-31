"""Plan certificate (physics Phase 5d): "every plan is checked for fuel, collision and roles in a
higher-fidelity model before it flies". A PURE library: not wired into the engine yet (Phase 5d-2).

`certify(plan, state, scenario, d_safe_m=...)` forward-simulates the plan being EXECUTED in the
truth model (cubesat/certify_sim.py: the EngineV2 stepper on a copy of the swarm; dead and silent
sats coast with the dead drag area) and evaluates ALL checks, so the report is complete even after
the first failure:
  separation  min pairwise distance over the horizon, every sat incl. dead ones >= d_safe_m
  fuel        static: each mover sum |dv_k| (L2) <= remaining tank delta-v * (1 - fuel_reserve), and
              it can move at all (k > 0, tank, radio, burns fit in the step cap); flown: every live
              sat ends with >= fuel_reserve of its starting tank delta-v and none runs dry
  roles       leader AND downlink held once each, on sats capable in the TRUE state, no stacking of
              non-stackable roles while a free capable sat exists
  coverage    mean imager coverage of the final seats over one orbit >= coverage_floor, or >= the
              coverage of holding the current seats with the current roles; an imager that does
              not reach its seat earns nothing
  landing     each mover's TRUTH position error vs its seat at its plan end <= landing_tol_m
  settled     every live sat is within landing_tol_m of its seat at the horizon end
  horizon     the horizon is at least MIN_HORIZON_ORBITS (it always runs PLAN_TAIL_ORBITS past the
              plan end); a shorter request is simulated and reported but cannot pass
Defaults (fuel_reserve 0.20, landing_tol_m 50, horizon 2 orbits) are illustrative.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field

import numpy as np

from cubesat.certify_checks import (
    DEAD,
    check_coverage,
    check_fuel_flown,
    check_fuel_planned,
    check_roles,
)
from cubesat.certify_sim import (
    CertificateCancelled,
    SwarmState,
    burn_span,
    simulate,
    swarm_state_from_engine,
    transfer_arrays,
    validate_state,
)
from cubesat.hcw import mean_motion, propagate
from cubesat.roles_v2 import ROLE_SPECS, capability
from cubesat.scenario import Scenario
from cubesat.transfer import Transfer

__all__ = [
    "Certificate",
    "CertificateCancelled",
    "Plan",
    "PlanItem",
    "SwarmState",
    "certify",
    "swarm_state_from_engine",
]
MIN_HORIZON_ORBITS = 2.0
PLAN_TAIL_ORBITS = 1.0


@dataclass(frozen=True, eq=False)
class PlanItem:
    """One sat's part of a plan. transfer None = hold. seat = 6-D LVLH state at the formation's
    t = 0 (hcw.propagate(seat, t) is the seat at absolute time t, as the engine's `refs`);
    transfer.times are seconds from plan.t_start_s. roles = the roles the sat holds afterwards."""

    sat_id: int
    transfer: Transfer | None
    seat: np.ndarray
    roles: tuple[str, ...] = ()


@dataclass(frozen=True, eq=False)
class Plan:
    """Items for the movers and holders; a sat without an item holds its current seat and keeps
    its current roles (an empty plan is 'do nothing'). level = the ladder level label (opaque).
    t_start_s must equal state.t_s (the plan was built for that moment)."""

    items: tuple[PlanItem, ...]
    level: str
    t_start_s: float


@dataclass
class Certificate:
    passed: bool
    reasons: list[str] = field(default_factory=list)  # the failed checks; empty when passed
    notes: list[str] = field(default_factory=list)  # not failures (e.g. an item for a dead sat)
    level: str = ""
    min_sep_m: float = 0.0
    min_sep_pair: tuple[int, int] = (0, 0)
    min_sep_t_s: float = 0.0
    worst_fuel_margin_mps: float = 0.0  # min(planned, flown); 0.0 with sat None if nothing flies
    worst_fuel_sat: int | None = None
    planned_fuel_margin_mps: float = 0.0  # movers only: remaining (1 - reserve) - planned L2
    roles_ok: bool = True
    vacant_roles: list[str] = field(default_factory=list)
    coverage: float = 0.0
    hold_coverage: float = 0.0
    landing_error_m: float = 0.0
    settled_error_m: float = 0.0
    horizon_s: float = 0.0

    def event_payload(self) -> dict:
        """The CERTIFICATE event payload; every float finite (ValueError otherwise)."""
        out = {"passed": bool(self.passed), "level": str(self.level)}
        for k in ("min_sep_m", "worst_fuel_margin_mps"):
            out[k] = _finite(getattr(self, k), k)
        out["roles_ok"] = bool(self.roles_ok)
        for k in ("coverage", "hold_coverage", "landing_error_m"):
            out[k] = _finite(getattr(self, k), k)
        out["reasons"] = [str(r) for r in self.reasons]
        return out


def _finite(v, name: str) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number, got {v!r}") from None
    if not math.isfinite(f):
        raise ValueError(f"{name} must be finite, got {v!r}")
    return f


def _check_inputs(plan: Plan, state: SwarmState, scenario: Scenario, period_s: float) -> None:
    n = scenario.n_sats
    if abs(_finite(plan.t_start_s, "plan.t_start_s") - _finite(state.t_s, "state.t_s")) > 1e-6:
        raise ValueError(f"plan.t_start_s={plan.t_start_s} != state.t_s={state.t_s}")
    validate_state(state, n)
    seen = set()
    for it in plan.items:
        if isinstance(it.sat_id, bool) or not isinstance(it.sat_id, int | np.integer):
            raise ValueError(f"sat_id must be an int, got {it.sat_id!r}")
        if not 0 <= it.sat_id < n:
            raise ValueError(f"plan references unknown sat id {it.sat_id} (swarm has {n})")
        if it.sat_id in seen:
            raise ValueError(f"plan has two items for sat {it.sat_id}")
        seen.add(it.sat_id)
        seat = np.asarray(it.seat, dtype=float)
        if seat.shape != (6,) or not np.all(np.isfinite(seat)):
            raise ValueError(f"sat {it.sat_id}: seat must be a finite (6,) state")
        for r in it.roles:
            if r not in ROLE_SPECS:
                raise ValueError(f"sat {it.sat_id}: unknown role {r!r}; known {sorted(ROLE_SPECS)}")
        if it.transfer is not None:
            transfer_arrays(it.transfer, f"sat {it.sat_id}", period_s)


def certify(
    plan: Plan,
    state: SwarmState,
    scenario: Scenario,
    *,
    d_safe_m: float,
    horizon_orbits: float = 2.0,
    fuel_reserve: float = 0.20,
    landing_tol_m: float = 50.0,
    coverage_floor: float | None = None,
    cancel_event: threading.Event | None = None,
) -> Certificate:
    """Certificate for `plan` from `state` (never mutated). ValueError on malformed input,
    CertificateCancelled (a RuntimeError) when cancel_event is set between simulation steps."""
    if _finite(d_safe_m, "d_safe_m") <= 0.0:
        raise ValueError(f"d_safe_m must be > 0, got {d_safe_m!r}")
    if _finite(horizon_orbits, "horizon_orbits") <= 0.0:
        raise ValueError(f"horizon_orbits must be > 0, got {horizon_orbits!r}")
    if not 0.0 <= _finite(fuel_reserve, "fuel_reserve") < 1.0:
        raise ValueError(f"fuel_reserve must be in [0, 1), got {fuel_reserve!r}")
    if _finite(landing_tol_m, "landing_tol_m") < 0.0:
        raise ValueError(f"landing_tol_m must be >= 0, got {landing_tol_m!r}")
    if landing_tol_m >= d_safe_m:  # a sat "on its seat" must not count as a collision risk
        raise ValueError(f"landing_tol_m={landing_tol_m} must be < d_safe_m={d_safe_m}")
    if coverage_floor is not None:
        _finite(coverage_floor, "coverage_floor")
    n = mean_motion(scenario.chief.altitude_km * 1000.0)
    period, dt = 2.0 * math.pi / n, scenario.dt_s
    _check_inputs(plan, state, scenario, period)
    items = {int(it.sat_id): it for it in plan.items}
    cmd_ok = [capability(s, True, True, "leader") for s in state.status]  # a reporting sat
    live = [i for i in range(len(state.sats)) if state.status[i] not in DEAD]  # a re-entry counts
    passive = {  # cannot thrust at the start: coasts, not judged by settled, keeps its seat
        i for i in live
        if (state.sats[i].k <= 0.0 or state.sats[i].depleted) and state.sats[i].stuck_vec is None
    }
    seats_now = np.array(state.refs, dtype=float)
    notes, reasons = [], []
    for i, it in items.items():
        seat = propagate(it.seat, plan.t_start_s, n)
        if i in passive:
            moved = float(np.linalg.norm(seat[:3] - state.refs[i, :3]))
            if moved > 1e-3 or float(np.linalg.norm(seat[3:] - state.refs[i, 3:])) > 1e-6:
                reasons.append(
                    f"seat: sat {i} cannot thrust (k = 0 or empty tank); the plan moves its "
                    f"seat by {moved:.1f} m"
                )
        elif cmd_ok[i]:  # a sat that cannot be commanded keeps flying its old seat
            seats_now[i] = seat
        elif it.transfer is None:
            notes.append(f"sat {i} ({state.status[i]}): plan item ignored, it cannot be commanded")
    movers = {i: it.transfer for i, it in items.items() if it.transfer is not None}
    plan_margin, plan_sat, flyable = check_fuel_planned(
        movers, state, cmd_ok, fuel_reserve, dt, round(PLAN_TAIL_ORBITS * period / dt), reasons
    )
    tail = round(PLAN_TAIL_ORBITS * period / dt)
    ends = [burn_span(tr, state.sats[i], dt)[2] + tail for i, tr in flyable.items()]
    steps = max([max(1, round(horizon_orbits * period / dt)), *ends])
    res = simulate(scenario, state, seats_now, flyable, steps, cancel_event)

    if res.min_sep_m < d_safe_m:
        a, b = res.min_sep_pair
        reasons.append(
            f"separation: sats {a} and {b} come within {res.min_sep_m:.1f} m at t = "
            f"{res.min_sep_t_s:.0f} s, below the {d_safe_m:.1f} m limit"
        )
    flown, flown_sat = check_fuel_flown(state, res, fuel_reserve, reasons)
    worst, worst_sat = (flown, flown_sat) if flown < math.inf else (0.0, None)
    if plan_sat is not None and (worst_sat is None or plan_margin < worst):
        worst, worst_sat = plan_margin, plan_sat
    final_roles = [
        list(items[i].roles) if i in items else list(r) for i, r in enumerate(state.roles)
    ]
    vacant, roles_ok = check_roles(final_roles, state, scenario, reasons)
    active = [i for i in live if i not in passive]
    far = {i for i in active if res.tail_err_m[i] > landing_tol_m}
    dry = {i for i in live if state.sats[i].m_prop_kg > 0.0 >= res.final_sats[i].m_prop_kg}
    coverage, hold_cov = check_coverage(
        seats_now, final_roles, state, scenario, coverage_floor, far | dry, reasons
    )
    landing = max(res.landing_m.values(), default=0.0)
    for i, err in sorted(res.landing_m.items()):
        if err > landing_tol_m:
            reasons.append(
                f"landing: sat {i} ends {err:.1f} m from its seat in the truth model "
                f"(limit {landing_tol_m:.1f} m)"
            )
    settled = max((float(res.tail_err_m[i]) for i in active), default=0.0)
    for i in sorted(far):
        reasons.append(
            f"settled: sat {i} is up to {res.tail_err_m[i]:.1f} m from its seat over the final "
            f"orbit (limit {landing_tol_m:.1f} m)"
        )
    notes += [
        f"sat {i} is passive (cannot thrust): drifts up to {res.max_err_m[i]:.1f} m from its seat"
        for i in sorted(passive)
    ]
    if horizon_orbits < MIN_HORIZON_ORBITS:
        reasons.append(
            f"horizon: {horizon_orbits:g} orbits requested, at least {MIN_HORIZON_ORBITS:g} "
            "are needed to certify"
        )
    return Certificate(
        passed=not reasons,
        reasons=reasons,
        notes=notes,
        level=plan.level,
        min_sep_m=res.min_sep_m,
        min_sep_pair=res.min_sep_pair,
        min_sep_t_s=res.min_sep_t_s,
        worst_fuel_margin_mps=worst,
        worst_fuel_sat=worst_sat,
        planned_fuel_margin_mps=plan_margin,
        roles_ok=roles_ok,
        vacant_roles=vacant,
        coverage=coverage,
        hold_coverage=hold_cov,
        landing_error_m=landing,
        settled_error_m=settled,
        horizon_s=res.n_steps * dt,
    )
