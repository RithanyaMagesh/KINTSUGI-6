"""Cross-track phase psi trade table (physics Phase 5b): imaging coverage vs how close
a dead satellite can drift to its neighbours. Pure functions + a report CLI:

    uv run python -m cubesat.psi_table --report data/eval/psi_trade_table.json

SI, LVLH (AGENTS.md invariants 3-4). Not wired into the engine.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

from cubesat.allocate import _coverage_estimate, seat_roles_for
from cubesat.allocate_v2 import candidate_slots
from cubesat.coverage import footprint_radius, target_grid
from cubesat.hcw import mean_motion, propagate

COMMAND = "uv run python -m cubesat.psi_table --report data/eval/psi_trade_table.json"
PSIS = (0, 15, 30, 45, 60, 75, 90)
ALT_M = 500e3
N_SLOTS, N_IMAGERS = 6, 4
SAMPLES, ORBITS = 2881, 2  # odd: no grid holds a symmetric minimiser time by luck; ~2 s steps
HALF = (SAMPLES - 1) // 2 + 1  # halved grid (spacing x2 up to one sample)
BRIEF_PATH = "docs/superpowers/specs/2026-10-31-physics-v2-brief.md section 4 Phase 5 item 3"
BRIEF = {  # A = B = 8 km: psi -> (coverage, worst separation m)
    0: (0.371, 11.8), 30: (0.364, 2929.0), 45: (0.355, 4330.0), 60: (0.345, 5657.0),
    90: (0.326, 8000.0),
}
CASES = (  # label, amp m, fov_half deg, grid step m, grid half-extent m
    ("A=B=8 km, fov_half 1.5 deg", 8000.0, 1.5, 2000.0, 30000.0),
    ("A=B=2 km, fov_half 0.375 deg (kit v2 formation, illustrative; grid scaled by 1/4)",
     2000.0, 0.375, 500.0, 7500.0),
)


def imager_seat_roles(k: int, n_imagers: int, layout: str = "even") -> list[str]:
    """Seat roles. "even": allocate.seat_roles_for's layout (imagers on even seats, the
    replan convention; 6 seats / 4 imagers -> seats 0, 2, 4, 5). "scenario": the scenario
    role order (imagers first, seats 0..3), i.e. the initial formation in sim.py."""
    roles = ["imager"] * n_imagers + ["leader", "downlink"] + ["bus"] * (k - n_imagers - 2)
    return seat_roles_for(roles, roles) if layout == "even" else roles


def pair_min_distance(si, sj, n: float, t, *, s_max: float, s_step: float | None = None) -> float:
    """min over times t and along-track offsets s in [-s_max, s_max] of
    |p_i(t) - (p_j(t) + s * y_hat)|: slot i flies normally, slot j (the 'dead' one) is
    displaced by s along track. A y-shift of the initial state shifts y(t) by exactly s
    at every t (the CW y-row has coefficient 1 on y0 and nothing else depends on y), so
    the s-minimum is closed form: s* = clip(dy, -s_max, s_max) (exact, no s grid).
    s_step quantises s to multiples of s_step (a grid in s); s_max = 0 is the s = 0
    metric."""
    d = propagate(si, t, n)[:, :3] - propagate(sj, t, n)[:, :3]
    s = d[:, 1] if s_step is None else np.round(d[:, 1] / s_step) * s_step
    d[:, 1] -= np.clip(s, -s_max, s_max)
    return float(np.linalg.norm(d, axis=1).min())


def worst_separation(
    slots, n: float, *, orbits: int = ORBITS, samples_per_orbit: int = SAMPLES,
    s_max: float | None = None, s_step: float | None = None,
) -> float:
    """Worst-case pair separation [m] under ANY along-track drift of one satellite:
    min over pairs (i, j), t in [0, orbits periods] on a grid of samples_per_orbit
    points per orbit, and s in [-s_max, s_max]. A dead satellite drifting along track
    (any s(t)) can do no better than this min over (t, s). Default s_max = twice the
    largest |y| on the grid, enough to sweep the whole ring (dy <= 2 max|y|)."""
    period = 2.0 * math.pi / n
    t = np.arange(orbits * samples_per_orbit + 1) * (period / samples_per_orbit)
    if s_max is None:
        s_max = 2.0 * max(float(np.abs(propagate(s, t, n)[:, 1]).max()) for s in slots)
    return min(
        pair_min_distance(slots[i], slots[j], n, t, s_max=s_max, s_step=s_step)
        for i in range(len(slots)) for j in range(i + 1, len(slots))
    )


def mean_coverage(
    slots, n: float, *, fov_half_deg: float, altitude_m: float = ALT_M,
    step_m: float = 2000.0, extent_m: float = 30000.0, n_imagers: int = N_IMAGERS,
    layout: str = "even",
) -> float:
    """Mean imager coverage over one orbit: allocate._coverage_estimate (72 samples per
    orbit, union of footprints r_f = h tan(fov_half) on coverage.target_grid)."""
    return _coverage_estimate(
        slots, imager_seat_roles(len(slots), n_imagers, layout),
        r_f=footprint_radius(altitude_m, math.radians(fov_half_deg)),
        grid=target_grid(step_m, extent_m), n=n, t_replan=0.0,
    )


def _row(psi, amp, fov, step, extent, n) -> dict:
    slots = candidate_slots(amp, 0.0, float(psi), N_SLOTS, n)
    sep = worst_separation(slots, n)
    half = worst_separation(slots, n, samples_per_orbit=HALF)
    cov = {
        lay: mean_coverage(slots, n, fov_half_deg=fov, step_m=step, extent_m=extent, layout=lay)
        for lay in ("even", "scenario")
    }
    row = {
        "psi_deg": psi,
        "coverage": round(cov["even"], 6),
        "coverage_scenario_order": round(cov["scenario"], 6),
        "worst_separation_m": round(sep, 3),
        "worst_separation_half_grid_m": round(half, 3),
        "convergence_delta_m": round(abs(sep - half), 3),
        "worst_separation_s0_only_m": round(worst_separation(slots, n, s_max=0.0), 3),
    }
    if amp == 8000.0 and psi in BRIEF:
        bc, bs = BRIEF[psi]
        rel = abs(row["worst_separation_m"] - bs) / bs
        row["brief_diff"] = {
            "brief_coverage": bc, "brief_separation_m": bs,
            "coverage_diff": round(row["coverage"] - bc, 6),
            "coverage_diff_scenario_order": round(row["coverage_scenario_order"] - bc, 6),
            "separation_diff_m": round(row["worst_separation_m"] - bs, 3),
            "separation_rel_diff": round(rel, 6),
            "flag": bool(rel > 0.02 or abs(row["coverage"] - bc) > 0.003),
            "flag_scenario_order": bool(
                rel > 0.02 or abs(row["coverage_scenario_order"] - bc) > 0.003),
        }
    return row


def build_report() -> dict:
    n = mean_motion(ALT_M)
    cases = []
    for label, amp, fov, step, extent in CASES:
        cases.append({
            "label": label, "amp_m": amp, "fov_half_deg": fov,
            "r_f_m": round(footprint_radius(ALT_M, math.radians(fov)), 3),
            "grid_step_m": step, "grid_extent_m": extent,
            "rows": [_row(p, amp, fov, step, extent, n) for p in PSIS],
        })
    return {
        "command": COMMAND, "brief": BRIEF_PATH, "n_slots": N_SLOTS, "n_imagers": N_IMAGERS,
        "altitude_m": ALT_M, "coverage_samples_per_orbit": 72,
        "seat_roles": imager_seat_roles(N_SLOTS, N_IMAGERS),
        "seat_roles_scenario_order": imager_seat_roles(N_SLOTS, N_IMAGERS, "scenario"),
        "separation_grid": {"orbits": ORBITS, "samples_per_orbit": SAMPLES,
                            "half_grid_samples_per_orbit": HALF,
                            "s": "closed-form minimum over s in [-S, S], S = 2 max|y|"},
        "metric": (
            "worst separation = min over slot pairs, t in [0, 2 orbits] and along-track "
            "offset s of one slot of the 3-D distance; see cubesat/psi_table.py"),
        "cases": cases,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--report", required=True, help="output JSON path")
    out = Path(ap.parse_args(argv).report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build_report(), indent=2) + "\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
