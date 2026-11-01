"""LP-vs-PD delta-v evidence table for Phase 5c (docs/PHYSICS_V2.md "Phase 5c").

    uv run python -m cubesat.transfer_report --report data/eval/lp_vs_pd_dv_table.json
    uv run python -m cubesat.transfer_report --landing-fuzz data/eval/lp_landing_fuzz.json
    uv run python -m cubesat.transfer_report --keepout-fuzz data/eval/lp_keepout_fuzz.json

Reference case: v1 run of data/scenarios/two_failure.json, first replan; sat 0's logged state at
the ASSIGNMENT tick (t = 1208 s, i.e. AFTER the first PD step, 0.2 m/s already spent) to its
assigned slot (formation amp 8000 m, k = 5, slot 1), propagated to the arrival time; the pure
planning state is the REPLANNING tick (t = 1206 s), shown as the `lp_alt_start_*` columns.
Second case: 2 km ring (slot 0 -> slot 1 of 5). Wall time is measured ONLY here
(machine-dependent); the planner itself reads no clock.
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
from cubesat.transfer_checks import (
    dual_lower_bound_l2,
    keepout_fuzz,
    l2_optimum,
    landing_fuzz,
    min_feasible_a_max,
    sphere_min_a_max,
)

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
    sat0_replan = next(s for s in ep["start_sats"] if s["id"] == 0)
    return {
        "name": "reference_8km_leader",
        "n": n,
        "t0": t_assign,
        "x0": np.array([*sat0["r"], *sat0["v"]]),
        "slot": slot_initial_state(amp, amp, phi0 + 2 * math.pi * slot_index / k, n),
        "amp_m": amp,
        "k_survivors": k,
        "slot_index": slot_index,
        "x0_t_replan": np.array([*sat0_replan["r"], *sat0_replan["v"]]),
        "t_replan": ep["t_replan"],
        "dv_already_spent_mps": sat0["dv_used"] - sat0_replan["dv_used"],
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


def lp_only(case: dict, a_max: float, T_orb: float, N: int, x0=None, t0=None):
    n = case["n"]
    t0 = case["t0"] if t0 is None else t0
    T = T_orb * 2 * math.pi / n
    x_t = propagate(case["slot"], t0 + T, n)
    c0 = time.perf_counter()
    tr = lp_transfer(case["x0"] if x0 is None else x0, x_t, T, n, a_max, 1.0, N)
    return tr, T, (time.perf_counter() - c0) * 1e3


def lp_row(case: dict, a_max: float, T_orb: float, N: int, pd: dict) -> dict:
    n, t0 = case["n"], case["t0"]
    tr, T, ms = lp_only(case, a_max, T_orb, N)
    ti = two_impulse_dv(case["x0"], case["slot"], t0, t0 + T, n)
    row = {
        "case": case["name"],
        "a_max_mps2": a_max,
        "T_orbits": T_orb,
        "T_s": T,
        "N": N,
        "solver": "scipy linprog highs",
        "solver_status": "optimal" if tr else "no_plan",
        "feasible": tr is not None,
        "lp_total_l1_mps": tr.total_dv_mps if tr else None,
        "lp_total_l2_mps": tr.l2_dv_mps if tr else None,
        "lp_runtime_ms_machine_dependent": ms,
        "two_impulse_same_T_l2_mps": None if ti["singular"] else ti["dv_total_mps"],
        "two_impulse_same_T_singular": bool(ti["singular"]),
        "pd_status": pd["status"],
        "pd_dv_l2_mps": pd["dv_used_mps"],
        "pd_settle_s": pd["settle_s"],
        "pd_residual_m": pd["residual_m"],
        "two_impulse_at_pd_settle_T_l2_mps": None,
    }
    if pd["settle_s"]:
        w = two_impulse_dv(case["x0"], case["slot"], t0, t0 + pd["settle_s"], n)
        row["two_impulse_at_pd_settle_T_l2_mps"] = None if w["singular"] else w["dv_total_mps"]
    if "x0_t_replan" in case:  # the pure planning state, t = t_replan
        alt, _, _ = lp_only(case, a_max, T_orb, N, case["x0_t_replan"], case["t_replan"])
        row["lp_alt_start_t_replan_l1_mps"] = alt.total_dv_mps if alt else None
        row["lp_alt_start_t_replan_l2_mps"] = alt.l2_dv_mps if alt else None
    return row


def l2_check(case: dict) -> list[dict]:
    """True L2 optimum (SLSQP) vs the LP's L2, 8 km reference, T = 1 orbit, N = 48."""
    n, N = case["n"], N_DEFAULT
    T = 2 * math.pi / n
    x_t = propagate(case["slot"], case["t0"] + T, n)
    out = []
    for a in (0.1, 0.01):
        lp = lp_transfer(case["x0"], x_t, T, n, a, 1.0, N)
        box = l2_optimum(case["x0"], x_t, T, n, a, N, "box")
        sph = l2_optimum(case["x0"], x_t, T, n, a, N, "sphere")
        out.append(
            {
                "a_max_mps2": a,
                "T_orbits": 1.0,
                "N": N,
                "lp_l2_mps": lp.l2_dv_mps,
                "lp_l1_mps": lp.total_dv_mps,
                "slsqp_box_l2_mps": box["l2_mps"],
                "slsqp_sphere_l2_mps": sph["l2_mps"],
                "slsqp_box_success": box["success"],
                "slsqp_sphere_success": sph["success"],
                "slsqp_box_landing_residual_m": box["landing_residual_m"],
                "slsqp_sphere_landing_residual_m": sph["landing_residual_m"],
                "dual_lower_bound_uncapped_l2_mps": dual_lower_bound_l2(case["x0"], x_t, T, n, N),
                "gap_box_pct": 100 * (lp.l2_dv_mps / box["l2_mps"] - 1.0),
                "gap_sphere_pct": 100 * (lp.l2_dv_mps / sph["l2_mps"] - 1.0),
            }
        )
    return out


