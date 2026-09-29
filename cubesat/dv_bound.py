"""Two-impulse CW transfer Δv lower bounds for the P0 hungarian runs
(docs/ENDGAME_PLAN.md section 2 Δv-scrutiny resolution method, zero core diff).

Command of record (post-hoc on the committed P0 hungarian logs):

    uv run python -m cubesat.dv_bound --base data/scenarios/two_failure.json \
        --p0-dir data/eval/benchmark --report data/eval/dv_lower_bounds.json \
        --csv data/eval/dv_lower_bounds.csv

For every replan episode of every pair's hungarian log this module reads the
survivors' ACTUAL start states (the REPLANNING-state tick line), the ACTUAL
target slots (the ASSIGNMENT event's formation amp/phase0 + slot indices,
reconstructed with cubesat.hcw.slot_initial_state exactly as
allocate.select_formation builds them), and the ACTUAL transfer window (replan
tick -> the episode's end: the next FAILURE_DETECTED tick if the episode was
interrupted by the second failure, else the RECOVERED tick). It then solves the
fixed-time two-impulse CW transfer from the hcw STM velocity block:

    Phi_rv(t) @ v1 = r_target(t_end) - Phi_rr(t) @ r0      (first impulse)
    dv2 = || v_target(t_end) - (Phi_vr @ r0 + Phi_vv @ v1) ||  (arrival match)

dv1 + dv2 is the unique impulsive transfer for that (start, target, time) --
the physics lower bound the PD controller is measured against. A large ratio
controller_dv / bound means controller inefficiency, not physics.

Singularity guard (ENDGAME_PLAN section 2): the velocity-row terms pass through
zero at t = k*pi/n and the Phi_rv xy-block determinant vanishes at t = 2*k*pi/n;
every solved transfer records |sin(n*t)|, the scaled determinant and the
distance to the nearest k*pi/n in seconds, and is flagged singular if either
collapses (no bound is silently produced from a singular solve).

Determinism: index iteration only, no RNG, no wall clock (AGENTS.md invariant 2).
Units SI (invariant 3); LVLH (invariant 4). Machine-written report + CSV
(invariant 1): every row carries the command of record and its log sha256.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

from cubesat.hcw import mean_motion, propagate, slot_initial_state, stm

SIN_EPS = 1e-9  # |sin(n*dt)| below this => z-channel impulse ill-defined
DET_EPS = 1e-12  # scaled Phi_rv xy-block determinant below this => singular


def two_impulse_dv(
    x0: np.ndarray, slot: np.ndarray, t0: float, t_end: float, n: float
) -> dict:
    """Fixed-time two-impulse CW transfer Δv from start state x0 at t0 to the
    slot trajectory (state at t_end), via the hcw STM blocks. SI, LVLH."""
    dt = t_end - t0
    Phi = stm(dt, n)
    rr, rv = Phi[:3, :3], Phi[:3, 3:]
    vr, vv = Phi[3:, :3], Phi[3:, 3:]
    x0 = np.asarray(x0, dtype=float)
    r0, v0 = x0[:3], x0[3:]
    target = propagate(slot, t_end, n)
    r_f, v_f = target[:3], target[3:]
    v1 = np.linalg.solve(rv, r_f - rr @ r0)
    dv1 = float(np.linalg.norm(v1 - v0))
    v_arr = vr @ r0 + vv @ v1
    dv2 = float(np.linalg.norm(v_f - v_arr))
    # Singularity margins (ENDGAME_PLAN section 2): t = k*pi/n kills the
    # velocity rows and the z impulse; t = 2*k*pi/n also kills the xy solve.
    s = math.sin(n * dt)
    det_xy_scaled = float((rv[0, 0] * rv[1, 1] - rv[0, 1] * rv[1, 0]) * n * n)
    phase = n * dt
    k = round(phase / math.pi)
    dist_to_singular_s = abs(phase - k * math.pi) / n
    singular = abs(s) < SIN_EPS or abs(det_xy_scaled) < DET_EPS
    return {
        "dv1_mps": dv1,
        "dv2_mps": dv2,
        "dv_total_mps": dv1 + dv2,
        "transfer_time_s": dt,
        "sin_nt": s,
        "det_xy_scaled": det_xy_scaled,
        "dist_to_singular_s": dist_to_singular_s,
        "singular": singular,
    }


def parse_episodes(lines: list[dict]) -> list[dict]:
    """Replan episodes from one JSONL log: (t_replan, start sats, ASSIGNMENT
    payload, t_end). The replanner runs between steps of the tick whose line
    carries the STATE->REPLANNING event (sim.py:215-247): that tick's t and
    sats[] are the transfer start. The ASSIGNMENT event rides the NEXT tick's
    line (one event pops per tick, sim.py:203-204). Episode end = the next
    FAILURE_DETECTED event tick if that comes before the episode's RECOVERED,
    else the RECOVERED tick, else the log end (flagged). Index order only --
    events pop FIFO, so file order is event order."""
    events = [(line["t"], line["event"]) for line in lines if line.get("event")]
    replan_sats = {
        line["t"]: line["sats"] for line in lines if line["state"] == "REPLANNING"
    }
    dv_at = {
        line["t"]: {int(s["id"]): float(s["dv_used"]) for s in line["sats"]}
        for line in lines
        if line["state"] not in ("INIT", "SUMMARY")
    }
    last_tick_t = max(line["t"] for line in lines)
    episodes: list[dict] = []
    last_state_t: float | None = None
    for idx, (t, ev) in enumerate(events):
        if ev["type"] == "STATE" and ev["payload"].get("to") == "REPLANNING":
            last_state_t = t
        elif ev["type"] == "ASSIGNMENT":
            assert last_state_t is not None, "ASSIGNMENT without STATE->REPLANNING"
            t_replan = last_state_t
            # Episode end: scan events after this ASSIGNMENT in file order.
            t_end = None
            for t2, ev2 in events[idx + 1 :]:
                if ev2["type"] == "FAILURE_DETECTED":
                    t_end = t2
                    break
                if ev2["type"] == "STATE" and ev2["payload"].get("to") == "RECOVERED":
                    t_end = t2
                    break
            truncated = t_end is None
            if t_end is None:
                t_end = last_tick_t
            episodes.append(
                {
                    "t_replan": t_replan,
                    "start_sats": replan_sats[t_replan],
                    "assignment": ev["payload"],
                    "t_end": t_end,
                    "truncated": truncated,
                    # controller dv_used at the window edges: the per-sat spend
                    # within the episode is the difference (log-derived).
                    "dv_at_replan": dv_at[t_replan],
                    "dv_at_end": dv_at[t_end],
                }
            )
    return episodes


def episode_bounds(episode: dict, n: float) -> dict:
    """Two-impulse bound per survivor of one episode, from the episode's start
    states and ASSIGNMENT payload (formation amp/phi0 + slot indices, slots
    built exactly as allocate.select_formation: slot_initial_state(amp, amp,
    phi0 + 2*pi*j/k, n), k = survivor count)."""
    assigns = sorted(episode["assignment"]["assignments"], key=lambda a: a["sat_id"])
    k = len(assigns)
    amp = float(episode["assignment"]["formation"]["radial_amp_m"])
    phi0 = float(episode["assignment"]["formation"]["phase_offset_rad"])
    states_by_id = {int(s["id"]): s for s in episode["start_sats"]}
    per_sat = []
    for a in assigns:
        sat_id, slot_index = int(a["sat_id"]), int(a["slot_index"])
        assert 0 <= slot_index < k
        sat = states_by_id[sat_id]
        assert sat["status"] == "NOMINAL"
        slot = slot_initial_state(amp, amp, phi0 + 2.0 * math.pi * slot_index / k, n)
        res = two_impulse_dv(
            np.array([*sat["r"], *sat["v"]]), slot, episode["t_replan"], episode["t_end"], n
        )
        spend = episode["dv_at_end"][sat_id] - episode["dv_at_replan"][sat_id]
        per_sat.append(
            {
                "sat_id": sat_id,
                "slot_index": slot_index,
                "controller_dv_in_window_mps": spend,
                "ratio_in_window": spend / res["dv_total_mps"] if res["dv_total_mps"] > 0 else None,
                **res,
            }
        )
    return {
        "t_replan": episode["t_replan"],
        "t_end": episode["t_end"],
        "truncated_end": episode["truncated"],
        "transfer_time_s": episode["t_end"] - episode["t_replan"],
        "n_survivors": k,
        "formation_amp_m": amp,
        "formation_phase0_rad": phi0,
        "bound_total_mps": float(sum(e["dv_total_mps"] for e in per_sat)),
        "controller_spend_total_mps": float(sum(e["controller_dv_in_window_mps"] for e in per_sat)),
        "per_sat": per_sat,
    }


def pair_bounds(log_path: Path, n: float) -> dict:
    """Per-pair bounds + controller dv from one hungarian log."""
    lines = [json.loads(line) for line in log_path.read_bytes().decode("utf-8").splitlines()]
    episodes = [episode_bounds(ep, n) for ep in parse_episodes(lines)]
    ticks = [line for line in lines if line["state"] not in ("INIT", "SUMMARY")]
    final = ticks[-1]
    controller = {int(s["id"]): float(s["dv_used"]) for s in final["sats"]}
    bound = {sat_id: 0.0 for sat_id in controller}
    for ep in episodes:
        for entry in ep["per_sat"]:
            bound[entry["sat_id"]] += entry["dv_total_mps"]
    worst_id = max(sorted(controller), key=lambda i: controller[i])
    worst_bound = bound[worst_id]
    # The COMPLETED transfer = the final episode (ends at RECOVERED, not at an
    # interruption): its window is the actual transfer the controller finished,
    # so spend-vs-bound inside it is the apples-to-apples efficiency figure.
    # Earlier episodes were interrupted by the second failure before any
    # transfer completed; their two-impulse bound is the cost of COMPLETING the
    # commanded transfer within the truncated window, which a continuous
    # partial burn need not pay -- so whole-run totals can sit below it.
    last_ep = episodes[-1]
    final_bound = last_ep["bound_total_mps"]
    final_spend = last_ep["controller_spend_total_mps"]
    final_per_sat = {
        str(e["sat_id"]): {
            "controller_dv_in_window_mps": e["controller_dv_in_window_mps"],
            "bound_mps": e["dv_total_mps"],
            "ratio": e["ratio_in_window"],
        }
        for e in last_ep["per_sat"]
    }
    return {
        "episodes": episodes,
        "per_sat_controller_dv_mps": {str(i): controller[i] for i in sorted(controller)},
        "per_sat_bound_mps": {str(i): bound[i] for i in sorted(bound)},
        "controller_total_mps": float(sum(controller.values())),
        "bound_total_mps": float(sum(bound.values())),
        "ratio_total": float(sum(controller.values())) / float(sum(bound.values())),
        "worst_sat": {
            "sat_id": worst_id,
            "controller_dv_mps": controller[worst_id],
            "bound_mps": worst_bound,
            "ratio": controller[worst_id] / worst_bound if worst_bound > 0 else None,
        },
        "completed_episode": {
            "t_replan": last_ep["t_replan"],
            "t_end": last_ep["t_end"],
            "transfer_time_s": last_ep["transfer_time_s"],
            "controller_spend_total_mps": final_spend,
            "bound_total_mps": final_bound,
            "ratio_total": final_spend / final_bound if final_bound > 0 else None,
            "per_sat": final_per_sat,
        },
    }


def run_dv_bound(
    *, base_scenario_path: Path, p0_dir: Path, policy: str, command: str, n: float
) -> dict:
    """Analyze every pair's log for one policy; return the report dict."""
    names = sorted(p0_dir.glob(f"pair_*-*__{policy}.jsonl"))  # sorted: index order
    if not names:
        raise SystemExit(f"no {policy} logs under {p0_dir}")
    pairs = []
    for path in names:
        stem = path.name.split("__")[0]  # pair_<i>-<j>
        ids = stem.removeprefix("pair_").split("-")
        res = pair_bounds(path, n)
        singular = [
            entry
            for ep in res["episodes"]
            for entry in ep["per_sat"]
            if entry["singular"]
        ]
        pairs.append(
            {
                "pair": [int(ids[0]), int(ids[1])],
                "policy": policy,
                "log": path.name,
                "log_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "command": command,
                "n_episodes": len(res["episodes"]),
                "transfer_windows_s": [ep["transfer_time_s"] for ep in res["episodes"]],
                "min_dist_to_singular_s": min(
                    entry["dist_to_singular_s"] for ep in res["episodes"] for entry in ep["per_sat"]
                ),
                "n_singular_solves": len(singular),
                "episodes": res["episodes"],
                "per_sat_controller_dv_mps": res["per_sat_controller_dv_mps"],
                "per_sat_bound_mps": res["per_sat_bound_mps"],
                "controller_total_mps": res["controller_total_mps"],
                "bound_total_mps": res["bound_total_mps"],
                "ratio_total": res["ratio_total"],
                "worst_sat": res["worst_sat"],
                "completed_episode": res["completed_episode"],
            }
        )
    pairs.sort(key=lambda row: tuple(row["pair"]))
    # The G4 headline number: per-sat dv_used 193.68 m/s (GATES.md G4 row) is
    # sat 0's whole-run total, measured identical (1e-4 m/s) in SEVEN P0 pairs:
    # (1,2) (1,3) (1,4) (1,5) (3,4) (3,5) (4,5). Sat 0 survives in each of them
    # (it dies only in the (0,x) rows); in (4,5) it is not the worst sat (sat 2
    # spends 251.24 m/s), so the worst-sat selector below matches six rows and
    # lands on (1,2) -- which is exactly two_failure.json (sat 1 fails t=1200,
    # sat 2 fails t=1500). The COMPLETED transfer is the final episode; ratio
    # there is the apples-to-apples figure.
    g4_rows = [
        row for row in pairs if abs(row["worst_sat"]["controller_dv_mps"] - 193.68) < 0.01
    ]
    assert g4_rows, "no P0 pair reproduces the G4 193.68 m/s per-sat figure"
    g4 = g4_rows[0]
    g4_sat = g4["worst_sat"]["sat_id"]
    g4_final = g4["completed_episode"]["per_sat"][str(g4_sat)]
    mean_ratio = sum(row["ratio_total"] for row in pairs) / len(pairs)
    # Worst completed-transfer per-sat ratio over all pairs/sats.
    worst_final = None
    for row in pairs:
        for sat_id_str, e in sorted(row["completed_episode"]["per_sat"].items()):
            if e["ratio"] is None:
                continue
            if worst_final is None or e["ratio"] > worst_final["ratio"]:
                worst_final = {
                    "pair": row["pair"],
                    "sat_id": int(sat_id_str),
                    "controller_dv_in_window_mps": e["controller_dv_in_window_mps"],
                    "bound_mps": e["bound_mps"],
                    "ratio": e["ratio"],
                }
    return {
        "command": command,
        "policy": policy,
        "method": (
            "two-impulse CW transfer from the hcw STM velocity block (cubesat.hcw.stm), "
            "same start state (REPLANNING tick), target slot (ASSIGNMENT event, "
            "slot_initial_state reconstruction of allocate.select_formation) and transfer "
            "time (replan tick -> next FAILURE_DETECTED or RECOVERED tick) as the actual "
            "run; ENDGAME_PLAN section 2 resolution method, post-hoc, zero core diff"
        ),
        "completed_episode_note": (
            "each pair replans twice (one ASSIGNMENT per failure); the FIRST episode is "
            "interrupted by the second failure detection before any transfer completes, so "
            "its two-impulse bound is the cost of COMPLETING the commanded transfer within "
            "the truncated window -- a continuous partial burn need not pay that, which is "
            "why whole-run totals can sit below it (ratio_total < 1). The FINAL episode ends "
            "at RECOVERED: same start state, target slot and transfer time as an actual "
            "completed transfer, so its spend-vs-bound ratio is the apples-to-apples figure."
        ),
        "singularity_guard": "t = k*pi/n (velocity rows) and t = 2*k*pi/n (Phi_rv xy determinant); "
        "every solve records sin_nt, det_xy_scaled and dist_to_singular_s",
        "pairs": pairs,
        "n_singular_solves_total": sum(row["n_singular_solves"] for row in pairs),
        "mean_ratio_total": mean_ratio,
        "max_ratio_total": max(row["ratio_total"] for row in pairs),
        "mean_completed_ratio_total": sum(
            row["completed_episode"]["ratio_total"] for row in pairs
        ) / len(pairs),
        "worst_completed_per_sat": worst_final,
        "headline": {
            "definition": "the G4 headline per-satellite dv (193.68 m/s, GATES.md G4 row, "
            "reproduced as the worst sat's dv_used in P0 pairs (1,2) (1,3) (1,4) (1,5) "
            "(3,4) (3,5), and as sat 0's total also in (4,5) where sat 2 is the worst "
            "sat) divided "
            "by the same satellite's two-impulse CW bound for its ACTUAL COMPLETED transfer "
            "(final episode: start state at the final replan tick, assigned slot, window "
            "replan tick -> RECOVERED tick)",
            "pair": g4["pair"],
            "sat_id": g4_sat,
            "controller_dv_used_total_mps": g4["worst_sat"]["controller_dv_mps"],
            "controller_dv_completed_window_mps": g4_final["controller_dv_in_window_mps"],
            "bound_completed_window_mps": g4_final["bound_mps"],
            "ratio_completed": g4_final["ratio"],
            "bound_total_both_episodes_mps": g4["worst_sat"]["bound_mps"],
            "ratio_total_both_episodes": g4["worst_sat"]["ratio"],
        },
        "g4_headline_pair_1_2": {
            "note": "two_failure.json == P0 pair (1,2) (failures: sat 1 at t=1200, sat 2 at "
            "t=1500; GATES.md P0 row's pair_1-2__hungarian.jsonl is the same run); its worst "
            "sat and totals, for direct comparison with the G4 single-run ledger row "
            "(GATES.md G4: per-sat dv 0-193.68 m/s at a_max = 0.1)",
            "pair": g4["pair"],
            "sat_id": g4["worst_sat"]["sat_id"],
            "controller_worst_per_sat_mps": g4["worst_sat"]["controller_dv_mps"],
            "bound_mps": g4["worst_sat"]["bound_mps"],
            "ratio": g4["worst_sat"]["ratio"],
            "controller_total_mps": g4["controller_total_mps"],
            "bound_total_mps": g4["bound_total_mps"],
            "ratio_total": g4["ratio_total"],
            "completed_episode": g4["completed_episode"],
        },
    }


