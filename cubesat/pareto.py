"""P1 fuel-vs-coverage Pareto sweep (docs/ENDGAME_PLAN.md section 4, zero core
diff). Sweeps allocation.w2 in {0.1, 0.5, 1.0, 2.0} at fixed w1=1.0 / w3=2.0
crossed with allocation.dv_budget_mps in {50, 100, 200} m/s = 12 grid points,
each through the P0 driver with --policies hungarian over all 15 pairs.

The grid point that coincides with the P0 benchmark's own configuration
(w2 = 0.5, dv_budget = the base scenario's committed value, 200.0 m/s in
two_failure.json) REUSES the committed P0 hungarian logs, verified by sha256
against benchmark_manifest.json -- it is never re-run.

Outputs (machine-written, AGENTS.md invariant 1): data/eval/pareto_points.csv
(one row per grid point, per-point command included) and the coverage-vs-dv
curve rendered by a stdlib SVG writer (no matplotlib, ENDGAME_PLAN 6).

Degenerate-front policy (user pre-decision Q4): the measured curve ships
as-is whether or not the front is degenerate -- a flat front is itself a
measurement ("dv is set by the formation, not the assignment"). The decision
is recorded in the report, never smoothed over.

Determinism: fixed grid order, index iteration only, no RNG, no wall clock
inside anything that writes a log (AGENTS.md invariant 2).
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path

from cubesat.benchmark import (
    FAILURE_TIMES,
    enumerate_pairs,
    metrics_from_log,
    run_one,
    scenario_for_pair,
)
from cubesat.scenario import Scenario

W1_FIXED = 1.0
W3_FIXED = 2.0
W2_GRID = (0.1, 0.5, 1.0, 2.0)
DV_BUDGET_GRID = (50.0, 100.0, 200.0)


def enumerate_grid_points() -> list[tuple[float, float]]:
    """The 12-point grid, w2 outer / dv_budget inner (index order)."""
    return [(w2, dv) for w2 in W2_GRID for dv in DV_BUDGET_GRID]


def point_tag(w2: float, dv_budget: float) -> str:
    return f"w2_{w2}_dv_{dv_budget:g}"


def scenario_for_point(base: Scenario, w2: float, dv_budget: float) -> Scenario:
    """Base scenario with the point's allocation weights (ENDGAME_PLAN 4)."""
    return base.model_copy(
        update={
            "allocation": base.allocation.model_copy(
                update={
                    "w1": W1_FIXED,
                    "w2": w2,
                    "w3": W3_FIXED,
                    "dv_budget_mps": dv_budget,
                }
            )
        }
    )


def _reuse_p0_logs(
    p0_dir: Path, p0_manifest_path: Path
) -> dict[str, dict] | None:
    """P0 hungarian logs + sha256s if the committed manifest is present and
    every hungarian log matches its recorded sha256; else None (fall back to
    re-running the coinciding point)."""
    if not p0_dir.is_dir() or not p0_manifest_path.is_file():
        return None
    manifest = json.loads(p0_manifest_path.read_text(encoding="utf-8"))
    reused: dict[str, dict] = {}
    for name, entry in manifest["logs"].items():
        if entry["policy"] != "hungarian":
            continue
        path = p0_dir / name
        if not path.is_file():
            return None
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if sha != entry["sha256"]:
            return None
        reused[name] = {"sha256": sha, "pair": entry["pair"], "path": path}
    return reused or None


