"""`benchmark --mode formations` (track C phase C3): what each formation shape costs and buys.

Per shape (cubesat/formations.py), from the committed `formation_<shape>_6sat.json` files next
to `--base` (the cartwheel file):
- min pairwise separation over an orbit: CW (closed form, 1441 samples) and truth (EngineV2 holding
  the slots with the PD for 2 orbits, J2 + drag, min of the logged `min_sep`);
- worst CW separation under ANY along-track drift of one sat (psi_table.worst_separation, 2
  orbits): the drift hazard of a dead sat (0 = some drift puts it on a neighbour);
- coverage: CW (mean over the 1441 samples, scenario imagers) and truth (mean of the logged
  `coverage` over the 2 orbits);
- hold fuel per orbit: truth dv_used after 2 orbits / 2 (per sat max, and swarm total);
- switch from cartwheel: transfer.lp_transfer (CW planning model, T = 1 orbit, N = 48 nodes,
  a_max and k = 1 from the scenario). Seats by Hungarian on the free-plan L1 delta-v (rows =
  sats, cols = shape slots, index-epsilon ties). Then sequential priority planning: sat i
  avoids the planned paths of sats 0..i-1 with d_safe = allocation.min_sep_km, so every pair is
  checked once. The pairwise separation of the final plans is verified on a 1 s grid.

Deterministic: fixed shape and sat order, no RNG, no wall clock.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

from cubesat import formations as F
from cubesat.coverage import coverage_fraction, footprint_radius, target_grid
from cubesat.hcw import stm
from cubesat.psi_table import worst_separation
from cubesat.scenario import Scenario, load_scenario
from cubesat.sim import build_slots
from cubesat.sim_v2 import EngineV2
from cubesat.transfer import lp_transfer
from cubesat.transfer_validate import plan_positions

CW_SAMPLES = 1441  # per orbit, ~4 s; odd so no grid hits a symmetric minimiser by luck
TRUTH_ORBITS = 2
N_NODES = 48
OBSTACLE_STEP_S = 10.0  # keep-out obstacle sample spacing (linear interpolation in between)
TIE_EPS = 1e-9  # = allocate._TIE_EPS (AGENTS.md invariant 6)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cw_metrics(sc: Scenario, n: float) -> dict:
    slots = build_slots(sc, n)
    pos = F.positions_over_orbit(slots, n, CW_SAMPLES)
    imagers = [i for i, r in enumerate(sc.roles) if r == "imager"]
    alt = sc.chief.altitude_km * 1000.0
    r_f = footprint_radius(alt, math.radians(sc.sensor.fov_half_angle_deg))
    grid = target_grid(sc.sensor.grid_step_km * 1000.0, sc.sensor.grid_extent_km * 1000.0)
    cov = [coverage_fraction(p[imagers, 1:3], grid, r_f) for p in pos]
    return {
        "cw_min_sep_m": F.min_separation(slots, n, CW_SAMPLES),
        "cw_worst_sep_any_along_track_drift_m": worst_separation(slots, n),
        "cw_coverage": float(np.mean(cov)),
    }


def _truth_metrics(sc: Scenario) -> dict:
    eng = EngineV2(sc)
    sc = sc.model_copy(update={"duration_s": TRUTH_ORBITS * 2.0 * math.pi / eng.n})
    lines = [ln for ln in EngineV2(sc).run() if "sats" in ln]
    dv = np.array([s["dv_used"] for s in lines[-1]["sats"]]) / TRUTH_ORBITS
    return {
        "truth_orbits": TRUTH_ORBITS,
        "truth_min_sep_m": min(ln["min_sep"] for ln in lines),
        "truth_coverage": float(np.mean([ln["coverage"] for ln in lines])),
        "hold_dv_per_orbit_max_sat_mps": float(dv.max()),
        "hold_dv_per_orbit_total_mps": float(dv.sum()),
        "hold_dv_per_orbit_per_sat_mps": dv.tolist(),
    }


def _switch(sc_from: Scenario, sc_to: Scenario, n: float) -> dict:
    x0, xt = np.array(build_slots(sc_from, n)), np.array(build_slots(sc_to, n))
    T, a, d_safe = 2.0 * math.pi / n, sc_to.a_max_mps2, sc_to.allocation.min_sep_km * 1000.0
    phi = stm(T, n)
    k = len(x0)
    free = [
        [lp_transfer(x0[i], phi @ xt[j], T, n, a, 1.0, N_NODES) for j in range(k)]
        for i in range(k)
    ]
    cost = np.array([[math.inf if p is None else p.total_dv_mps for p in row] for row in free])
    big = np.where(np.isfinite(cost), cost, 1e9)  # no free plan: only taken if nothing else fits
    rows, cols = linear_sum_assignment(big + TIE_EPS * np.arange(k * k).reshape(k, k))
    obs_t = np.arange(0.0, T + OBSTACLE_STEP_S, OBSTACLE_STEP_S).clip(max=T)
    grid = np.arange(0.0, T, 1.0)
    keepout, paths, sats = [], [], []
    for i, j in zip(rows, cols, strict=True):
        plan = lp_transfer(x0[i], phi @ xt[j], T, n, a, 1.0, N_NODES, keepout or None)
        ok = plan is not None
        plan = plan if ok else free[i][j]
        sats.append({
            "sat": int(i),
            "slot": int(j),
            "keepout_ok": ok,
            "dv_l1_mps": None if plan is None else plan.total_dv_mps,
            "dv_l2_mps": None if plan is None else plan.l2_dv_mps,
            "free_dv_l1_mps": None if free[i][j] is None else free[i][j].total_dv_mps,
        })
        if plan is not None:
            keepout.append((obs_t, plan_positions(x0[i], plan.times, plan.dv, n, obs_t), d_safe))
            paths.append(plan_positions(x0[i], plan.times, plan.dv, n, grid))
    p = np.stack(paths, axis=1) if paths else np.zeros((1, 0, 3))
    iu = np.triu_indices(p.shape[1], k=1)
    sep = np.linalg.norm(p[:, iu[0]] - p[:, iu[1]], axis=-1).min() if iu[0].size else math.inf
    dvs = [s["dv_l1_mps"] for s in sats]
    return {
        "T_s": T, "N": N_NODES, "a_max_mps2": a, "d_safe_m": d_safe,
        "feasible": all(s["keepout_ok"] for s in sats) and float(sep) >= d_safe,
        "min_pair_sep_during_switch_m": float(sep),
        "total_dv_l1_mps": None if None in dvs else float(sum(dvs)),
        "max_sat_dv_l1_mps": None if None in dvs else float(max(dvs)),
        "per_sat": sats,
    }


def build_report(base_path: Path, command: str) -> dict:
    files = {s: base_path.with_name(f"formation_{s}_6sat.json") for s in F.SHAPES}
    scen = {s: load_scenario(p) for s, p in files.items()}
    if scen["cartwheel"].formation.shape != "cartwheel":
        raise ValueError(f"--base must be the cartwheel formation file, got {base_path}")
    n = EngineV2(scen["cartwheel"]).n
    shapes = {}
    for s, sc in scen.items():
        row = {"scenario": str(files[s]), **_cw_metrics(sc, n), **_truth_metrics(sc)}
        row["switch_from_cartwheel"] = _switch(scen["cartwheel"], sc, n)
        shapes[s] = row
    return {
        "command": command,
        "inputs_sha256": {str(p): _sha(p) for p in files.values()},
        "notes": [
            "illustrative scenarios (8 km amplitude; string: 8 km along-track spacing)",
            "CW = linear Hill-Clohessy-Wiltshire; truth = EngineV2 (J2 + drag, PD hold)",
            "switch delta-v is the L1 (per-axis) LP objective, an upper bound on vector fuel; "
            "CW planning model, not flown in truth",
            "recovery is not shape-aware (allocate_v2.candidate_slots = cartwheel + psi family)",
        ],
        "shapes": shapes,
    }


def run(args) -> int:
    command = "uv run python -m cubesat.benchmark " + " ".join(args.argv)
    report = build_report(Path(args.base), command)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    for s, r in report["shapes"].items():
        sw = r["switch_from_cartwheel"]
        print(
            f"{s:9s} sep CW {r['cw_min_sep_m']:9.1f} truth {r['truth_min_sep_m']:9.1f} m  "
            f"drift {r['cw_worst_sep_any_along_track_drift_m']:7.1f} m  "
            f"cov {r['cw_coverage']:.4f}/{r['truth_coverage']:.4f}  "
            f"hold {r['hold_dv_per_orbit_total_mps']:.4f} m/s/orbit  "
            f"switch {sw['total_dv_l1_mps']} m/s feasible={sw['feasible']}"
        )
    print(f"wrote {args.report}")
    return 0
