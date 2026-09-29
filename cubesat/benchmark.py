"""P0 benchmark driver: all C(6,2)=15 two-failure pairs x 5 policies
(docs/ENDGAME_PLAN.md section 3, zero core diffs).

Command of record (75 runs, ~2-3 min wall):

    uv run python -m cubesat.benchmark --base data/scenarios/two_failure.json \
        --out data/eval/benchmark --report data/eval/benchmark_results.json \
        --policies do_nothing,even_split,greedy,hungarian,hungarian_keepout

Each (pair, policy) run replaces the base failure list with the demo's own
failure times (t = 1200/1500 s, mode DEAD) for the pair's sat ids, runs the pure
core cubesat.sim.run_scenario in-process (with the replan seam override for the
benchmark-side policies, saved and restored in try/finally), writes one JSONL
log per run in the exact cubesat.run byte format, and computes every metric
POST-HOC from the written log bytes. Committed artifacts: the report
(benchmark_results.json) and the manifest (per-log sha256 + exact argv) are
machine-written -- never hand-assembled (AGENTS.md invariant 1).

Determinism: lexicographic pair enumeration, fixed policy order, index
iteration only, no RNG, no wall clock inside anything that writes a log
(AGENTS.md invariant 2).
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import sys
from pathlib import Path

import cubesat.sim as sim_module
from cubesat.benchmark_policies import even_split_replan, hungarian_keepout_replan
from cubesat.scenario import Failure, FailureMode, Scenario

POLICY_ORDER = ("do_nothing", "even_split", "greedy", "hungarian", "hungarian_keepout")

# The demo's own failure times (two_failure.json:12-15) -- every pair is
# directly comparable to the committed G4 numbers (ENDGAME_PLAN 3.1).
FAILURE_TIMES = (1200.0, 1500.0)


def enumerate_pairs(n_sats: int) -> list[tuple[int, int]]:
    """C(n,2) pairs, lexicographic (deterministic, no sets)."""
    return list(itertools.combinations(range(n_sats), 2))


def scenario_for_pair(
    base: Scenario, pair: tuple[int, int], failure_times: tuple[float, float]
) -> Scenario:
    """Base scenario with exactly the pair's two DEAD failures at the demo times."""
    failures = [
        Failure(t=failure_times[0], sat_id=pair[0], mode=FailureMode.DEAD),
        Failure(t=failure_times[1], sat_id=pair[1], mode=FailureMode.DEAD),
    ]
    return base.model_copy(update={"name": f"bench_pair_{pair[0]}-{pair[1]}", "failures": failures})


def _scenario_for_policy(scenario: Scenario, policy: str) -> Scenario:
    if policy == "do_nothing":
        # Existing no-recovery baseline knob (scenario.py recovery_enabled).
        return scenario.model_copy(update={"recovery_enabled": False})
    if policy == "greedy":
        # Existing method toggle; the sweep keeps running, step 2 degrades.
        return scenario.model_copy(
            update={"allocation": scenario.allocation.model_copy(update={"method": "greedy"})}
        )
    return scenario


def _replanner_for(policy: str):
    if policy == "even_split":
        return even_split_replan
    if policy == "hungarian_keepout":
        return hungarian_keepout_replan
    return None


def run_one(scenario: Scenario, policy: str) -> list[dict]:
    """One in-process run; rebinds cubesat.sim.replan for the benchmark-side
    policies and RESTORES it in finally (sim resolves replan from its module
    globals at call time, so in-process siblings stay unpolluted)."""
    replanner = _replanner_for(policy)
    original = sim_module.replan
    if replanner is not None:
        sim_module.replan = replanner
    try:
        return sim_module.run_scenario(_scenario_for_policy(scenario, policy))
    finally:
        sim_module.replan = original