def write_csv(report: dict, path: Path) -> None:
    cols = (
        "pair","policy","controller_total_mps","bound_total_mps","ratio_total",
        "completed_ratio_total","worst_sat_id","worst_sat_controller_dv_mps",
        "worst_sat_bound_mps","worst_sat_ratio","min_transfer_time_s",
        "max_transfer_time_s","min_dist_to_singular_s",
    )
    lines = [",".join(cols)]
    for row in report["pairs"]:
        windows = row["transfer_windows_s"]
        ws = row["worst_sat"]
        lines.append(
            ",".join(
                [
                    f"{row['pair'][0]}-{row['pair'][1]}",
                    row["policy"],
                    repr(row["controller_total_mps"]),
                    repr(row["bound_total_mps"]),
                    repr(row["ratio_total"]),
                    repr(row["completed_episode"]["ratio_total"]),
                    str(ws["sat_id"]),
                    repr(ws["controller_dv_mps"]),
                    repr(ws["bound_mps"]),
                    repr(ws["ratio"]),
                    repr(min(windows)),
                    repr(max(windows)),
                    repr(row["min_dist_to_singular_s"]),
                ]
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cubesat.dv_bound",
        description="Two-impulse CW Δv lower bounds vs the measured controller dv",
    )
    parser.add_argument("--base", required=True, type=Path, help="base scenario JSON")
    parser.add_argument("--p0-dir", type=Path, default=Path("data/eval/benchmark"))
    parser.add_argument("--policy", default="hungarian", help="P0 policy logs to analyze")
    parser.add_argument("--report", type=Path, default=Path("data/eval/dv_lower_bounds.json"))
    parser.add_argument("--csv", type=Path, default=Path("data/eval/dv_lower_bounds.csv"))
    args = parser.parse_args(argv)
    command = "uv run python -m cubesat.dv_bound " + " ".join(sys.argv[1:])
    base = json.loads(args.base.read_text(encoding="utf-8"))
    n = mean_motion(base["chief"]["altitude_km"] * 1000.0)
    report = run_dv_bound(
        base_scenario_path=args.base, p0_dir=args.p0_dir, policy=args.policy,
        command=command, n=n,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    write_csv(report, args.csv)
    h = report["headline"]
    print(f"wrote {args.report} and {args.csv} ({len(report['pairs'])} pairs)")
    print(
        f"headline: G4-scale per-sat controller dv {h['controller_dv_used_total_mps']:.2f} m/s "
        f"(pair {h['pair']}, sat {h['sat_id']}); completed-transfer spend "
        f"{h['controller_dv_completed_window_mps']:.2f} m/s vs two-impulse bound "
        f"{h['bound_completed_window_mps']:.2f} m/s -> ratio {h['ratio_completed']:.2f}x"
    )
    print(
        f"mean whole-run total-dv ratio {report['mean_ratio_total']:.2f}x "
        f"(interrupted-episode caveat), mean completed-episode ratio "
        f"{report['mean_completed_ratio_total']:.2f}x; "
        f"singular solves: {report['n_singular_solves_total']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
