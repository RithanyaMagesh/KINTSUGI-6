"""Nominal swarm simulation and versioned JSONL line model (gate G3).

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

Event contract designed now, emitted by G4 (events carry type + payload):
    FAILURE_DETECTED: payload {sat_id, mode, t_fail, t_detect}
    ASSIGNMENT: payload {assignments: [{sat_id, slot_index, role}], method, cost_total}

The run opens with one metadata line (state INIT: v, t, scenario, seed, n_sats --
the G0 header, kept for replay) and closes with one SUMMARY line carrying the
time-averaged coverage over the last orbit (MASTER_PROMPT 3.4). Tick lines are
exactly the schema above; state is "NOMINAL" until G4 adds the state machine.
"""

from __future__ import annotations

import math

import numpy as np

from cubesat.coverage import coverage_fraction, footprint_radius, target_grid
from cubesat.hcw import mean_motion, propagate
from cubesat.pd import PDController
from cubesat.scenario import Scenario

LOG_SCHEMA_VERSION = 1
STATE_INIT = "INIT"
STATE_NOMINAL = "NOMINAL"
STATE_SUMMARY = "SUMMARY"
STATUS_NOMINAL = "NOMINAL"


def slot_initial_state(
    radial_amp_m: float, cross_amp_m: float, phase_rad: float, n: float
) -> np.ndarray:
    """Slot at ellipse phase `phase_rad` on the COMMON passive relative orbit
    (radial amplitude radial_amp_m, cross-track amplitude cross_amp_m):
    x = A cos(nt+p), y = -2A sin(nt+p), z = B cos(nt+p).
    Drift-free (vy0 = -2 n x0; vx0 = -A n sin p only shifts the phase), so all
    slots are points of ONE drift-free 2:1 ellipse -- the locked "phase-spaced
    slots on passive relative orbits" formation (MASTER_PROMPT section 2)."""
    c = math.cos(phase_rad)
    s = math.sin(phase_rad)
    return np.array(
        [
            radial_amp_m * c,
            -2.0 * radial_amp_m * s,
            cross_amp_m * c,
            -radial_amp_m * n * s,
            -2.0 * radial_amp_m * n * c,
            -cross_amp_m * n * s,
        ]
    )


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
    """Simulate the nominal mission (every sat PD-holds its own slot; no failures
    until G4) and return the JSONL lines: [INIT header, tick..., SUMMARY]."""
    if scenario.n_sats != scenario.formation.n_slots:
        raise ValueError(
            f"{scenario.n_sats} roles but {scenario.formation.n_slots} slots: "
            "G3 maps sat i to slot i; G4 relaxes this"
        )
    altitude_m = scenario.chief.altitude_km * 1000.0
    n = mean_motion(altitude_m)
    dt = scenario.dt_s
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
    imager_ids = [i for i, role in enumerate(scenario.roles) if role == "imager"]

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
        centers = np.array([states[i][1:3] for i in imager_ids])
        coverage = coverage_fraction(centers, grid, r_f)
        positions = np.array([state[:3] for state in states])
        min_sep = min(
            float(np.linalg.norm(positions[i] - positions[j]))
            for i in range(len(states))
            for j in range(i + 1, len(states))
        )
        lines.append(
            {
                "v": LOG_SCHEMA_VERSION,
                "t": t,
                "state": STATE_NOMINAL,
                "sats": [
                    {
                        "id": i,
                        "role": scenario.roles[i],
                        "status": STATUS_NOMINAL,
                        "r": states[i][:3].tolist(),
                        "v": states[i][3:].tolist(),
                        "dv_used": controllers[i].dv_used,
                    }
                    for i in range(scenario.n_sats)
                ],
                "coverage": coverage,
                "min_sep": min_sep,
            }
        )
        coverage_by_tick.append((t, coverage))
        if k == n_ticks - 1:
            break
        for i in range(scenario.n_sats):
            ref = propagate(slots[i], t, n)
            states[i], _ = controllers[i].step(states[i], ref[:3], ref[3:], dt, n)

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
