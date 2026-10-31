"""CW-vs-truth report (Phase 1, Task 1.5): how far the v2 truth engine departs from the v1
linear-CW path for a passive formation, per formation scale, J2 on/off, drag on/off.

Passive = a_max 1e-12 m/s^2 (no effective control), so the v1 path is exactly the analytic CW
STM (hcw.stm applied to the slot states) and v2 is free truth motion (ECI two-body [+J2] [+drag],
RK4 dt = 2 s) of the same initial LVLH states. Metric: max over sats and ticks of
|r_v2 - r_CW| in the LVLH frame. `g1_state` repeats the G1 evidence state (1 km radial, 500 m
cross-track, cubesat/cw_curve.py) and compares with the independent two-body RK45 reference.

    uv run python -m cubesat.cw_truth --report data/eval/cw_vs_truth_report.json

Deterministic: fixed case order, no RNG, no wall clock.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from cubesat import cw_curve, hcw
from cubesat.scenario import Scenario
from cubesat.sim import build_slots
from cubesat.sim_v2 import EngineV2

DEFAULT_REPORT = "data/eval/cw_vs_truth_report.json"
SCALES_KM = (1.0, 8.0)


def passive_scenario(radial_km: float, duration_s: float, *, j2: bool, drag: bool, n_sats: int = 6):
    return Scenario.model_validate(
        {
            "name": "cw_truth",
            "seed": 0,
            "engine": "v2",
            "duration_s": duration_s,
            "dt_s": 2.0,
            "chief": {"altitude_km": 500.0},
            "formation": {"n_slots": n_sats, "radial_amp_km": radial_km, "phase_offset_deg": 0.0},
            "a_max_mps2": 1e-12,
            "gains": {"wn": 0.01, "zeta": 1.0},
            "sensor": {"fov_half_angle_deg": 1.5, "grid_step_km": 5.0, "grid_extent_km": 5.0},
            "roles": ["imager"] * n_sats,
            "truth": {"j2_enabled": j2, "density_factor": 1.0 if drag else 0.0},
        }
    )


def max_diff_vs_cw(scenario: Scenario, start: np.ndarray | None = None) -> float:
    """Max |r_v2 - r_CW| [m] over all sats and ticks (CW = hcw.stm applied to `start`)."""
    eng = EngineV2(scenario, initial_lvlh=start)
    start = np.array(build_slots(scenario, eng.n)) if start is None else start
    worst = 0.0
    for _ in range(eng.n_ticks):
        t = eng.k * eng.dt
        r = np.array([s["r"] for s in eng.step()["sats"]])
        cw = (start @ hcw.stm(t, eng.n).T)[:, :3]
        worst = max(worst, float(np.linalg.norm(r - cw, axis=1).max()))
    return worst


def g1_case(orbits: float, *, j2: bool, drag: bool) -> tuple[Scenario, np.ndarray]:
    """Two sats on the G1 evidence state (1 km radial, 500 m cross-track) and its negative."""
    g1 = cw_curve.state_1km_passive_ellipse()
    s = passive_scenario(1.0, orbits * cw_curve.PERIOD, j2=j2, drag=drag, n_sats=2)
    return s, np.array([g1, -g1])


def build_report(orbits: float = 3.0, command: str = "") -> dict:
    period = cw_curve.PERIOD
    duration = orbits * period
    cases = [
        {
            "radial_amp_km": km,
            "j2": j2,
            "drag": drag,
            "orbits": orbits,
            "max_pos_diff_m": max_diff_vs_cw(passive_scenario(km, duration, j2=j2, drag=drag)),
        }
        for km in SCALES_KM
        for j2 in (False, True)
        for drag in (False, True)
    ]
    s, g1_start = g1_case(orbits, j2=False, drag=False)
    g1 = g1_start[0]
    t_grid = np.linspace(0.0, duration, max(int(orbits * 200), 2) + 1)
    kepler = cw_curve.cw_vs_kepler_errors(
        g1, t_grid=t_grid, n=cw_curve.N, chief_y=cw_curve.chief_states(t_grid)
    )
    return {
        "command": command,
        "dt_s": 2.0,
        "altitude_km": 500.0,
        "inclination_deg": 97.4,
        "period_s": period,
        "orbits": orbits,
        "formation": "6 ring slots, planar (z amplitude = x)",
        "control": "none (a_max 1e-12 m/s^2): v1 path = analytic CW STM",
        "truth_defaults": {
            "cd": 2.2,
            "area_active_m2": 0.010,
            "mass_kg": 4.0,
            "illustrative": True,
        },
        "metric": "max over sats and ticks of |r_v2 - r_CW| in LVLH, m",
        "cases": cases,
        "g1_state": {
            "orbits": orbits,
            "v2_vs_cw_max_m": max_diff_vs_cw(s, g1_start),
            "cw_vs_two_body_rk45_max_m": float(kepler.max()),
            "note": "1 km radial / 500 m cross-track state, J2 off, drag off; GATES.md G1: 3.101 m",
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--report", default=DEFAULT_REPORT)
    ap.add_argument("--orbits", type=float, default=3.0)
    args = ap.parse_args(argv)
    cmd = f"uv run python -m cubesat.cw_truth --report {args.report}"
    cmd += f" --orbits {args.orbits:g}" if args.orbits != 3.0 else ""
    report = build_report(args.orbits, cmd)
    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    for c in report["cases"]:
        print(
            f"{c['radial_amp_km']:g} km  J2={c['j2']!s:5}  drag={c['drag']!s:5}  "
            f"max diff {c['max_pos_diff_m']:.4f} m"
        )
    print(
        f"G1 state: {report['g1_state']['v2_vs_cw_max_m']:.4f} m "
        f"(RK45 ref {report['g1_state']['cw_vs_two_body_rk45_max_m']:.4f} m) -> {path}"
    )
    return 0 if all(math.isfinite(c["max_pos_diff_m"]) for c in report["cases"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