def run_pareto(
    *,
    base: Scenario,
    out_dir: Path,
    p0_dir: Path,
    p0_manifest_path: Path,
    command: str,
) -> dict:
    """Run the 12-point grid over all 15 pairs; return the report dict. Logs
    land in out_dir; the report (rows + aggregates + degenerate-front decision)
    is returned for the caller to write."""
    pairs = enumerate_pairs(base.n_sats)
    first_failure_t = min(FAILURE_TIMES)
    p0_logs = _reuse_p0_logs(p0_dir, p0_manifest_path)
    p0_point = (base.allocation.w2, base.allocation.dv_budget_mps)
    # Provenance pointer, not a copied command string (Mimosa finding resolved
    # 2026-09-29): the P0 command of record lives exactly once, in
    # benchmark_manifest.json next to the sha256 that pins it.
    reuse_pointer = (
        f"reused point: per-pair logs {p0_dir.as_posix()}/pair_*__hungarian.jsonl; "
        f"command of record: {p0_manifest_path.as_posix()} (sha256-pinned)"
    )
    rows: list[dict] = []
    for w2, dv_budget in enumerate_grid_points():
        reused_point = p0_logs is not None and (w2, dv_budget) == p0_point
        tag = point_tag(w2, dv_budget)
        variant = scenario_for_point(base, w2, dv_budget)
        per_pair: list[dict] = []
        for pair in pairs:
            filename = f"pair_{pair[0]}-{pair[1]}__hungarian__{tag}.jsonl"
            log_path = out_dir / filename
            if reused_point:
                p0_name = f"pair_{pair[0]}-{pair[1]}__hungarian.jsonl"
                log_path.write_bytes(p0_logs[p0_name]["path"].read_bytes())
                point_command = reuse_pointer
                reused_from = f"{p0_dir.as_posix()}/{p0_name}"
            else:
                try:
                    lines = run_one(scenario_for_pair(variant, pair, FAILURE_TIMES), "hungarian")
                except RuntimeError as exc:
                    if "no feasible survivor formation" not in str(exc):
                        raise
                    # Measured infeasibility: the dv_budget filter (allocate
                    # step-1 reachability) admits no formation in the sweep
                    # grid for this pair. Recorded as such, never silently
                    # dropped -- unmeasured stays unmeasured (invariant 1).
                    per_pair.append(
                        {
                            "pair": list(pair),
                            "log": None,
                            "log_sha256": None,
                            "reused_from": None,
                            "infeasible": True,
                            "infeasibility_reason": str(exc),
                            "coverage_mean_last_orbit": None,
                            "total_dv_mps": None,
                            "per_sat_dv_mps": None,
                            "min_sep_survivor_dead_m": None,
                            "prefailure_mean_coverage": None,
                            "n_ticks": None,
                            "duration_s": variant.duration_s,
                        }
                    )
                    continue
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with log_path.open("w", encoding="utf-8", newline="\n") as f:
                    for line in lines:
                        f.write(json.dumps(line, sort_keys=True) + "\n")
                point_command = command
                reused_from = None
            sha256 = hashlib.sha256(log_path.read_bytes()).hexdigest()
            metrics = metrics_from_log(
                log_path,
                first_failure_t=first_failure_t,
                dead_ids=list(pair),
                duration_s=variant.duration_s,
            )
            per_pair.append(
                {
                    "pair": list(pair),
                    "log": filename,
                    "log_sha256": sha256,
                    "reused_from": reused_from,
                    **metrics,
                }
            )
        feasible = [p for p in per_pair if not p.get("infeasible")]
        n_infeasible = len(per_pair) - len(feasible)
        if feasible:
            coverages = [p["coverage_mean_last_orbit"] for p in feasible]
            totals = [p["total_dv_mps"] for p in feasible]
            mean_coverage = sum(coverages) / len(coverages)
            worst_coverage = min(coverages)
            mean_total_dv = sum(totals) / len(totals)
            worst_per_sat = max(max(p["per_sat_dv_mps"]) for p in feasible)
        else:
            mean_coverage = worst_coverage = None
            mean_total_dv = worst_per_sat = None
        rows.append(
            {
                "w2": w2,
                "dv_budget_mps": dv_budget,
                "mean_coverage": mean_coverage,
                "worst_coverage": worst_coverage,
                "mean_total_dv_mps": mean_total_dv,
                "worst_per_sat_dv_mps": worst_per_sat,
                "n_feasible_pairs": len(feasible),
                "n_infeasible_pairs": n_infeasible,
                "command": point_command,
                "reused_p0_logs": reused_point,
                "per_pair": per_pair,
            }
        )
    report = {
        "command": command,
        "w1_fixed": W1_FIXED,
        "w3_fixed": W3_FIXED,
        "w2_grid": list(W2_GRID),
        "dv_budget_grid_mps": list(DV_BUDGET_GRID),
        "n_pairs": len(pairs),
        "p0_point": {
            "w2": p0_point[0],
            "dv_budget_mps": p0_point[1],
            "reused": p0_logs is not None,
        },
        "rows": rows,
    }
    report["pareto_front"] = _pareto_front(rows)
    report["degenerate_front"] = _degenerate_front_decision(rows)
    return report


