"""Swarm simulation and versioned JSONL line model (gates G3/G4).

Pure core (MASTER_PROMPT 3.5): fixed-dt steps, no wall clock, no RNG, no
order-dependent iteration (AGENTS.md invariant 2); SI units, LVLH frame
(AGENTS.md invariants 3-4). cubesat.run is the I/O edge that writes these lines
as JSONL; two runs of one scenario + seed are byte-identical.

Log schema, one line per tick (MASTER_PROMPT section 5; v = LOG_SCHEMA_VERSION):

    {"v": 1, "t": <sim s>, "state": <str>,
     "sats": [{"id": int, "role": str, "status": str,
               "r": [x, y, z] m, "v": [vx, vy, vz] m/s, "dv_used": m/s}],
     "coverage": <fraction 0..1>, "min_sep": <m>,
     "event": {"type": <str>, "payload": <object>}}   # optional; omitted when None

The run opens with one metadata line (state INIT: v, t, scenario, seed, n_sats --
the G0 header, kept for replay) and closes with one SUMMARY line carrying the
time-averaged coverage over the last orbit (MASTER_PROMPT 3.4).

Swarm state machine (MASTER_PROMPT 3.5), logged per tick in `state`:
    NOMINAL -> FAILURE_DETECTED -> REPLANNING -> RECONFIGURING -> RECOVERED
A newly detected failure re-enters FAILURE_DETECTED from any state; with
recovery_enabled = False the machine stops at FAILURE_DETECTED (no-recovery
baseline). Events (type + payload, FIFO, at most one per tick line):
    FAILURE_DETECTED: {sat_id, mode, t_fail, t_detect, self_report?}
                      (self_report: true marks a failure the sat announced
                      itself -- a THRUSTER_OUT reports its own death on the
                      firing tick, so no heartbeat misses are needed and
                      t_detect == t_fail for tick-aligned failure times, as
                      in every committed scenario and live injection; a
                      mid-tick failure reports the enclosing tick)
    DEGRADE_START:    {sat_id, t_fail, degrade_s}  (EPS_DEGRADE fade onset)
    STATE:            {from, to}                    (plain transitions)
    ASSIGNMENT:       {assignments: [{sat_id, slot_index, role}], method,
                       cost_total, formation: {radial_amp_m, phase_offset_rad},
                       transfer_lower_bound_s}
    EVASIVE_MANEUVER: {sat_id, other_id, range_m, t}  (Addendum v1.2: a sat came
                       inside safety.evade_radius_m of another and started a
                       bounded away-from-intruder burn; default radius is below
                       every measured clearance, so canonical runs never emit it)
The replanner (cubesat.allocate.replan) runs BETWEEN sim steps -- one control
cycle per machine transition -- never inside the step loop below it. Every sat
emits a heartbeat each tick; a sat that stops reporting is declared DEAD after
missed_ticks_k misses. DEAD sats (and THRUSTER_OUT sats) coast ballistically --
never frozen -- and stay in the min_sep pairwise loop as collision hazards.

Failure modes (Addendum v1.2): EPS_DEGRADE with degrade_s > 0 puts the sat in
STATUS_DEGRADED from max(t_fail - degrade_s, 0) -- it keeps reporting, keeps
PD-holding its assigned seat, and still counts for coverage and the settle
check, but is excluded from replan assignable (status != NOMINAL). At t_fail it
becomes DEAD exactly like DEAD mode. degrade_s == 0 is sudden: the run matches
the same failure declared DEAD byte for byte except the FAILURE_DETECTED payload's
mode label, which honestly stays EPS_DEGRADE (one field, pinned by
test_eps_degrade_zero_window_equals_dead); a delayed DEGRADE_START event (the
FIFO pops at most one event per tick) is fine and documented.
"""

from __future__ import annotations

import math

import numpy as np

