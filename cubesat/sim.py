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
    FAILURE_DETECTED: {sat_id, mode, t_fail, t_detect}
    STATE:            {from, to}                    (plain transitions)
    ASSIGNMENT:       {assignments: [{sat_id, slot_index, role}], method,
                       cost_total, formation: {radial_amp_m, phase_offset_rad},
                       transfer_lower_bound_s}
The replanner (cubesat.allocate.replan) runs BETWEEN sim steps -- one control
cycle per machine transition -- never inside the step loop below it. Every sat
emits a heartbeat each tick; a sat that stops reporting is declared DEAD after
missed_ticks_k misses. DEAD sats (and THRUSTER_OUT sats) coast ballistically --
never frozen -- and stay in the min_sep pairwise loop as collision hazards.
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
    mission = STATE_NOMINAL
    events: list[dict] = []  # FIFO; at most one popped per tick line
    replan_due = False
    assigned = False
    recover_tol = 0.0

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
        # Failures fire (before this tick's heartbeat), in scheduled order.
        while next_failure < len(failures) and failures[next_failure].t <= t + 1e-9:
            failure = failures[next_failure]
            next_failure += 1
            i = failure.sat_id
            if status[i] != STATUS_DEAD:
                status[i] = (
                    STATUS_DEAD if failure.mode == FailureMode.DEAD else STATUS_THRUSTER_OUT
                )
                t_fail[i] = failure.t
                fail_mode[i] = str(failure.mode.value)
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
            formation = plan.slots
            for row, col in pairs:
                sat_id = assignable[row]
                seat_of[sat_id] = col
                roles[sat_id] = plan.seat_roles[col]
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
                                "slot_index": c,
                                "role": plan.seat_roles[c],
                            }
                            for r, c in sorted(pairs)
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
                if status[i] == STATUS_NOMINAL
            )
            if settled:
                mission = STATE_RECOVERED
                events.append(
                    {
                        "type": "STATE",
                        "payload": {"from": STATE_RECONFIGURING, "to": STATE_RECOVERED},
                    }
                )

        # Step every satellite: healthy sats PD-hold their assigned seat; DEAD and
        # THRUSTER_OUT sats coast ballistically (never freeze) and remain hazards.
        for i in range(n_sats):
            if status[i] == STATUS_NOMINAL:
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
