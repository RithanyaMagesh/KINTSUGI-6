"""Plan certificate (physics Phase 5d-1): "every plan is checked for fuel, collision and roles in a
higher-fidelity model before it flies". A PURE library: not wired into the engine yet (Phase 5d-2).

`certify(plan, state, scenario, d_safe_m=...)` forward-simulates the plan being EXECUTED in the
truth model (cubesat/certify_sim.py: the EngineV2 stepper on a copy of the swarm; dead and silent
sats coast with the dead drag area) for a horizon of 2 chief orbits (longer if a transfer needs
it) and evaluates ALL five checks, so the report is complete even after the first failure:
  1 separation  min pairwise distance over the horizon, every sat incl. dead ones >= d_safe_m
  2 fuel        each mover: sum |dv_k| (L2) <= remaining tank delta-v * (1 - fuel_reserve);
                a mover with k = 0, an empty tank or no radio cannot move at all
  3 roles       leader AND downlink (the critical roles the scenario labels) are held, and every
                role in the plan sits on a sat that is capable in the TRUE state (roles_v2)
  4 coverage    mean imager coverage of the final seats over one orbit >= coverage_floor, or
                >= the coverage of holding the current seats with the current roles
  5 landing     each mover's TRUTH position error vs its seat at its plan end <= landing_tol_m
Defaults (fuel_reserve 0.20, landing_tol_m 50, horizon 2 orbits) are illustrative.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field

import numpy as np

from cubesat.allocate import _coverage_estimate
from cubesat.certify_sim import (
    CertificateCancelled,
    SwarmState,
    simulate,
    swarm_state_from_engine,
)
from cubesat.coverage import footprint_radius, target_grid
from cubesat.hcw import mean_motion, propagate
from cubesat.roles_v2 import ROLE_SPECS, capability, imaging_sats
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
REQUIRED_ROLES = ("leader", "downlink")  # the critical roles (roles_v2.ROLE_SPECS critical)


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
    reasons: list[str] = field(default_factory=list)
    level: str = ""
    min_sep_m: float = 0.0
    min_sep_pair: tuple[int, int] = (0, 0)
    min_sep_t_s: float = 0.0
    worst_fuel_margin_mps: float = 0.0  # 0.0 with worst_fuel_sat None when nothing is planned
    worst_fuel_sat: int | None = None
    roles_ok: bool = True
    vacant_roles: list[str] = field(default_factory=list)
    coverage: float = 0.0
    hold_coverage: float = 0.0
    landing_error_m: float = 0.0
    horizon_s: float = 0.0

    def event_payload(self) -> dict:
        """The CERTIFICATE event payload; every float finite (ValueError otherwise)."""
        out = {
            "passed": bool(self.passed),
            "level": str(self.level),
            "min_sep_m": self.min_sep_m,
            "worst_fuel_margin_mps": self.worst_fuel_margin_mps,
            "roles_ok": bool(self.roles_ok),
            "coverage": self.coverage,
            "hold_coverage": self.hold_coverage,
            "landing_error_m": self.landing_error_m,
            "reasons": [str(r) for r in self.reasons],
        }
        for k in ("min_sep_m", "worst_fuel_margin_mps", "coverage", "hold_coverage"):
            out[k] = _finite(out[k], k)
        out["landing_error_m"] = _finite(out["landing_error_m"], "landing_error_m")
        return out


def _finite(v, name: str) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number, got {v!r}") from None
    if not math.isfinite(f):
        raise ValueError(f"{name} must be finite, got {v!r}")
    return f


def _check_inputs(plan: Plan, state: SwarmState, scenario: Scenario) -> None:
    n = scenario.n_sats
    if _finite(plan.t_start_s, "plan.t_start_s") != _finite(state.t_s, "state.t_s"):
        if abs(plan.t_start_s - state.t_s) > 1e-6:
            raise ValueError(f"plan.t_start_s={plan.t_start_s} != state.t_s={state.t_s}")
    shapes = {"chief": (6,), "sat_eci": (n, 6), "refs": (n, 6)}
    for name, shape in shapes.items():
        a = np.asarray(getattr(state, name), dtype=float)
        if a.shape != shape or not np.all(np.isfinite(a)):
            raise ValueError(f"state.{name} must be a finite array of shape {shape}")
    if not (len(state.status) == len(state.sats) == len(state.roles) == n):
        raise ValueError(f"state lists must hold {n} entries (the scenario's sats)")
    for s in state.sats:
        vals = (s.m_kg, s.m_prop_kg, s.isp_s, s.f_max_n, s.k)
        if not all(math.isfinite(v) for v in vals) or s.m_kg <= 0.0 or s.isp_s <= 0.0:
            raise ValueError(f"non-finite or non-physical SatState {s}")
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
        tr = it.transfer
        if tr is not None:
            dv, ts = np.asarray(tr.dv, dtype=float), np.asarray(tr.times, dtype=float)
            if dv.ndim != 2 or dv.shape[1] != 3 or ts.shape != (dv.shape[0],) or dv.shape[0] < 1:
                raise ValueError(f"sat {it.sat_id}: transfer needs dv (N, 3) and times (N,)")
            if not (np.all(np.isfinite(dv)) and np.all(np.isfinite(ts))) or np.any(ts < 0.0):
                raise ValueError(f"sat {it.sat_id}: transfer has non-finite dv/times or t < 0")


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
    if _finite(d_safe_m, "d_safe_m") < 0.0:
        raise ValueError(f"d_safe_m must be >= 0, got {d_safe_m!r}")
    if _finite(horizon_orbits, "horizon_orbits") <= 0.0:
        raise ValueError(f"horizon_orbits must be > 0, got {horizon_orbits!r}")
    if not 0.0 <= _finite(fuel_reserve, "fuel_reserve") < 1.0:
        raise ValueError(f"fuel_reserve must be in [0, 1), got {fuel_reserve!r}")
    if _finite(landing_tol_m, "landing_tol_m") < 0.0:
        raise ValueError(f"landing_tol_m must be >= 0, got {landing_tol_m!r}")
    if coverage_floor is not None:
        _finite(coverage_floor, "coverage_floor")
    _check_inputs(plan, state, scenario)
    n = mean_motion(scenario.chief.altitude_km * 1000.0)
    items = {it.sat_id: it for it in plan.items}
    # commandable = a reporting sat (roles_v2: only those can hold the radio roles)
    cmd_ok = [capability(s, True, True, "leader") for s in state.status]
    seats_now = np.array(state.refs, dtype=float)
    movers = {i: it.transfer for i, it in items.items() if it.transfer is not None}
    for i, it in items.items():
        if cmd_ok[i]:  # a sat that cannot be commanded keeps flying its old seat
            seats_now[i] = propagate(it.seat, plan.t_start_s, n)
    steps = max(1, round(horizon_orbits * 2.0 * math.pi / n / scenario.dt_s))
    live = {i: tr for i, tr in movers.items() if cmd_ok[i]}
    res = simulate(scenario, state, seats_now, live, steps, cancel_event)
    reasons: list[str] = []

    # 1 separation
    if res.min_sep_m < d_safe_m:
        a, b = res.min_sep_pair
        reasons.append(
            f"separation: sats {a} and {b} come within {res.min_sep_m:.1f} m at t = "
            f"{res.min_sep_t_s:.0f} s, below the {d_safe_m:.1f} m limit"
        )
    worst, worst_sat = _check_fuel(movers, state, cmd_ok, fuel_reserve, reasons)
    final_roles = [
        list(items[i].roles) if i in items else list(r) for i, r in enumerate(state.roles)
    ]
    vacant, roles_ok = _check_roles(final_roles, state, scenario, reasons)
    coverage, hold_cov = _check_coverage(
        seats_now, final_roles, state, scenario, coverage_floor, reasons
    )
    landing = max(res.landing_m.values(), default=0.0)  # 5 landing
    for i, err in sorted(res.landing_m.items()):
        if err > landing_tol_m:
            reasons.append(
                f"landing: sat {i} ends {err:.1f} m from its seat in the truth model "
                f"(limit {landing_tol_m:.1f} m)"
            )

    return Certificate(
        passed=not reasons,
        reasons=reasons,
        level=plan.level,
        min_sep_m=res.min_sep_m,
        min_sep_pair=res.min_sep_pair,
        min_sep_t_s=res.min_sep_t_s,
        worst_fuel_margin_mps=worst,
        worst_fuel_sat=worst_sat,
        roles_ok=roles_ok,
        vacant_roles=vacant,
        coverage=coverage,
        hold_coverage=hold_cov,
        landing_error_m=landing,
        horizon_s=res.n_steps * scenario.dt_s,
    )


def _check_fuel(movers, state, cmd_ok, fuel_reserve, reasons):
    """Check 2. Returns (worst margin, its sat); (0.0, None) when nothing moves."""
    worst, worst_sat = math.inf, None
    for i, tr in movers.items():
        sat, planned = state.sats[i], float(np.linalg.norm(np.asarray(tr.dv), axis=1).sum())
        if not cmd_ok[i] or sat.k <= 0.0 or sat.depleted:
            why = "no radio link" if not cmd_ok[i] else "empty tank" if sat.depleted else "k = 0"
            reasons.append(f"fuel: sat {i} cannot move ({why}, status {state.status[i]})")
            margin = -planned
        else:
            margin = sat.fuel_mps_left * (1.0 - fuel_reserve) - planned
            if margin < 0.0:
                reasons.append(
                    f"fuel: sat {i} needs {planned:.3f} m/s but only {sat.fuel_mps_left:.3f} m/s "
                    f"is left with a {100.0 * fuel_reserve:.0f}% reserve (margin {margin:.3f} m/s)"
                )
        if margin < worst:
            worst, worst_sat = margin, i
    return (0.0 if worst_sat is None else worst), worst_sat


def _check_roles(final_roles, state, scenario, reasons):
    """Check 3. Returns (vacant required roles, roles_ok); capability is judged on the TRUE
    status and flags, never on what the swarm believes."""

    def can(i, role):
        s = state.sats[i]
        return capability(state.status[i], s.payload_ok, s.radio_ok, role)

    vacant = []
    for role in (r for r in REQUIRED_ROLES if r in scenario.roles):
        holders = [i for i, rs in enumerate(final_roles) if role in rs]
        if not any(can(i, role) for i in holders):
            vacant.append(role)
    bad = [(i, r) for i, rs in enumerate(final_roles) for r in rs if not can(i, r)]
    if vacant:
        reasons.append("roles: no capable sat holds " + ", ".join(vacant))
    if bad:
        held = ", ".join(f"{r} on sat {i} ({state.status[i]})" for i, r in bad)
        reasons.append("roles: incapable sats hold roles: " + held)
    return vacant, not vacant and not bad


def _check_coverage(seats_now, final_roles, state, scenario, floor, reasons):
    """Check 4, via allocate._coverage_estimate (same footprint radius, target grid and 72-sample
    average over one orbit as the allocator). Returns (plan coverage, hold coverage)."""
    n = mean_motion(scenario.chief.altitude_km * 1000.0)
    fov = math.radians(scenario.sensor.fov_half_angle_deg)
    r_f = footprint_radius(scenario.chief.altitude_km * 1000.0, fov)
    sn = scenario.sensor
    grid = target_grid(sn.grid_step_km * 1000.0, sn.grid_extent_km * 1000.0)

    def cover(seats, roles):
        img = set(imaging_sats(roles, state.status, state.sats))
        labels = ["imager" if i in img else "-" for i in range(len(roles))]
        return _coverage_estimate(list(seats), labels, r_f=r_f, grid=grid, n=n, t_replan=0.0)

    coverage, hold_cov = cover(seats_now, final_roles), cover(state.refs, state.roles)
    need = hold_cov - 1e-9 if floor is None else float(floor)
    if coverage < need:
        what = "the coverage floor" if floor is not None else "holding position"
        reasons.append(f"coverage: {coverage:.4f} is below {need:.4f} ({what})")
    return coverage, hold_cov