from cubesat.allocate import replan
from cubesat.coverage import coverage_fraction, footprint_radius, target_grid
from cubesat.hcw import mean_motion, propagate, slot_initial_state
from cubesat.pd import PDController, bang_bang_time_lower_bound
from cubesat.scenario import FailureMode, Scenario

LOG_SCHEMA_VERSION = 1
STATE_INIT = "INIT"
STATE_NOMINAL = "NOMINAL"
STATE_FAILURE_DETECTED = "FAILURE_DETECTED"
STATE_REPLANNING = "REPLANNING"
STATE_RECONFIGURING = "RECONFIGURING"
STATE_RECOVERED = "RECOVERED"
STATE_SUMMARY = "SUMMARY"
STATUS_NOMINAL = "NOMINAL"
STATUS_DEGRADED = "DEGRADED"
STATUS_DEAD = "DEAD"
STATUS_THRUSTER_OUT = "THRUSTER_OUT"

# Recovery tolerance: fraction of the largest assigned transfer distance.
_RECOVER_TOL_FRAC = 0.05


def build_slots(scenario: Scenario, n: float) -> list[np.ndarray]:
    """Slot initial states, sat i on slot i: phase = phase_offset_deg + 360*j/n_slots.
    The schema has no cross-track amplitude, so it equals radial_amp_km (planar
    relative orbit, z in phase with x); that spreads the ground (y, z) centers
    around a ring instead of pairing them on top of each other."""
    amp = scenario.formation.radial_amp_km * 1000.0
    offset = math.radians(scenario.formation.phase_offset_deg)
    return [
        slot_initial_state(
            amp, amp, offset + 2.0 * math.pi * j / scenario.formation.n_slots, n
        )
        for j in range(scenario.formation.n_slots)
    ]


