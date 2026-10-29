"""Monte Carlo robustness mode for the benchmark driver (zero core diff).

KEY FACT: the sim core consumes NO RNG -- the scenario seed labels the INIT
header only (sim.py writes it verbatim; nothing reads it) -- so a naive seed
sweep is vacuous. The honest ensemble jitters SCENARIO PARAMETERS
deterministically, outside the core:

    failure times x (1 +- 0.10)
    formation phase_offset_deg +- 30 deg
    formation radial amplitude x [0.9, 1.1]

drawn from ONE numpy Generator(PCG64(SeedSequence(seed))) in the fixed per-run
DRAW_ORDER below. Failure sat ids and modes and every other base-scenario
field stay fixed, so runs are comparable to each other and to the committed
P0 numbers (two_failure pair (1,2): hungarian +4.93 pts worst-case, GATES.md).
The driver is the analysis layer -- seeded RNG is allowed THERE (AGENTS.md
invariant 2 bans it inside the sim only), so the whole report is
byte-reproducible by its command.

Outputs (machine-written, invariant 1): per-run JSONL logs in the exact
cubesat.run byte format, monte_carlo_results.json (rows with command + log
sha256 + the drawn jitter, per-policy aggregates, paired comparison) and
monte_carlo_manifest.json (per-log sha256 + the full jitter spec so the
ensemble regenerates exactly).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from cubesat.benchmark import metrics_from_log, run_one
from cubesat.scenario import Scenario

MC_POLICIES = ("do_nothing", "hungarian")
FAILURE_TIME_REL_PM = 0.10  # failure t jitter: t_base * (1 +- 0.10)
PHASE_OFFSET_ABS_PM_DEG = 30.0  # formation phase offset: base +- 30 deg
RADIAL_AMP_REL = 0.10  # radial amplitude multiplier in [0.9, 1.1]

# The exact per-run draw order off the single ensemble stream -- written into
# the manifest so the run regenerates exactly.
DRAW_ORDER = (
    "per failure in base list order: t = t_base * (1 + FAILURE_TIME_REL_PM * U(-1, 1))",
    "formation.phase_offset_deg = base + PHASE_OFFSET_ABS_PM_DEG * U(-1, 1)",
    "formation.radial_amp_km = base * (1 + RADIAL_AMP_REL * U(-1, 1))",
)


def mc_rng(seed: int) -> np.random.Generator:
    """The ensemble RNG: one PCG64 stream off SeedSequence(seed); per-run draws
    follow DRAW_ORDER, so (base, runs, seed) determines every scenario."""
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence(seed)))


def jitter_spec(seed: int, base: Scenario) -> dict:
    """The declared jitter contract written into report + manifest: seed, RNG
    construction, bounds, draw order, and what stays fixed."""
    return {
        "seed": seed,
        "rng": "numpy.random.Generator(numpy.random.PCG64(numpy.random.SeedSequence(seed)))",
        "draw_order_per_run": list(DRAW_ORDER),
        "failure_time_rel_pm": FAILURE_TIME_REL_PM,
        "phase_offset_abs_pm_deg": PHASE_OFFSET_ABS_PM_DEG,
        "radial_amp_multiplier_range": [1.0 - RADIAL_AMP_REL, 1.0 + RADIAL_AMP_REL],
        "fixed": [
            "failure sat_ids and modes (comparability with the base scenario)",
            "every other base-scenario field (duration, roles, allocation, gains, sensor)",
        ],
        "base_scenario": base.name,
    }


def jittered_scenario(
    base: Scenario, rng: np.random.Generator, run_index: int
) -> tuple[Scenario, dict]:
    """Base scenario with the run's parameter jitter -- pydantic model_copy
    only, no core change. Draws follow DRAW_ORDER. Returns (scenario, drawn):
    the drawn block is what the report row records for auditability."""
    failures = [
        f.model_copy(update={"t": f.t * (1.0 + FAILURE_TIME_REL_PM * rng.uniform(-1.0, 1.0))})
        for f in base.failures
    ]
    phase = base.formation.phase_offset_deg + PHASE_OFFSET_ABS_PM_DEG * rng.uniform(-1.0, 1.0)
    amp_mult = 1.0 + RADIAL_AMP_REL * rng.uniform(-1.0, 1.0)
    formation = base.formation.model_copy(
        update={
            "phase_offset_deg": phase,
            "radial_amp_km": base.formation.radial_amp_km * amp_mult,
        }
    )
    scenario = base.model_copy(
        update={"name": f"mc_run_{run_index:03d}", "failures": failures, "formation": formation}
    )
    drawn = {
        "failure_times_s": [f.t for f in failures],
        "phase_offset_deg": phase,
        "radial_amp_multiplier": amp_mult,
        "radial_amp_km": formation.radial_amp_km,
    }
    return scenario, drawn


def _write_log(lines: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for line in lines:
            f.write(json.dumps(line, sort_keys=True) + "\n")


def run_monte_carlo(
    *,
    base: Scenario,
    runs: int,
    seed: int,
    out_dir: Path,
    report_path: Path,
    manifest_path: Path,
    command: str,
) -> dict:
    """Run the jittered ensemble (runs x MC_POLICIES) through the pure core,
    write the logs + report + manifest, return the report dict. Both policies
    see the SAME jittered scenario per run (matched pairs)."""
    rng = mc_rng(seed)
    dead_ids = [f.sat_id for f in base.failures]
    rows: list[dict] = []
    manifest_logs: dict[str, dict] = {}
    for run_index in range(runs):
        scenario, drawn = jittered_scenario(base, rng, run_index)
        first_failure_t = min(f.t for f in scenario.failures) if scenario.failures else 0.0
        for policy in MC_POLICIES:
            lines = run_one(scenario, policy)
            filename = f"mc_run_{run_index:03d}__{policy}.jsonl"
            log_path = out_dir / filename
            _write_log(lines, log_path)
            sha256 = hashlib.sha256(log_path.read_bytes()).hexdigest()
            manifest_logs[filename] = {"sha256": sha256, "run": run_index, "policy": policy}
            rows.append(
                {
                    "run": run_index,
                    "policy": policy,
                    "command": command,
                    "log": filename,
                    "log_sha256": sha256,
                    "jitter": drawn,
                    **metrics_from_log(
                        log_path,
                        first_failure_t=first_failure_t,
                        dead_ids=dead_ids,
                        duration_s=scenario.duration_s,
                    ),
                }
            )
    policies_summary = _mc_policy_summary(rows)
    report = {
        "command": command,
        "mode": "monte-carlo",
        "base_scenario": base.name,
        "seed": seed,
        "runs": runs,
        "policies": list(MC_POLICIES),
        "jitter_spec": jitter_spec(seed, base),
        "rows": rows,
        "policies_summary": policies_summary,
        "comparison": _mc_comparison(rows, policies_summary),
    }
    manifest = {
        "command": command,
        "mode": "monte-carlo",
        "jitter_spec": report["jitter_spec"],
        "logs": manifest_logs,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return report


def _mc_policy_summary(rows: list[dict]) -> dict[str, dict]:
    """Per-policy ensemble aggregates: coverage mean/std/min (min = the worst
    case), total dv mean/max, min survivor-dead separation min. Fixed policy
    order, rows in run order (index iteration only)."""
    summary: dict[str, dict] = {}
    for policy in MC_POLICIES:
        sel = [row for row in rows if row["policy"] == policy]
        coverages = [row["coverage_mean_last_orbit"] for row in sel]
        totals = [row["total_dv_mps"] for row in sel]
        seps = [row["min_sep_survivor_dead_m"] for row in sel]
        summary[policy] = {
            "n_runs": len(sel),
            "coverage_mean_last_orbit": {
                "mean": sum(coverages) / len(coverages),
                "std": float(np.std(coverages)),  # population std (ddof=0)
                "min": min(coverages),
            },
            "total_dv_mps": {"mean": sum(totals) / len(totals), "max": max(totals)},
            "min_sep_survivor_dead_m": {"min": min(seps)},
        }
    return summary


def _mc_comparison(rows: list[dict], policies_summary: dict[str, dict]) -> dict:
    """hungarian vs do_nothing over the ensemble. Every run is a matched pair
    (both policies run the SAME jittered scenario): paired_gain_pts is the
    honest per-run difference. worst_case_coverage_gain_pts is the ensemble
    analogue of the committed P0 +4.93 pt story (hungarian worst vs do_nothing
    worst over the P0 pairs)."""
    by_run: dict[int, dict[str, float]] = {}
    for row in rows:
        by_run.setdefault(row["run"], {})[row["policy"]] = row["coverage_mean_last_orbit"]
    paired: list[float] = []
    for run_index in sorted(by_run):
        coverages = by_run[run_index]
        if "hungarian" in coverages and "do_nothing" in coverages:
            paired.append(coverages["hungarian"] - coverages["do_nothing"])
    hung = policies_summary["hungarian"]["coverage_mean_last_orbit"]
    dn = policies_summary["do_nothing"]["coverage_mean_last_orbit"]
    return {
        "mean_coverage_gain_pts": 100.0 * (hung["mean"] - dn["mean"]),
        "worst_case_coverage_gain_pts": 100.0 * (hung["min"] - dn["min"]),
        "paired_gain_pts": {
            "mean": (100.0 * sum(paired) / len(paired)) if paired else None,
            "min": (100.0 * min(paired)) if paired else None,
        },
    }