def _write_log(lines: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for line in lines:
            f.write(json.dumps(line, sort_keys=True) + "\n")


def metrics_from_log(
    path: Path, *, first_failure_t: float, dead_ids: list[int], duration_s: float
) -> dict:
    """Post-hoc metrics from the written log bytes (ENDGAME_PLAN 3.4)."""
    raw = path.read_bytes()
    lines = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
    ticks = [line for line in lines if line["state"] not in ("INIT", "SUMMARY")]
    summary = lines[-1]
    final_tick = ticks[-1]
    per_sat_dv = [0.0] * len(final_tick["sats"])
    for sat in final_tick["sats"]:
        per_sat_dv[sat["id"]] = float(sat["dv_used"])
    survivor_ids = [s["id"] for s in final_tick["sats"] if s["status"] == "NOMINAL"]
    min_sep = math.inf
    for line in ticks:
        if line["t"] < first_failure_t - 1e-9:
            continue
        pos = {s["id"]: s["r"] for s in line["sats"]}
        for dead in dead_ids:
            for survivor in survivor_ids:
                d = math.dist(pos[survivor], pos[dead])
                if d < min_sep:
                    min_sep = d
    pre = [line["coverage"] for line in ticks if line["t"] < first_failure_t - 1e-9]
    return {
        "coverage_mean_last_orbit": float(summary["coverage_mean_last_orbit"]),
        "total_dv_mps": float(sum(per_sat_dv)),
        "per_sat_dv_mps": per_sat_dv,
        "min_sep_survivor_dead_m": float(min_sep),
        "prefailure_mean_coverage": float(sum(pre) / len(pre)) if pre else 0.0,
        "n_ticks": len(ticks),
        "duration_s": duration_s,
    }


def run_benchmark(
    *,
    base: Scenario,
    pairs: list[tuple[int, int]],
    policies: list[str],
    out_dir: Path,
    report_path: Path,
    manifest_path: Path,
    command: str,
    failure_times: tuple[float, float] = FAILURE_TIMES,
) -> dict:
    """Run every (pair, policy), write the logs + report + manifest, return the report dict."""
    first_failure_t = min(failure_times)
    rows: list[dict] = []
    manifest_logs: dict[str, dict] = {}
    do_nothing_coverage: dict[tuple[int, int], float] = {}
    for pair in pairs:
        pair_scenario = scenario_for_pair(base, pair, failure_times)
        dead_ids = list(pair)
        for policy in policies:
            lines = run_one(pair_scenario, policy)
            filename = f"pair_{pair[0]}-{pair[1]}__{policy}.jsonl"
            log_path = out_dir / filename
            _write_log(lines, log_path)
            sha256 = hashlib.sha256(log_path.read_bytes()).hexdigest()
            manifest_logs[filename] = {"sha256": sha256, "pair": list(pair), "policy": policy}
            row = {
                "pair": list(pair),
                "policy": policy,
                "command": command,
                "log": filename,
                "log_sha256": sha256,
                **metrics_from_log(
                    log_path,
                    first_failure_t=first_failure_t,
                    dead_ids=dead_ids,
                    duration_s=pair_scenario.duration_s,
                ),
            }
            if policy == "do_nothing":
                do_nothing_coverage[pair] = row["coverage_mean_last_orbit"]
            rows.append(row)
    # gain vs do-nothing: same pair, same metric (ENDGAME_PLAN 3.4); only after
    # every do_nothing row exists -- fixed-order second pass, no dict-order use.
    for row in rows:
        baseline = do_nothing_coverage.get(tuple(row["pair"]))
        row["gain_vs_do_nothing_pts"] = (
            100.0 * (row["coverage_mean_last_orbit"] - baseline) if baseline is not None else None
        )
    policies_summary = _policies_summary(rows, policies)
    report = {
        "command": command,
        "failure_times_s": list(failure_times),
        "n_pairs": len(pairs),
        "policies": list(policies),
        "rows": rows,
        "policies_summary": policies_summary,
    }
    manifest = {"command": command, "logs": manifest_logs}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return report


def _policies_summary(rows: list[dict], policies: list[str]) -> dict[str, dict]:
    """Mean AND worst-case per policy over the pairs (ENDGAME_PLAN 3.4): the
    worst case is the slide number. Fixed policy order, rows in pair order."""
    summary: dict[str, dict] = {}
    for policy in policies:
        sel = [row for row in rows if row["policy"] == policy]
        coverages = [row["coverage_mean_last_orbit"] for row in sel]
        totals = [row["total_dv_mps"] for row in sel]
        worst_per_sat = [max(row["per_sat_dv_mps"]) for row in sel]
        seps = [row["min_sep_survivor_dead_m"] for row in sel]
        gains = [
            row["gain_vs_do_nothing_pts"]
            for row in sel
            if row["gain_vs_do_nothing_pts"] is not None
        ]
        summary[policy] = {
            "mean_coverage_retained": sum(coverages) / len(coverages),
            "worst_coverage_retained": min(coverages),
            "mean_total_dv_mps": sum(totals) / len(totals),
            "worst_per_sat_dv_mps": max(worst_per_sat),
            "mean_min_sep_survivor_dead_m": sum(seps) / len(seps),
            "worst_min_sep_survivor_dead_m": min(seps),
            "mean_gain_vs_do_nothing_pts": (sum(gains) / len(gains)) if gains else None,
        }
    return summary


def _run_keepout_report(args) -> int:
    """P2 dispatch (ENDGAME_PLAN 5): post-hoc analysis of written log bytes --
    no sim core involvement. Reads the logs named on the command line, writes
    the keepout section into --report (machine-written, invariant 1)."""
    import json

    from cubesat.hcw import mean_motion
    from cubesat.keepout import keepout_report

    base = Scenario.model_validate_json(args.base.read_text(encoding="utf-8"))
    log_paths: dict[str, list[Path]] = {}
    for spec in args.keepout_logs.split(","):
        policy, pattern = spec.split("=")
        log_paths[policy] = sorted(args.out.glob(pattern))  # glob -> sorted: index order
    if not log_paths:
        raise SystemExit("--keepout-logs matched no logs")
    report = keepout_report(
        log_paths=log_paths,
        n=mean_motion(base.chief.altitude_km * 1000.0),
        tick_dt=base.dt_s,
        keepout_radius_m=base.allocation.min_sep_km * 1000.0,
        command="uv run python -m cubesat.benchmark " + " ".join(sys.argv[1:]),
    )
    if args.report.exists():
        merged = json.loads(args.report.read_text(encoding="utf-8"))
    else:
        merged = {}
    merged["keepout"] = report
    args.report.write_text(json.dumps(merged, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    n_entries = sum(len(v) for v in report["per_policy"].values())
    print(f"wrote keepout section into {args.report} ({n_entries} dead-sat entries)")
    comp = report["keepout_binding_comparison"]
    print(f"decision: {comp['decision']} -- {comp['decision_text']}")
    return 0


def _run_pareto(args) -> int:
    """P1 dispatch (ENDGAME_PLAN 4): the 12-point w2 x dv_budget grid through
    the P0 driver, hungarian, all 15 pairs. Machine-writes the report JSON,
    pareto_points.csv and the SVG curve (no matplotlib)."""
    from cubesat.pareto import run_pareto, write_csv, write_svg

    base = Scenario.model_validate_json(args.base.read_text(encoding="utf-8"))
    p0_dir = args.p0_dir
    p0_manifest = args.p0_manifest or p0_dir.with_name("benchmark_manifest.json")
    command = "uv run python -m cubesat.benchmark " + " ".join(sys.argv[1:])
    report = run_pareto(
        base=base,
        out_dir=args.out,
        p0_dir=p0_dir,
        p0_manifest_path=p0_manifest,
        command=command,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    write_csv(report, args.csv)
    write_svg(report, args.svg)
    dec = report["degenerate_front"]
    print(f"wrote {args.report} ({len(report['rows'])} grid points x {report['n_pairs']} pairs)")
    print(f"wrote {args.csv} and {args.svg}")
    print(f"pareto front: {len(report['pareto_front'])} points")
    print(f"decision: {dec['decision']} -- {dec['decision_text']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cubesat.benchmark", description="P0 exhaustive recovery benchmark"
    )
    parser.add_argument(
        "--mode", choices=("benchmark", "keepout-report", "pareto"), default="benchmark",
        help="benchmark: run the P0 sweep; keepout-report: P2 post-hoc log analysis; "
        "pareto: P1 w2 x dv_budget sweep",
    )
    parser.add_argument("--base", required=True, type=Path, help="base scenario JSON")
    parser.add_argument("--out", required=True, type=Path, help="directory for per-run JSONL logs")
    parser.add_argument(
        "--report", required=True, type=Path, help="path for benchmark_results.json"
    )
    parser.add_argument(
        "--manifest", type=Path, default=None,
        help="path for benchmark_manifest.json (default: alongside --report)",
    )
    parser.add_argument(
        "--policies",
        default=",".join(POLICY_ORDER),
        help="comma-separated subset of " + ",".join(POLICY_ORDER),
    )
    parser.add_argument(
        "--keepout-logs",
        default="do_nothing=pair_*__do_nothing.jsonl,hungarian=pair_*__hungarian.jsonl,"
        "hungarian_keepout=pair_*__hungarian_keepout.jsonl",
        help="keepout-report mode: comma-separated policy=glob log specs under --out",
    )
    parser.add_argument(
        "--p0-dir", type=Path, default=Path("data/eval/benchmark"),
        help="pareto mode: P0 log dir for the coinciding-point log reuse",
    )
    parser.add_argument(
        "--p0-manifest", type=Path, default=None,
        help="pareto mode: P0 manifest path (default: alongside --p0-dir)",
    )
    parser.add_argument(
        "--csv", type=Path, default=None,
        help="pareto mode: pareto_points.csv path (default: alongside --report)",
    )
    parser.add_argument(
        "--svg", type=Path, default=None,
        help="pareto mode: SVG curve path (default: alongside --report)",
    )
    args = parser.parse_args(argv)
    if args.mode == "keepout-report":
        return _run_keepout_report(args)
    if args.mode == "pareto":
        if args.csv is None:
            args.csv = args.report.with_name("pareto_points.csv")
        if args.svg is None:
            args.svg = args.report.with_name("pareto_curve.svg")
        return _run_pareto(args)
    policies = [p for p in args.policies.split(",") if p]
    unknown = [p for p in policies if p not in POLICY_ORDER]
    if unknown:
        parser.error(f"unknown policies: {unknown}")
    command = "uv run python -m cubesat.benchmark " + " ".join(sys.argv[1:])
    base = Scenario.model_validate_json(args.base.read_text(encoding="utf-8"))
    pairs = enumerate_pairs(base.n_sats)
    manifest_path = args.manifest or args.report.with_name("benchmark_manifest.json")
    report = run_benchmark(
        base=base,
        pairs=pairs,
        policies=policies,
        out_dir=args.out,
        report_path=args.report,
        manifest_path=manifest_path,
        command=command,
    )
    print(
        f"wrote {args.report} ({len(report['rows'])} rows, "
        f"{len(pairs)} pairs x {len(policies)} policies)"
    )
    print(f"wrote {manifest_path} ({len(report['rows'])} log sha256s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