def run_scenario(scenario: Scenario) -> list[dict]:
    """Simulate the mission and return the JSONL lines: [INIT header, tick..., SUMMARY]."""
    altitude_m = scenario.chief.altitude_km * 1000.0
    n = mean_motion(altitude_m)
    dt = scenario.dt_s
    n_sats = scenario.n_sats
    slots = build_slots(scenario, n)
    states = [slot.copy() for slot in slots]
    controllers = [
        PDController(scenario.gains.wn, scenario.gains.zeta, scenario.a_max_mps2)
        for _ in scenario.roles
    ]
    r_f = footprint_radius(altitude_m, math.radians(scenario.sensor.fov_half_angle_deg))
    grid = target_grid(
        scenario.sensor.grid_step_km * 1000.0, scenario.sensor.grid_extent_km * 1000.0
    )

    # Mission bookkeeping. With no failures every default keeps this path
    # byte-identical to the G3 nominal log (golden-hash regression guard).
    formation = list(slots)  # current formation seat states (t = 0 convention)
    seat_of = list(range(n_sats))  # sat i -> seat index in `formation`
    roles = list(scenario.roles)
    status = [STATUS_NOMINAL] * n_sats
    missed = [0] * n_sats  # consecutive missed heartbeat ticks
    t_fail = [0.0] * n_sats
    fail_mode = [""] * n_sats
    declared = [False] * n_sats
    failures = sorted(scenario.failures, key=lambda f: (f.t, f.sat_id))
    next_failure = 0
    # EPS_DEGRADE fade transitions, scheduled at max(t_fail - degrade_s, 0) --
    # the failure fires early as a DEGRADED status flip, in (fade time, sat_id)
    # order. Only degrade_s > 0 enters this schedule, which is what keeps
    # sudden failures (and every existing scenario) byte-identical.
    degrades = sorted(
        (
            f
            for f in scenario.failures
            if f.mode == FailureMode.EPS_DEGRADE and f.degrade_s > 0
        ),
        key=lambda f: (max(f.t - f.degrade_s, 0.0), f.sat_id),
    )
    next_degrade = 0
    mission = STATE_NOMINAL
    events: list[dict] = []  # FIFO; at most one popped per tick line
    replan_due = False
    assigned = False
    recover_tol = 0.0
    oracle_warned = [False] * len(scenario.failures)
    # Evasion episodes (Addendum v1.2): per-sat countdown and held acceleration.
    # All-zero init keeps the default path byte-identical (see the evasion block).
    evade_ticks_left = [0] * n_sats
    u_evade = [np.zeros(3) for _ in range(n_sats)]

    n_ticks = int(round(scenario.duration_s / dt)) + 1
    lines = [
        {
            "v": LOG_SCHEMA_VERSION,
            "t": 0.0,
            "state": STATE_INIT,
            "scenario": scenario.name,
            "seed": scenario.seed,
            "n_sats": scenario.n_sats,
        }
    ]
    coverage_by_tick: list[tuple[float, float]] = []
    for k in range(n_ticks):
        t = k * dt
        # EPS_DEGRADE fades fire (before this tick's heartbeat), in scheduled
        # order: the sat turns DEGRADED (still reporting, still seat-holding)
        # and announces the upcoming death with one DEGRADE_START event. Only
        # reaches a sat that is still NOMINAL -- a sat that already failed in
        # another mode keeps that mode's semantics.
        while next_degrade < len(degrades):
            failure = degrades[next_degrade]
            if max(failure.t - failure.degrade_s, 0.0) > t + 1e-9:
                break
            next_degrade += 1
            i = failure.sat_id
            if status[i] == STATUS_NOMINAL:
                status[i] = STATUS_DEGRADED
                events.append(
                    {
                        "type": "DEGRADE_START",
                        "payload": {
                            "sat_id": i,
                            "t_fail": failure.t,
                            "degrade_s": failure.degrade_s,
                        },
                    }
                )
        # Failures fire (before this tick's heartbeat), in scheduled order.
        while next_failure < len(failures) and failures[next_failure].t <= t + 1e-9:
            failure = failures[next_failure]
            next_failure += 1
            i = failure.sat_id
            if status[i] != STATUS_DEAD:
                status[i] = (
                    STATUS_THRUSTER_OUT
                    if failure.mode == FailureMode.THRUSTER_OUT
                    else STATUS_DEAD
                )
                t_fail[i] = failure.t
                fail_mode[i] = str(failure.mode.value)
                if failure.mode == FailureMode.THRUSTER_OUT:
                    # Self-reported failure (Addendum v1.2): the sat announces
                    # its own dead thruster, so detection needs no heartbeat
                    # misses and fires on this tick (t_detect = t, equal to
                    # t_fail for tick-aligned failure times -- every committed
                    # scenario and live injection) and the machine enters
                    # FAILURE_DETECTED immediately -- the standard REPLANNING
                    # -> re-election -> RECONFIGURING -> RECOVERED arc then
                    # runs unchanged (non-NOMINAL sats are already excluded
                    # from assignable and seat_roles_for re-elects the role).
                    mission = STATE_FAILURE_DETECTED
                    events.append(
                        {
                            "type": "FAILURE_DETECTED",
                            "payload": {
                                "sat_id": i,
                                "mode": fail_mode[i],
                                "t_fail": failure.t,
                                "t_detect": t,
                                "self_report": True,
                            },
                        }
                    )
        # Heartbeats: only DEAD sats stay silent; everyone else reports each tick.
        for i in range(n_sats):
            if status[i] == STATUS_DEAD:
                missed[i] += 1
            else:
                missed[i] = 0
        # Detection: declare after K consecutive missed heartbeats.
        for i in range(n_sats):
            if (
                status[i] == STATUS_DEAD
                and not declared[i]
                and missed[i] >= scenario.detection.missed_ticks_k
            ):
                declared[i] = True
                mission = STATE_FAILURE_DETECTED
                events.append(
                    {
                        "type": "FAILURE_DETECTED",
                        "payload": {
                            "sat_id": i,
                            "mode": fail_mode[i],
                            "t_fail": t_fail[i],
                            "t_detect": t,
                        },
                    }
                )

        # Coverage follows the CURRENT role assignment: re-election after a replan
        # reassigns roles[] (imagers can move to other sats), so the imager set is
        # evaluated per tick. With no replanning roles == scenario.roles, which
        # keeps the no-failure path byte-identical to the G3 nominal log.
        centers = np.array(
            [
                states[i][1:3]
                for i in range(n_sats)
                if roles[i] == "imager" and status[i] != STATUS_DEAD
            ]
        )
        coverage = coverage_fraction(centers, grid, r_f)
        positions = np.array([state[:3] for state in states])
        min_sep = min(
            float(np.linalg.norm(positions[i] - positions[j]))
            for i in range(n_sats)
            for j in range(i + 1, n_sats)
        )
        line = {
            "v": LOG_SCHEMA_VERSION,
            "t": t,
            "state": mission,
            "sats": [
                {
                    "id": i,
                    "role": roles[i],
                    "status": status[i],
                    "r": states[i][:3].tolist(),
                    "v": states[i][3:].tolist(),
                    "dv_used": controllers[i].dv_used,
                }
                for i in range(n_sats)
            ],
            "coverage": coverage,
            "min_sep": min_sep,
        }
        if events:
            line["event"] = events.pop(0)
        lines.append(line)
        coverage_by_tick.append((t, coverage))
        if k == n_ticks - 1:
            break

        # Between-step orchestration (MASTER_PROMPT 3.5): the replanner runs here,
        # between sim steps, one control cycle per machine transition. The decision
        # states FAILURE_DETECTED and REPLANNING therefore each last exactly one
        # tick in the log; RECONFIGURING spans the physical transfers until every
        # Oracle value-of-warning hook (Phase 2): gated default-off; inert when disabled
        if (
            scenario.oracle.enabled
            and scenario.recovery_enabled
            and scenario.oracle.lead_s > 0
            and not replan_due
            and mission in (STATE_NOMINAL, STATE_RECOVERED)
        ):
            lead = scenario.oracle.lead_s
            for f_idx, f in enumerate(failures):
                if not oracle_warned[f_idx] and t < f.t:
                    t_warn = max(f.t - lead, 0.0)
                    if t_warn <= t:
                        oracle_warned[f_idx] = True
                        mission = STATE_REPLANNING
                        replan_due = True
                        events.append(
                            {
                                "type": "ORACLE_ALERT",
                                "payload": {
                                    "sat_id": f.sat_id,
                                    "lead_s": lead,
                                    "t_fail": f.t,
                                    "t_warn": t,
                                },
                            }
                        )
                        break

        # Between-step orchestration (MASTER_PROMPT 3.5): the replanner runs here,
        # between sim steps, one control cycle per machine transition. The decision
        # states FAILURE_DETECTED and REPLANNING therefore each last exactly one
        # tick in the log; RECONFIGURING spans the physical transfers until every
        # survivor settles within tolerance, and RECOVERED holds to the end.
        if (
            mission == STATE_FAILURE_DETECTED
            and scenario.recovery_enabled
            and any(s == STATUS_NOMINAL for s in status)
        ):
            mission = STATE_REPLANNING
            events.append(
                {
                    "type": "STATE",
                    "payload": {"from": STATE_FAILURE_DETECTED, "to": STATE_REPLANNING},
                }
            )
            replan_due = True
        elif replan_due and mission == STATE_REPLANNING:
            assignable = [i for i in range(n_sats) if status[i] == STATUS_NOMINAL]
            obstacles = [states[i] for i in range(n_sats) if status[i] != STATUS_NOMINAL]
            plan, pairs, cost_total, method, max_transfer, _cost = replan(
                [states[i] for i in assignable],
                [roles[i] for i in assignable],
                [
                    max(scenario.allocation.dv_budget_mps - controllers[i].dv_used, 1e-9)
                    for i in assignable
                ],
                obstacles,
                scenario.roles,
                scenario.allocation,
                scenario.formation.radial_amp_km * 1000.0,
                r_f,
                grid,
                n,
                scenario.a_max_mps2,
                t,
            )
            # DEGRADED sats are excluded from assignable (status != NOMINAL) but
            # keep PD-holding their assigned seat (Addendum v1.2, module
            # docstring) -- so when a replan shrinks the formation to the
            # survivors' k seats, each DEGRADED sat keeps its pre-replan seat:
            # its formation entry is appended after plan.slots (ascending sat
            # id, deterministic) and seat_of is re-pointed. Without this the
            # stale seat index either crashes the step loop (index >= k, first
            # hit by the v2 oracle sweep on eps_downlink_6sat) or silently
            # double-books a survivor's seat (eps_leader_6sat, seat 0).
            # Reached only when a replan fires while a sat is DEGRADED: via the
            # oracle hook, or reactively when a DEAD sat's missed-heartbeat
            # detection fires while another sat is mid-fade (mixed failures --
            # the DEGRADED sat then lands in `preserved` below). No committed
            # scenario does either (the EPS_DEGRADE ones are single-failure
            # with the oracle off), so this block never fires on a canonical
            # run and the golden pins stay byte-identical.
            preserved: list[np.ndarray] = []
            for i in range(n_sats):
                if status[i] == STATUS_DEGRADED:
                    preserved.append(formation[seat_of[i]])
                    seat_of[i] = len(plan.slots) + len(preserved) - 1
            formation = list(plan.slots) + preserved
            for row, col in pairs:
                sat_id = assignable[row]
                seat_of[sat_id] = col
                roles[sat_id] = plan.seat_roles[col]
            if scenario.oracle.enabled and scenario.oracle.lead_s > 0:
                lead = scenario.oracle.lead_s
                failing_soon = {
                    f.sat_id
                    for f in scenario.failures
                    if t <= f.t <= t + lead + 1e-9
                }
                for crit_role in ("leader", "downlink"):
                    holders = [s for s in assignable if roles[s] == crit_role]
                    if not holders:
                        continue
                    holder = holders[0]
                    if holder in failing_soon:
                        candidates = [
                            s
                            for s in assignable
                            if s not in failing_soon
                            and roles[s] not in ("leader", "downlink")
                        ]
                        if candidates:
                            target = min(candidates)
                            h_seat, t_seat = seat_of[holder], seat_of[target]
                            seat_of[holder], seat_of[target] = t_seat, h_seat
                            roles[holder], roles[target] = roles[target], roles[holder]
                            events.append(
                                {
                                    "type": "ORACLE_SWAP",
                                    "payload": {
                                        "role": crit_role,
                                        "from_sat": holder,
                                        "to_sat": target,
                                        "t": t,
                                    },
                                }
                            )
            recover_tol = max(_RECOVER_TOL_FRAC * max_transfer, 1.0)
            assigned = True
            replan_due = False
            mission = STATE_RECONFIGURING
            events.append(
                {
                    "type": "ASSIGNMENT",
                    "payload": {
                        "assignments": [
                            {
                                "sat_id": assignable[r],
                                "slot_index": seat_of[assignable[r]],
                                "role": roles[assignable[r]],
                            }
                            for r, _ in sorted(pairs)
                        ],
                        "method": method,
                        "cost_total": cost_total,
                        "formation": {
                            "radial_amp_m": plan.radial_amp_m,
                            "phase_offset_rad": plan.phase0_rad,
                        },
                        # Research patch #1: log the bang-bang lower bound per
                        # reconfig, t >= 2*sqrt(d/a_max) for the largest transfer.
                        "transfer_lower_bound_s": bang_bang_time_lower_bound(
                            max_transfer, scenario.a_max_mps2
                        ),
                    },
                }
            )
        elif assigned and mission == STATE_RECONFIGURING:
            settled = all(
                float(
                    np.linalg.norm(states[i][:3] - propagate(formation[seat_of[i]], t, n)[:3])
                )
                <= recover_tol
                for i in range(n_sats)
                if status[i] in (STATUS_NOMINAL, STATUS_DEGRADED)
            )
            if settled:
                mission = STATE_RECOVERED
                events.append(
                    {
                        "type": "STATE",
                        "payload": {"from": STATE_RECONFIGURING, "to": STATE_RECOVERED},
                    }
                )

        # Evasive collision avoidance (Addendum v1.2): a discrete bounded evasion
        # maneuver, explicitly NOT potential fields (MASTER_PROMPT 2 lock is
        # preserved; min_sep above stays logged every tick). AFTER the
        # replan/settle block, BEFORE stepping: an evasive-capable sat (NOMINAL
        # or DEGRADED -- THRUSTER_OUT cannot thrust, DEAD does not report) with
        # no active episode starts one when its nearest other sat (ANY status --
        # dead sats coast and stay hazards) is inside the evade radius. The burn
        # points straight away from the intruder at a_max for evade_ticks ticks;
        # a sat still inside the radius when its counter expires starts a new
        # episode (continuous burn until clear -- deterministic, index-ordered
        # scan with a strict < so ties resolve to the lowest id). Evasion changes
        # NO mission state -- only physics, dv_used, and events (FIFO, one pops
        # per tick line). Default-inertness is geometric: no committed scenario
        # comes within the 1000 m default radius, so this block appends nothing
        # and the runs stay byte-identical.
        if scenario.safety.evasion_enabled:
            for i in range(n_sats):
                if (
                    status[i] not in (STATUS_NOMINAL, STATUS_DEGRADED)
                    or evade_ticks_left[i] > 0
                ):
                    continue
                best_j = -1
                best_range = scenario.safety.evade_radius_m
                best_d = None
                for j in range(n_sats):
                    if j == i:
                        continue
                    d_ij = states[i][:3] - states[j][:3]
                    rng = float(np.linalg.norm(d_ij))
                    if 0.0 < rng < best_range:  # rng == 0 has no away-direction
                        best_j, best_range, best_d = j, rng, d_ij
                if best_j >= 0 and best_d is not None:
                    u_evade[i] = scenario.a_max_mps2 * best_d / best_range
                    evade_ticks_left[i] = scenario.safety.evade_ticks
                    events.append(
                        {
                            "type": "EVASIVE_MANEUVER",
                            "payload": {
                                "sat_id": i,
                                "other_id": best_j,
                                "range_m": best_range,
                                "t": t,
                            },
                        }
                    )

        # Step every satellite: healthy and DEGRADED sats PD-hold their assigned
        # seat -- unless an evasion episode is active, in which case the bounded
        # away-from-intruder burn replaces seat-holding for the episode (dv_used
        # accrues through PDController.apply_accel either way); DEAD and
        # THRUSTER_OUT sats coast ballistically (never freeze) and remain hazards.
        for i in range(n_sats):
            if status[i] in (STATUS_NOMINAL, STATUS_DEGRADED):
                if evade_ticks_left[i] > 0:
                    states[i] = controllers[i].apply_accel(
                        states[i], u_evade[i], dt, n
                    )
                    evade_ticks_left[i] -= 1
                else:
                    ref = propagate(formation[seat_of[i]], t, n)
                    states[i], _ = controllers[i].step(states[i], ref[:3], ref[3:], dt, n)
            else:
                states[i] = propagate(states[i], dt, n)

    # Time-averaged coverage over the last orbit (MASTER_PROMPT 3.4).
    window_start = scenario.duration_s - 2.0 * math.pi / n
    tail = [c for (tick_t, c) in coverage_by_tick if tick_t >= window_start - 1e-9]
    lines.append(
        {
            "v": LOG_SCHEMA_VERSION,
            "t": coverage_by_tick[-1][0],
            "state": STATE_SUMMARY,
            "coverage_mean_last_orbit": sum(tail) / len(tail),
        }
    )
    return lines
