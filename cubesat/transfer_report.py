"""LP-vs-PD delta-v evidence table for Phase 5c (docs/PHYSICS_V2.md "Phase 5c").

    uv run python -m cubesat.transfer_report --report data/eval/lp_vs_pd_dv_table.json

Reference case: v1 run of data/scenarios/two_failure.json, first replan; sat 0's logged state at
the ASSIGNMENT tick (t = 1208 s) to its assigned slot (formation amp 8000 m, k = 5, slot 1),
propagated to the arrival time. Second case: 2 km ring (slot 0 -> slot 1 of 5). Wall time is
measured ONLY here (machine-dependent); the planner itself reads no clock.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

from cubesat.dv_bound import parse_episodes, two_impulse_dv
from cubesat.hcw import mean_motion, propagate, slot_initial_state
from cubesat.pd import PDController
from cubesat.scenario import load_scenario
from cubesat.sim import run_scenario
from cubesat.transfer import lp_transfer

BASE = Path("data/scenarios/two_failure.json")
A_MAXES = (0.1, 0.01, 0.002)
ORBITS = (0.5, 1.0, 2.0)
N_DEFAULT = 48
N_SWEEP = (12, 24, 48, 96)
TOL_FRAC = 0.05  # PD "settled": position error <= 5% of the transfer distance


def reference_case() -> dict:
    sc = load_scenario(BASE)
    n = mean_motion(sc.chief.altitude_km * 1e3)
    lines = run_scenario(sc)
    ep = parse_episodes(lines)[0]
    asg = ep["assignment"]
    k = len(asg["assignments"])
    slot_index = next(a["slot_index"] for a in asg["assignments"] if a["sat_id"] == 0)
    amp, phi0 = asg["formation"]["radial_amp_m"], asg["formation"]["phase_offset_rad"]
    t_assign = ep["t_replan"] + sc.dt_s
    sat0 = next(s for s in next(ln for ln in lines if ln["t"] == t_assign)["sats"] if s["id"] == 0)
    return {
        "name": "reference_8km_leader",
        "n": n,
        "t0": t_assign,
        "x0": np.array([*sat0["r"], *sat0["v"]]),
        "slot": slot_initial_state(amp, amp, phi0 + 2 * math.pi * slot_index / k, n),
        "amp_m": amp,
        "k_survivors": k,
        "slot_index": slot_index,
        "x0_t_replan": np.array(
            [*next(s for s in ep["start_sats"] if s["id"] == 0)["r"],
             *next(s for s in ep["start_sats"] if s["id"] == 0)["v"]]
        ),
        "t_replan": ep["t_replan"],
    }


def formation_2km_case(n: float) -> dict:
    amp, k = 2000.0, 5
    return {
        "name": "formation_2km_slot0_to_slot1",
        "n": n,
        "t0": 0.0,
        "x0": slot_initial_state(amp, amp, 0.0, n),
        "slot": slot_initial_state(amp, amp, 2 * math.pi / k, n),
        "amp_m": amp,
        "k_survivors": k,
        "slot_index": 1,
    }


def pd_transfer(case: dict, a_max: float, wn=0.01, zeta=1.0, dt=2.0, orbits=4.0) -> dict:
    """Real v1 PDController to the moving slot; settle = first time after which the position
    error stays <= 5% of the initial transfer distance (dv reported up to that instant; if it
    never settles within `orbits` periods: 'diverged', dv over the whole horizon)."""
    n, t0, slot = case["n"], case["t0"], case["slot"]
    pd = PDController(wn, zeta, a_max)
    x = np.asarray(case["x0"], float).copy()
    d0 = float(np.linalg.norm(x[:3] - propagate(slot, t0, n)[:3]))
    err, dv = [], []
    for i in range(int(orbits * 2 * math.pi / n / dt) + 1):
        ref = propagate(slot, t0 + i * dt, n)
        err.append(float(np.linalg.norm(x[:3] - ref[:3])))
        dv.append(pd.dv_used)
        x, _ = pd.step(x, ref[:3], ref[3:], dt, n)
    bad = [i for i, e in enumerate(err) if e > TOL_FRAC * d0]
    settled = not bad or bad[-1] < len(err) - 1
    i = bad[-1] + 1 if bad else 0
    if not settled:
        i = len(err) - 1
    return {
        "status": "settled" if settled else "diverged",
        "dv_used_mps": dv[i],
        "settle_s": i * dt if settled else None,
        "residual_m": err[i],
        "transfer_distance_m": d0,
        "horizon_s": (len(err) - 1) * dt,
    }


def lp_row(case: dict, a_max: float, T_orb: float, N: int, pd: dict) -> dict:
    n, t0 = case["n"], case["t0"]
    T = T_orb * 2 * math.pi / n
    x_t = propagate(case["slot"], t0 + T, n)
    c0 = time.perf_counter()
    tr = lp_transfer(case["x0"], x_t, T, n, a_max, 1.0, N)
    ms = (time.perf_counter() - c0) * 1e3
    ti = two_impulse_dv(case["x0"], case["slot"], t0, t0 + T, n)
    row = {
        "case": case["name"], "a_max_mps2": a_max, "T_orbits": T_orb, "T_s": T, "N": N,
        "solver": "scipy linprog highs",
        "solver_status": "optimal" if tr else "infeasible",
        "feasible": tr is not None,
        "lp_total_l1_mps": tr.total_dv_mps if tr else None,
        "lp_total_l2_mps": tr.l2_dv_mps if tr else None,
        "lp_runtime_ms_machine_dependent": ms,
        "two_impulse_same_T_mps": None if ti["singular"] else ti["dv_total_mps"],
        "two_impulse_same_T_singular": bool(ti["singular"]),
        "pd_status": pd["status"], "pd_dv_mps": pd["dv_used_mps"],
        "pd_settle_s": pd["settle_s"], "pd_residual_m": pd["residual_m"],
    }
    if pd["settle_s"]:
        w = two_impulse_dv(case["x0"], case["slot"], t0, t0 + pd["settle_s"], n)
        row["two_impulse_at_pd_settle_T_mps"] = None if w["singular"] else w["dv_total_mps"]
    else:
        row["two_impulse_at_pd_settle_T_mps"] = None
    return row


def build_report(command: str) -> dict:
    ref = reference_case()
    cases = [ref, formation_2km_case(ref["n"])]
    pds, rows = {}, []
    for case in cases:
        for a in A_MAXES:
            pds[case["name"], a] = pd_transfer(case, a)
            for o in ORBITS:
                rows.append(lp_row(case, a, o, N_DEFAULT, pds[case["name"], a]))
    conv = []
    for name, a, o in (
        ("reference_8km_leader", 0.01, 1.0),
        ("reference_8km_leader", 0.1, 1.0),
        ("formation_2km_slot0_to_slot1", 0.002, 1.0),
    ):
        case = cases[0] if name.startswith("ref") else cases[1]
        series = [lp_row(case, a, o, N, pds[name, a]) for N in N_SWEEP]
        tot = [s["lp_total_l1_mps"] for s in series]
        conv.append({
            "case": name, "a_max_mps2": a, "T_orbits": o, "N": list(N_SWEEP), "l1_mps": tot,
            "l2_mps": [s["lp_total_l2_mps"] for s in series],
            "rel_change_on_halving": [
                abs(tot[i] - tot[i - 1]) / tot[i] for i in range(1, len(tot))
            ],
        })

    def pick(case, a, o):
        return next(r for r in rows if r["case"] == case and r["a_max_mps2"] == a
                    and r["T_orbits"] == o)

    r8 = pick("reference_8km_leader", 0.01, 1.0)
    r2 = pick("formation_2km_slot0_to_slot1", 0.002, 1.0)
    x_alt = propagate(ref["slot"], ref["t_replan"] + r8["T_s"], ref["n"])
    alt = lp_transfer(ref["x0_t_replan"], x_alt, r8["T_s"], ref["n"], 0.01, 1.0, N_DEFAULT)
    brief = [
        {"claim": "16.4 m/s at a_max 0.01, T = 1 orbit, 8 km leader", "claimed_mps": 16.4,
         "measured_l1_mps": r8["lp_total_l1_mps"], "measured_l2_mps": r8["lp_total_l2_mps"],
         "alt_start_t_replan_l1_mps": alt.total_dv_mps if alt else None},
        {"claim": "~4 m/s at a_max 0.002, 2 km formation (T = 1 orbit)", "claimed_mps": 4.0,
         "measured_l1_mps": r2["lp_total_l1_mps"], "measured_l2_mps": r2["lp_total_l2_mps"]},
    ]
    for b in brief:
        b["definition"] = (
            f"LP, N={N_DEFAULT}, k=1, T = 1 orbit, CW planning model; compared as measured "
            "(no tuning of N, caps or T). L1 = LP objective, L2 = sum of impulse magnitudes."
        )
        m = b["measured_l1_mps"]
        b["difference_l1_mps"] = None if m is None else m - b["claimed_mps"]
    return {
        "command": command,
        "definitions": {
            "lp_total_l1_mps": "LP objective: sum over nodes and axes of |dv| (minimised)",
            "lp_total_l2_mps": "sum over nodes of ||dv_k||_2 (physical delta-v), same plan",
            "reference_start": "sat 0 logged state at the ASSIGNMENT tick (t_replan + dt); "
            "alt_start uses the REPLANNING-tick state",
            "pd": "cubesat.pd.PDController wn=0.01 zeta=1 a_max, dt 2 s, 4 orbits, moving slot",
            "two_impulse": "cubesat.dv_bound.two_impulse_dv, L2 sum; null when its singularity "
            "guard fires (T = k*pi/n kills the z / xy velocity solve)",
            "wall_time": "lp_runtime_ms_machine_dependent is wall time on the generating machine",
        },
        "reference_case": {k: (v.tolist() if isinstance(v, np.ndarray) else v)
                           for k, v in ref.items() if k not in ("slot", "x0_t_replan")},
        "n_default": N_DEFAULT,
        "rows": rows,
        "convergence": conv,
        "brief_comparison": brief,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--report", required=True, type=Path)
    args = ap.parse_args(argv)
    cmd = "uv run python -m cubesat.transfer_report --report " + args.report.as_posix()
    rep = build_report(cmd)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.report} ({len(rep['rows'])} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