def cap_comparison(case: dict) -> dict:
    n, N = case["n"], N_DEFAULT
    T = 2 * math.pi / n
    x0, x_t = case["x0"], propagate(case["slot"], case["t0"] + T, n)
    sph_min = sphere_min_a_max(x0, x_t, T, n, N, 0.01)
    mins = {
        "box": min_feasible_a_max(x0, x_t, T, n, N),
        "octahedron": min_feasible_a_max(x0, x_t, T, n, N, cap_shape="octahedron"),
        "sphere_slsqp": sph_min["a_max_mps2"],
        "box_cap_dt_T_over_N_minus_1": min_feasible_a_max(x0, x_t, T, n, N, cap_dt_s=T / (N - 1)),
    }
    totals = {}
    for shape in ("box", "octahedron"):
        tr = lp_transfer(x0, x_t, T, n, 0.01, 1.0, N, cap_shape=shape)
        totals[shape] = {"l1_mps": tr.total_dv_mps, "l2_mps": tr.l2_dv_mps}
    sph = l2_optimum(x0, x_t, T, n, 0.01, N, "sphere")
    totals["sphere_slsqp"] = {"l1_mps": sph["l1_mps"], "l2_mps": sph["l2_mps"]}
    return {
        "case": case["name"],
        "T_orbits": 1.0,
        "N": N,
        "min_feasible_a_max_mps2": mins,
        "min_feasible_a_max_sphere_success": sph_min["success"],
        "totals_at_a_max_0.01": totals,
        "box_extra_l1_vs_octahedron_pct": 100
        * (totals["box"]["l1_mps"] / totals["octahedron"]["l1_mps"] - 1.0),
        "note": "sphere = ||dv_k||_2 <= a_max*T/N (true vector cap), sphere_slsqp totals are the "
        "SLSQP L2 optimum under it; the default cap stays 'box'; the choice is made later.",
    }


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
    for case, a, o in ((cases[0], 0.01, 1.0), (cases[0], 0.1, 1.0), (cases[1], 0.002, 1.0)):
        tot = [lp_only(case, a, o, N)[0].total_dv_mps for N in N_SWEEP]
        conv.append(
            {
                "case": case["name"],
                "a_max_mps2": a,
                "T_orbits": o,
                "N": list(N_SWEEP),
                "l1_mps": tot,
                "rel_change_on_halving": [
                    abs(tot[i] - tot[i - 1]) / tot[i] for i in range(1, len(tot))
                ],
            }
        )

    def pick(case, a, o):
        return next(
            r for r in rows if r["case"] == case and r["a_max_mps2"] == a and r["T_orbits"] == o
        )

    r8 = pick("reference_8km_leader", 0.01, 1.0)
    r2 = pick("formation_2km_slot0_to_slot1", 0.002, 1.0)
    brief = [
        {
            "claim": "16.4 m/s at a_max 0.01, T = 1 orbit, 8 km leader",
            "claimed_mps": 16.4,
            "measured_l1_mps": r8["lp_total_l1_mps"],
            "measured_l2_mps": r8["lp_total_l2_mps"],
            "alt_start_t_replan_l1_mps": r8["lp_alt_start_t_replan_l1_mps"],
        },
        {
            "claim": "~4 m/s at a_max 0.002, 2 km formation (T = 1 orbit)",
            "claimed_mps": 4.0,
            "measured_l1_mps": r2["lp_total_l1_mps"],
            "measured_l2_mps": r2["lp_total_l2_mps"],
        },
    ]
    for b in brief:
        b["definition"] = (
            f"LP, N={N_DEFAULT}, k=1, T = 1 orbit, CW planning model, L1-optimal plan; compared "
            "as measured (no tuning of N, caps or T). L1 = LP objective, L2 = sum of impulse "
            "magnitudes."
        )
        m = b["measured_l1_mps"]
        b["difference_l1_mps"] = None if m is None else m - b["claimed_mps"]
    return {
        "command": command,
        "definitions": {
            "lp_total_l1_mps": "LP objective: sum over nodes and axes of |dv| (minimised)",
            "lp_total_l2_mps": "sum over nodes of ||dv_k||_2 (physical delta-v), same plan",
            "reference_start": "sat 0 logged state at the ASSIGNMENT tick (t_replan + dt = "
            "1208 s, after the first PD step: dv_already_spent_mps); the lp_alt_start_* "
            "columns use the REPLANNING-tick state (1206 s), the pure planning state",
            "pd_dv_l2_mps": "cubesat.pd.PDController dv_used (integral of ||u|| dt, an L2 "
            "figure) wn=0.01 zeta=1 a_max, dt 2 s, 4 orbits, moving slot",
            "two_impulse_*_l2_mps": "cubesat.dv_bound.two_impulse_dv, L2 sum; null when its "
            "singularity guard fires (T = k*pi/n: at 0.5 orbit the xy block of Phi_rv is "
            "regular, det = 16/n^2, but sin(nT)/n = 0 makes the z velocity term and so the "
            "full 3x3 singular; at 1 and 2 orbits the xy block is singular too)",
            "wall_time": "lp_runtime_ms_machine_dependent is wall time on the generating machine",
        },
        "reference_case": {
            k: (v.tolist() if isinstance(v, np.ndarray) else v)
            for k, v in ref.items()
            if k not in ("slot", "x0_t_replan")
        },
        "n_default": N_DEFAULT,
        "rows": rows,
        "convergence": conv,
        "brief_comparison": brief,
        "l2_optimum_check": l2_check(ref),
        "cap_shape_comparison": cap_comparison(ref),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--report", type=Path)
    ap.add_argument("--landing-fuzz", type=Path)
    ap.add_argument("--keepout-fuzz", type=Path)
    args = ap.parse_args(argv)
    jobs = [
        ("--report", args.report, build_report),
        ("--landing-fuzz", args.landing_fuzz, lambda cmd: {"command": cmd, **landing_fuzz()}),
        ("--keepout-fuzz", args.keepout_fuzz, lambda cmd: {"command": cmd, **keepout_fuzz()}),
    ]
    if not any(path for _, path, _ in jobs):
        ap.error("give at least one of --report, --landing-fuzz, --keepout-fuzz")
    for flag, path, fn in jobs:
        if path is None:
            continue
        rep = fn("uv run python -m cubesat.transfer_report " + flag + " " + path.as_posix())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
