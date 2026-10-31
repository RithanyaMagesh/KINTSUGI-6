"""The fuel, roles and coverage checks of the plan certificate (cubesat/certify.py), split out to
keep each file near 300 lines. Each appends plain-English reasons for what failed; nothing here
mutates its inputs."""

from __future__ import annotations

import math

import numpy as np

from cubesat.certify_sim import MAX_STEPS, burn_span, coverage_estimate
from cubesat.coverage import footprint_radius, target_grid
from cubesat.hcw import mean_motion
from cubesat.roles_v2 import ROLE_SPECS, assign_roles, capability, imaging_sats

REQUIRED_ROLES = tuple(r for r, spec in ROLE_SPECS.items() if spec["critical"])
DEAD = ("DEAD", "REENTERED")


def check_fuel_planned(movers, state, cmd_ok, fuel_reserve, dt, tail, reasons):
    """Static fuel and cannot-move checks. Returns (worst planned margin, its sat, the movers
    that may be flown); (0.0, None, {}) when nothing moves. Failing movers are not simulated.
    A mover whose burns plus the `tail` steps after them exceed MAX_STEPS cannot be flown."""
    worst, worst_sat, flyable = math.inf, None, {}
    for i, tr in movers.items():
        sat, planned = state.sats[i], float(np.linalg.norm(np.asarray(tr.dv), axis=1).sum())
        ok = cmd_ok[i] and sat.k > 0.0 and not sat.depleted
        if not ok:
            why = "no radio link" if not cmd_ok[i] else "empty tank" if sat.depleted else "k = 0"
            reasons.append(f"fuel: sat {i} cannot move ({why}, status {state.status[i]})")
            margin = -planned
        else:
            margin = sat.fuel_mps_left * (1.0 - fuel_reserve) - planned
            last = burn_span(tr, sat, dt)[2]
            if margin < 0.0:
                reasons.append(
                    f"fuel: sat {i} needs {planned:.3f} m/s but only {sat.fuel_mps_left:.3f} m/s "
                    f"is left with a {100.0 * fuel_reserve:.0f}% reserve (margin {margin:.3f} m/s)"
                )
            elif last + tail > MAX_STEPS:
                reasons.append(
                    f"fuel: sat {i}'s burns need {last} steps + {tail} after (cap {MAX_STEPS})"
                )
            else:
                flyable[i] = tr
        if margin < worst:
            worst, worst_sat = margin, i
    return (0.0 if worst_sat is None else worst), worst_sat, flyable


def check_fuel_flown(state, res, fuel_reserve, reasons):
    """Flown tank of every live sat: >= reserve * starting delta-v left, and never empty."""
    worst, worst_sat = math.inf, None
    for i, (a, b) in enumerate(zip(state.sats, res.final_sats, strict=True)):
        if state.status[i] in DEAD:
            continue
        margin = b.fuel_mps_left - fuel_reserve * a.fuel_mps_left
        if margin < 0.0:
            reasons.append(
                f"fuel: sat {i} would end with {b.fuel_mps_left:.3f} of {a.fuel_mps_left:.3f} m/s, "
                f"under the {100.0 * fuel_reserve:.0f}% reserve (margin {margin:.3f} m/s)"
            )
        if a.m_prop_kg > 0.0 and b.m_prop_kg <= 0.0:
            reasons.append(f"fuel: sat {i} runs out of propellant during the horizon")
        if margin < worst:
            worst, worst_sat = margin, i
    return worst, worst_sat


def check_roles(final_roles, state, scenario, reasons):
    """Roles check; capability is judged on the TRUE status and flags, never on belief."""

    def can(i, role):
        s = state.sats[i]
        return capability(state.status[i], s.payload_ok, s.radio_ok, role)

    vacant, found = [], []
    for role in (r for r in REQUIRED_ROLES if r in scenario.roles):
        holders = [i for i, rs in enumerate(final_roles) if role in rs]
        if not any(can(i, role) for i in holders):
            vacant.append(role)
        if len(holders) > 1:
            found.append(f"{role} held by sats {holders}")
    bad = [(i, r) for i, rs in enumerate(final_roles) for r in rs if not can(i, r)]
    # stacking and seat counts: the plan must be what the engine's own rule (roles_v2.assign_roles,
    # truth statuses, the plan's roles as incumbents) would keep; "spare" is only a label
    view = [
        {"status": st, "payload_ok": s.payload_ok, "radio_ok": s.radio_ok, "roles": rs}
        for st, s, rs in zip(state.status, state.sats, final_roles, strict=True)
    ]
    priority = [r for r in scenario.role_priority if r in scenario.roles]
    kept = assign_roles(view, priority, scenario.roles.count("imager"))
    for i, (want, got) in enumerate(zip(kept, final_roles, strict=True)):
        if set(want) - {"spare"} != set(got) - {"spare"}:
            found.append(f"the engine's role rule gives sat {i} {sorted(want)}, not {sorted(got)}")
    if vacant:
        reasons.append("roles: no capable sat holds " + ", ".join(vacant))
    if bad:
        held = ", ".join(f"{r} on sat {i} ({state.status[i]})" for i, r in bad)
        reasons.append("roles: incapable sats hold roles: " + held)
    reasons.extend(f"roles: {f}" for f in found)
    return vacant, not (vacant or bad or found)


def check_coverage(seats_now, final_roles, state, scenario, floor, unreached, reasons):
    """Coverage check via the allocator's convention (footprint radius, target grid, 72-sample
    orbit average). `unreached` sats do not image, on BOTH sides (like for like: an empty plan
    never fails against itself). Returns (plan coverage, hold coverage)."""
    n = mean_motion(scenario.chief.altitude_km * 1000.0)
    sn = scenario.sensor
    alt = scenario.chief.altitude_km * 1000.0
    r_f = footprint_radius(alt, math.radians(sn.fov_half_angle_deg))
    grid = target_grid(sn.grid_step_km * 1000.0, sn.grid_extent_km * 1000.0)

    def cover(seats, roles, skip=()):
        img = [i for i in imaging_sats(roles, state.status, state.sats) if i not in skip]
        return coverage_estimate(list(seats), img, r_f=r_f, grid=grid, n=n)

    coverage = cover(seats_now, final_roles, unreached)
    hold_cov = cover(state.refs, state.roles, unreached)
    need = hold_cov - 1e-9 if floor is None else float(floor)
    if coverage < need:
        what = "the coverage floor" if floor is not None else "holding position"
        reasons.append(f"coverage: {coverage:.4f} is below {need:.4f} ({what})")
    return coverage, hold_cov