def _measured_rows(rows: list[dict]) -> list[dict]:
    """Grid points with measured (coverage, dv) aggregates -- a point whose
    every pair is infeasible carries None and cannot enter the front."""
    return [r for r in rows if r["mean_coverage"] is not None]


def _dominates(a: dict, b: dict) -> bool:
    """Point a dominates b: no worse on both axes, strictly better on one."""
    dv_a, dv_b = a["mean_total_dv_mps"], b["mean_total_dv_mps"]
    cov_a, cov_b = a["mean_coverage"], b["mean_coverage"]
    return (dv_a <= dv_b and cov_a >= cov_b) and (dv_a < dv_b or cov_a > cov_b)


def _pareto_front(rows: list[dict]) -> list[list[float]]:
    """Non-dominated points as [w2, dv_budget, mean_dv, mean_coverage], in row
    order (index iteration only). Only points measured over ALL 15 pairs are
    comparable (a mean over a feasible subset is not on the same scale);
    fully-infeasible points never enter either."""
    measured = [r for r in _measured_rows(rows) if r["n_infeasible_pairs"] == 0]
    return [
        [r["w2"], r["dv_budget_mps"], r["mean_total_dv_mps"], r["mean_coverage"]]
        for r in measured
        if not any(_dominates(other, r) for other in measured if other is not r)
    ]


def _degenerate_front_decision(rows: list[dict]) -> dict:
    """The Q4 pre-decision: the measured curve ships as-is, degenerate or not.
    This function only NAMES what was measured."""
    measured = _measured_rows(rows)
    comparable = [r for r in measured if r["n_infeasible_pairs"] == 0]
    n_infeasible_points = len(rows) - len(measured)
    n_partial = len(measured) - len(comparable)
    coverages = [r["mean_coverage"] for r in comparable]
    dvs = [r["mean_total_dv_mps"] for r in comparable]
    if not measured:
        degenerate = "all-infeasible"
        text = (
            "MEASURED: every grid point infeasible (no formation satisfies the "
            "reachability budget). Shipped as-is per user pre-decision Q4."
        )
    elif not comparable:
        degenerate = "all-partial"
        text = (
            "MEASURED: no grid point feasible over all 15 pairs; every mean is "
            "over a feasible subset. Shipped as-is per user pre-decision Q4."
        )
    elif (max(coverages) - min(coverages)) < 1e-5:
        # Flat-front threshold 1e-5 coverage: BELOW it the front is effectively
        # flat -- dv is set by the formation (step-1 sweep), not the assignment
        # (w2 acts on the step-2 cost only, ENDGAME_PLAN 4 fallback note).
        degenerate = "coverage-flat"
        text = (
            "DEGENERATE FRONT (measured): coverage spans only "
            f"{max(coverages) - min(coverages):.2e} across the all-pairs grid "
            f"points (flat threshold 1e-5) while dv spans "
            f"[{min(dvs):.4f}, {max(dvs):.4f}] m/s -- dv is set by the formation, "
            "not the assignment. Shipped as-is per user pre-decision Q4."
        )
    else:
        degenerate = "no"
        text = "Non-degenerate front measured; shipped as-is per Q4."
    if n_partial:
        text += (
            f" {n_partial} of {len(rows)} grid points partially infeasible"
            " (means over a feasible subset, excluded from the front"
            " as not comparable; recorded, not dropped)."
        )
    if n_infeasible_points:
        text += (
            f" {n_infeasible_points} of {len(rows)} grid points fully infeasible"
            " (recorded, not dropped)."
        )
    return {
        "degenerate": degenerate,
        "decision": "ship as-is",
        "decision_text": text,
        "n_infeasible_grid_points": n_infeasible_points,
        "n_partially_infeasible_grid_points": n_partial,
        "min_mean_coverage": min(coverages) if coverages else None,
        "max_mean_coverage": max(coverages) if coverages else None,
        "min_mean_total_dv_mps": min(dvs) if dvs else None,
        "max_mean_total_dv_mps": max(dvs) if dvs else None,
    }


CSV_FIELDS = (
    "w2",
    "dv_budget_mps",
    "mean_coverage",
    "worst_coverage",
    "mean_total_dv_mps",
    "worst_per_sat_dv_mps",
    "n_feasible_pairs",
    "command",
    "reused_p0_logs",
)


