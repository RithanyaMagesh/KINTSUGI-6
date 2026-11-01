"""Recovery ladder L0-L5 for engine v2 (master map R1; replan kit §2.5). Pure: no RNG, no clock.

On a declared failure `run_ladder` builds plans level by level, certifies each with
cubesat/certify.py from the engine's TRUE state, and returns the plan to execute:
  L0 hold/wait     NOT BUILT: there is no SUSPECT state (Phase 4 unbuilt); the K-tick heartbeat
                   confirm already is the wait, so L0 is always rejected with that reason.
  L1 role swap     0 delta-v: every sat keeps its seat, roles = roles_v2.assign_roles on the
                   truth statuses (incumbents kept), certified as a hold plan.
  L2 local re-seat only the imagers move, onto the scenario's own ring at cross-track phase psi,
                   psi swept ascending (PSI_SWEEP); the smallest psi that certifies wins.
  L3 re-formation  every sat that can thrust moves onto a k-seat ring (amp_sweep x
                   phase_sweep_deg x PSI_SWEEP, psi ascending, the best pre-filtered candidate
                   per psi certified), plus MOVE-TO-THE-CRIPPLE: when a live sat cannot thrust
                   (THRUSTER_OUT / FUEL_DEPLETED / k = 0) it keeps its seat and the others form
                   the ring through it; both are certified and the better coverage (ties: less
                   delta-v) is taken; both delta-v are reported.
  L4 degraded      hold plan certified with the vacant critical roles SHED (lowest priority
                   first) and no coverage floor: the best certified reduced mission.
  L5 retire        NOT BUILT (graceful de-orbit burn + FCC 5-year decay report): rejected.
A move (L2/L3) replaces L1 only if certified AND its coverage beats L1's like for like
(certificate coverage > max(L1 coverage, the move's own hold baseline, which uses the same
exclusions) + COVER_EPS). When L1 itself fails, the first certified move is taken, certified
against the coverage floor (0 when none) instead of the unsafe hold's coverage.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from cubesat import ladder_moves as mv
from cubesat import truth
from cubesat.certify import Certificate, Plan, PlanItem, SwarmState, certify
from cubesat.certify_checks import DEAD, REQUIRED_ROLES, commandable
from cubesat.certify_checks import passive as is_passive
from cubesat.coverage import footprint_radius, target_grid
from cubesat.hcw import mean_motion, propagate
from cubesat.roles_v2 import assign_roles, capability, imaging_sats
from cubesat.scenario import Scenario

PSI_SWEEP = (0.0, 30.0, 45.0, 60.0, 90.0)  # deg; separation is non-monotone in psi: swept
COVER_EPS = 1e-4  # "better" = above the pre-registered PR-1 tie tolerance (GATES.md)
LANDING_TOL_M = 50.0  # = certify default (illustrative)


@dataclass
class Decision:
    level: str | None  # executed level; None = nothing certified (hold, flagged)
    plan: Plan | None
    cert: Certificate | None
    reason: str
    rejected: list[dict] = field(default_factory=list)  # [{level, why}]
    shed: list[str] = field(default_factory=list)
    dv_mps: float = 0.0  # planned L2 delta-v of the executed plan, all movers
    cripple: dict | None = None  # {sat_id, dv_with_mps, dv_abandon_mps} when a cripple exists

    def payload(self) -> dict:
        out = {"level": self.level, "reason": self.reason, "rejected": self.rejected}
        out.update(shed_roles=self.shed, dv_planned_mps=self.dv_mps)
        if self.cripple is not None:
            out["cripple"] = self.cripple
        return out


@dataclass
class _Ctx:
    scenario: Scenario
    n: float
    dt: float
    r_f: float
    grid: np.ndarray
    d_safe: float
    floor: float | None
    landing_tol_m: float
    cancel: object


def _ctx(scenario, cancel) -> _Ctx:
    alt = scenario.chief.altitude_km * 1000.0
    sn = scenario.sensor
    rec = scenario.recovery
    return _Ctx(
        scenario, mean_motion(alt), scenario.dt_s,
        footprint_radius(alt, math.radians(sn.fov_half_angle_deg)),
        target_grid(sn.grid_step_km * 1000.0, sn.grid_extent_km * 1000.0),
        scenario.allocation.min_sep_km * 1000.0, rec.coverage_floor if rec else None,
        LANDING_TOL_M, cancel,
    )


def _dv(plan: Plan) -> float:
    return float(sum(it.transfer.l2_dv_mps for it in plan.items if it.transfer is not None))


def run_ladder(
    state: SwarmState, scenario: Scenario, cancel_event=None, inflight=None, believed=None
) -> Decision:
    """The plan to execute now (see module doc). `inflight` {sat: Transfer}: the remaining burns
    of the plan being flown; L1 and the sats a move leaves alone keep flying them (a replan
    mid-transfer must not turn the hold into a PD chase from mid-flight). `believed`
    [[status, payload_ok, radio_ok]] per sat: the swarm's view the roles are assigned from
    (the engine's own rule; default the truth); the certificate still judges the truth.
    CertificateCancelled / TransferCancelled propagate when cancel_event is set."""
    inflight = inflight or {}
    ctx = _ctx(scenario, cancel_event)
    n, t = ctx.n, state.t_s
    c = state.chief
    lvlh = truth.eci_to_lvlh(state.sat_eci[:, :3], state.sat_eci[:, 3:], c[:3], c[3:])
    live = [i for i, s in enumerate(state.status) if s not in DEAD]
    declared = state.declared or [False] * len(state.sats)
    cmd_ok = [commandable(s, d) for s, d in zip(state.status, declared, strict=True)]
    passive = [i for i in live if is_passive(state.sats[i])]
    firing = [i for i in live if state.sats[i].stuck_vec is not None and i not in passive]
    active = [i for i in live if i not in passive and i not in firing and cmd_ok[i]]
    inflight = {i: tr for i, tr in inflight.items() if i in active}  # a dead mover stops
    priority = [r for r in scenario.role_priority if r in scenario.roles]
    seen = believed or [[st, s.payload_ok, s.radio_ok] for st, s in zip(state.status, state.sats,
                                                                         strict=True)]
    view = [{"status": b[0], "payload_ok": b[1], "radio_ok": b[2], "roles": r}
            for b, r in zip(seen, state.roles, strict=True)]
    roles = assign_roles(view, priority, scenario.roles.count("imager"))
    seat0 = [propagate(state.refs[i], -t, n) for i in range(len(state.sats))]

    def plan_of(level, targets, trs):
        items = []
        for i in range(len(state.sats)):
            if i in targets:
                items.append(PlanItem(i, trs.get(i), targets[i], tuple(roles[i])))
            elif i in inflight:
                items.append(PlanItem(i, inflight[i], seat0[i], tuple(roles[i])))
            elif list(roles[i]) != list(state.roles[i]):
                items.append(PlanItem(i, None, seat0[i], tuple(roles[i])))
        return Plan(tuple(items), level, t)

    def cert(plan, floor=ctx.floor, shed=()):
        return certify(plan, state, scenario, d_safe_m=ctx.d_safe, coverage_floor=floor,
                       cancel_event=cancel_event, shed_roles=tuple(shed))

    rejected = [{"level": "L0", "why": "not built: no SUSPECT state; the K-tick heartbeat "
                 "confirm is the wait"}]
    p1 = plan_of("L1", {}, {})
    c1 = cert(p1)
    if c1.passed:
        base = c1.coverage
    else:
        base = None
        rejected.append({"level": "L1", "why": "; ".join(c1.reasons)})
    obstacles = [lvlh[i] for i in range(len(state.sats)) if state.status[i] == "DEAD"]
    obstacles += [lvlh[i] for i in passive + firing]  # coasting or firing uncommanded

    def better(cc):
        return base is None or cc.coverage > max(base, cc.hold_coverage) + COVER_EPS

    def attempt(level, targets, stay):
        """(plan, cert) or a reason string."""
        now = [propagate(s, t, n) for s in targets.values()]
        if not mv.clear(now + [state.refs[i] for i in stay], obstacles, n, ctx.d_safe):
            return "seats closer than d_safe (CW, one orbit)"
        seats_all = np.array(state.refs, dtype=float)
        for i, s in targets.items():
            seats_all[i] = propagate(s, t, n)
        est = mv.estimate(seats_all, imaging_sats(roles, state.status, state.sats), ctx)
        if base is not None and est <= base + COVER_EPS:
            return f"coverage estimate {est:.4f} not above L1 {base:.4f}"
        trs = mv.transfers(ctx, state, lvlh, targets, obstacles, ctx.d_safe, cancel_event)
        if isinstance(trs, str):
            return trs
        if not trs:
            return "no seat change"
        plan = plan_of(level, targets, trs)
        # L1 failed (the hold is unsafe): a safe move may cost coverage, down to the floor
        cc = cert(plan) if base is not None else cert(plan, floor=ctx.floor or 0.0)
        if not cc.passed:
            return "certificate: " + "; ".join(cc.reasons)
        if not better(cc):
            return f"certified, coverage {cc.coverage:.4f} not above L1 {base:.4f}"
        return plan, cc

    # L2: imagers only, onto the scenario's own ring at psi
    movers2 = [i for i in active if "imager" in roles[i]]
    stay2 = [i for i in live if i not in movers2]
    fm = scenario.formation
    amp, ph0 = fm.radial_amp_km * 1000.0, math.radians(fm.phase_offset_deg)
    chosen = None
    for psi in PSI_SWEEP if movers2 else ():
        pool = mv.ring(amp, ph0, math.radians(psi), fm.n_slots, n)
        pool = [s for s in pool if mv.clear([propagate(s, t, n)], obstacles
                + [state.refs[i] for i in stay2], n, ctx.d_safe)]
        if len(pool) < len(movers2):
            rejected.append({"level": "L2", "why": f"psi {psi:g}: fewer clear seats than imagers"})
            continue
        asg, _ = mv.assign(lvlh, movers2, [propagate(s, t, n) for s in pool])
        out = attempt("L2", {i: pool[j] for i, j in asg.items()}, stay2)
        if isinstance(out, str):
            rejected.append({"level": "L2", "why": f"psi {psi:g}: {out}"})
            continue
        chosen = ("L2", *out)
        break
    cripple = None
    if not active:
        rejected.append({"level": "L2", "why": "no sat can thrust and be commanded"})
        rejected.append({"level": "L3", "why": "no sat can thrust and be commanded"})
    if chosen is None and active:
        chosen, cripple = _level3(ctx, state, lvlh, active, passive, live, attempt, rejected)
    if chosen is not None:
        level, plan, cc = chosen
        why = "certified move, coverage above L1" if base is not None else "L1 failed; certified"
        return Decision(level, plan, cc, why, rejected, [], _dv(plan), cripple)
    if c1.passed:
        return Decision("L1", p1, c1, "role swap certified; no move beats it", rejected,
                        [], 0.0, cripple)
    vacant = [r for r in reversed(priority) if r in REQUIRED_ROLES and not any(
        r in roles[i] and capability(state.status[i], state.sats[i].payload_ok,
                                     state.sats[i].radio_ok, r) for i in live)]
    p4 = plan_of("L4", {}, {})
    c4 = cert(p4, floor=0.0, shed=vacant)
    if c4.passed:
        return Decision("L4", p4, c4, "degraded mission: " + (
            f"shed {', '.join(vacant)}" if vacant else "coverage floor dropped"),
            rejected, vacant, 0.0, cripple)
    rejected.append({"level": "L4", "why": "; ".join(c4.reasons)})
    rejected.append({"level": "L5", "why": "not built: graceful retirement burn"})
    return Decision(None, None, c4, "no certified plan: hold and flag", rejected, vacant,
                    0.0, cripple)


def _level3(ctx, state, lvlh, active, passive, live, attempt, rejected):
    """((level, plan, cert) or None, cripple report). Abandon: psi ascending, the best
    pre-filtered ring per psi (coverage estimate desc, then distance). Cripple: the ring
    through the lowest-id passive sat."""
    n, t, al = ctx.n, state.t_s, ctx.scenario.allocation
    stay = [i for i in live if i not in active]
    amp0 = ctx.scenario.formation.radial_amp_km * 1000.0
    found = None
    for psi in PSI_SWEEP:
        cands = []
        for a in al.amp_sweep:
            for ph in al.phase_sweep_deg:
                pool = mv.ring(a * amp0, math.radians(ph), math.radians(psi), len(active), n)
                asg, dist = mv.assign(lvlh, active, [propagate(s, t, n) for s in pool])
                cands.append((dist, len(cands), {i: pool[j] for i, j in asg.items()}))
        cands.sort(key=lambda c: (c[0], c[1]))  # same coverage on a symmetric ring: distance
        out = "no candidate"
        for _, _, targets in cands:
            out = attempt("L3", targets, stay)
            if not isinstance(out, str) or not out.startswith("seats closer"):
                break
        if isinstance(out, str):
            rejected.append({"level": "L3", "why": f"psi {psi:g}: {out}"})
            continue
        found = ("L3", *out)
        break
    if not passive:
        return found, None
    c = passive[0]
    ring = mv.ring_through(propagate(state.refs[c], -t, n), len(active) + 1, n)[1:]
    asg, _ = mv.assign(lvlh, active, [propagate(s, t, n) for s in ring])
    out = attempt("L3", {i: ring[j] for i, j in asg.items()}, stay)
    report = {"sat_id": c, "dv_with_mps": None if isinstance(out, str) else _dv(out[0]),
              "dv_abandon_mps": None if found is None else _dv(found[1])}
    if isinstance(out, str):
        rejected.append({"level": "L3", "why": f"move to the cripple (sat {c}): {out}"})
        return found, report
    if found is None or out[1].coverage > found[2].coverage + COVER_EPS or (
        abs(out[1].coverage - found[2].coverage) <= COVER_EPS and _dv(out[0]) < _dv(found[1])
    ):
        if found is not None:
            rejected.append({"level": "L3", "why": "abandoning the cripple: certified but worse"})
        return ("L3", *out), report
    rejected.append({"level": "L3", "why": f"move to the cripple (sat {c}): certified but worse"})
    return found, report