def write_csv(report: dict, csv_path: Path) -> None:
    """Machine-written pareto_points.csv: one row per grid point with its
    per-point command (AGENTS.md invariant 1)."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(CSV_FIELDS))
        writer.writeheader()
        for row in report["rows"]:
            writer.writerow({k: row[k] for k in CSV_FIELDS})


def write_svg(report: dict, svg_path: Path, *, width: int = 640, height: int = 420) -> None:
    """Coverage-vs-dv curve, stdlib SVG only (ENDGAME_PLAN 6, P3 writer
    family). All 12 points as labeled circles; the Pareto front as a polyline.
    Axes are data-scaled with padded, human-rounded limits."""
    rows = _measured_rows(report["rows"])
    margin = 56
    xs = [r["mean_total_dv_mps"] for r in rows]
    ys = [r["mean_coverage"] for r in rows]
    x_lo = math.floor(min(xs)) - 1.0
    x_hi = math.ceil(max(xs)) + 1.0
    y_span = (max(ys) - min(ys)) or 1.0
    y_lo = min(ys) - 0.05 * y_span
    y_hi = max(ys) + 0.05 * y_span

    def px(x: float) -> float:
        return margin + (x - x_lo) / (x_hi - x_lo) * (width - 2 * margin)

    def py(y: float) -> float:
        return height - margin - (y - y_lo) / (y_hi - y_lo) * (height - 2 * margin)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        'font-family="monospace" font-size="11">',
        f"<text x='{margin}' y='20'>P1 fuel-vs-coverage Pareto sweep (mean over 15 pairs, "
        "hungarian; w1=1.0 w3=2.0)</text>",
        f"<line x1='{margin}' y1='{height - margin}' x2='{width - margin}' "
        f"y2='{height - margin}' stroke='black'/>",
        f"<line x1='{margin}' y1='{margin}' x2='{margin}' "
        f"y2='{height - margin}' stroke='black'/>",
        f"<text x='{width / 2}' y='{height - 14}' text-anchor='middle'>mean total dv (m/s)</text>",
        f"<text x='14' y='{height / 2}' text-anchor='middle' "
        "transform='rotate(-90 14 "
        f"{height / 2})'>mean coverage retained</text>",
    ]
    for r in rows:
        x, y = px(r["mean_total_dv_mps"]), py(r["mean_coverage"])
        parts.append(
            f"<circle cx='{x:.1f}' cy='{y:.1f}' r='4' fill='#1f77b4'>"
            f"<title>w2={r['w2']} dv_budget={r['dv_budget_mps']:g} m/s: "
            f"coverage={r['mean_coverage']:.6f}, dv={r['mean_total_dv_mps']:.4f} m/s</title>"
            "</circle>"
        )
        parts.append(
            f"<text x='{x + 6:.1f}' y='{y - 6:.1f}'>w2={r['w2']:g}, "
            f"dv_b={r['dv_budget_mps']:g}</text>"
        )
    front = _pareto_front(rows)
    infeasible = [r for r in report["rows"] if r["mean_coverage"] is None]
    for r in infeasible:
        parts.append(
            f"<text x='{margin}' y='{height - 28}' fill='#d62728'>INFEASIBLE "
            f"(measured): w2={r['w2']:g}, dv_budget={r['dv_budget_mps']:g} m/s -- "
            f"{r['n_infeasible_pairs']}/{r['n_feasible_pairs'] + r['n_infeasible_pairs']}"
            " pairs had no feasible formation</text>"
        )
    if len(front) > 1:
        pts = " ".join(
            f"{px(p[2]):.1f},{py(p[3]):.1f}" for p in sorted(front, key=lambda p: p[2])
        )
        parts.append(
            f"<polyline points='{pts}' fill='none' stroke='#d62728' stroke-width='1.5' "
            "stroke-dasharray='4,3'/>"
        )
        parts.append(
            f"<text x='{width - margin}' y='{margin - 8}' text-anchor='end' "
            "fill='#d62728'>Pareto front (non-dominated points)</text>"
        )
    parts.append("</svg>")
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.write_text("\n".join(parts) + "\n", encoding="utf-8")
