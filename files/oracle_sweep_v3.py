"""Oracle sweep v3: oracle value-of-warning + the degrade-trigger policy
(GATES.md 2026-10-29 pre-registration, recorded before any v3 number existed).

Extends v2 (files/oracle_sweep_v2.py, copy-and-extend; v2's four single-failure
6-sat families and its cap/t_settle rules are unchanged) with:

  (a) critical_seat_frac_functional -- secondary seat metric: a critical seat
      counts held when its holder is NOMINAL *or* DEGRADED (the "functional
      counts as healthy" robustness metric demanded by the v2 caveat review);
  (b) coverage_mean -- mean tick-line coverage per point (mission-level measure);
  (c) the L grid {0, 30, 60, 300, 600, 900, 1200, 1800} s;
  (d) a third policy per scenario: degrade_trigger -- NO oracle (disabled), the
      new defaulted-off Scenario field reassign_on_degrade=true, L_nominal_s=0.
      The EPS_DEGRADE fade window is itself the warning, so the trigger's
      timing equals the oracle L=1800 point on the eps families.

Every row carries "policy" ("reactive" at L=0 / "oracle" at L>0 /
"degrade_trigger") and gains vs that scenario's reactive L=0 baseline:
gain_pp (pinned NOMINAL-only metric), gain_pp_functional, gain_pp_coverage.

Pre-registered trigger verdict (fixed before measurement): the trigger is
RECOMMENDED as an opt-in scenario field iff the best eps critical-seat family
(eps_leader_6sat or eps_downlink_6sat) shows a trigger gain >= 0.5 pp on the
PINNED metric AND its mean-coverage gain over the reactive baseline is >= 0.
Otherwise the mechanism ships measured-but-unrecommended and the Gate-2 CUT
verdict stands for the control-loop default. Either way nothing integrates
into the control loop without a further user decision.

Output: data/eval/oracle_sweep_v3.json (machine-written; committed) plus the
per-point scenario variants and JSONL logs under data/eval/oracle_sweep_v3/
(gitignored -- regenerate with the per-row command, cubesat.run serialization:
sorted-key JSON, LF endings, run.py:42-44).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cubesat.scenario import Scenario, load_scenario  # noqa: E402
from cubesat.sim import (  # noqa: E402
    STATE_INIT,
    STATE_SUMMARY,
    STATUS_DEGRADED,
    STATUS_NOMINAL,
    run_scenario,
)

SCENARIOS = [
    ("eps_leader_6sat", ROOT / "data" / "scenarios" / "eps_leader_6sat.json"),
    ("eps_downlink_6sat", ROOT / "data" / "scenarios" / "eps_downlink_6sat.json"),
    ("eps_imager_6sat", ROOT / "data" / "scenarios" / "eps_imager_6sat.json"),
    ("thruster_leader_6sat", ROOT / "data" / "scenarios" / "thruster_leader_6sat.json"),
]
L_GRID = [0.0, 30.0, 60.0, 300.0, 600.0, 900.0, 1200.0, 1800.0]
PRE_REGISTERED_THRESHOLD_PP = 0.5
CRITICAL_ROLES = ("leader", "downlink")
TRIGGER_FAMILIES = ("eps_leader_6sat", "eps_downlink_6sat")
NOMINAL_LOG = ROOT / "data" / "logs" / "nominal.jsonl"
OUT_DIR = ROOT / "data" / "eval" / "oracle_sweep_v3"
REPORT_PATH = ROOT / "data" / "eval" / "oracle_sweep_v3.json"
SETTLE_REL_BAND = 0.10  # nominal coverage band half-width, relative to the log mean

TRIGGER_RULE = (
    "GATES.md decisions log 2026-10-29, recorded before any v3 number existed: "
    "the trigger is RECOMMENDED as an opt-in scenario field (defaults never "
    "change canonical logs) iff the best eps critical-seat family "
    "(eps_leader_6sat or eps_downlink_6sat) shows a trigger gain >= 0.5 pp on "
    "the PINNED metric (NOMINAL-only seats; same threshold and rationale as the "
    "2026-10-03 and 2026-10-26 pre-registrations) AND its mean-coverage gain "
    "over the reactive baseline is >= 0 (no-harm check at mission level). "
    "Otherwise the mechanism ships measured-but-unrecommended and the Gate-2 "
    "CUT verdict stands for the control-loop default. Known caveat carried into "
    "every report of these numbers: the pinned metric counts the "
    "still-functional fade window as outage; the functional metric "
    "(NOMINAL or DEGRADED counts as held) is reported alongside."
)


def measure_t_settle(path: Path = NOMINAL_LOG, rel_band: float = SETTLE_REL_BAND) -> float:
    """v2's rule unchanged (files/oracle_sweep_v2.py:65-93): the first tick of
    the committed nominal log whose coverage sits inside the log's mean tick
    coverage +/- rel_band (relative); fallback 0.0 when the log is missing."""
    try:
        raw = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except OSError:
        return 0.0
    ticks = [
        line
        for line in raw
        if line.get("state") not in (STATE_INIT, STATE_SUMMARY) and "coverage" in line
    ]
    if not ticks:
        return 0.0
    covs = [float(line["coverage"]) for line in ticks]
    mean = sum(covs) / len(covs)
    for line in ticks:
        if abs(float(line["coverage"]) - mean) <= rel_band * mean:
            return float(line["t"])
    return 0.0


def evaluate_log(lines: list[dict]) -> tuple[float, float, float, float]:
    """(critical_seat_frac, critical_seat_frac_functional, coverage_mean,
    total_dv_mps), post-hoc from the log lines -- no core diff.

    critical_seat_frac: fraction of tick lines where BOTH unique critical seats
    (leader, downlink) are held by a status-NOMINAL satellite -- the PINNED
    metric the pre-registrations threshold (v2 AND definition, unchanged).
    critical_seat_frac_functional: same, but NOMINAL or DEGRADED counts as
    held (the fade window is still functional). coverage_mean: mean tick-line
    coverage. total_dv: the final tick's summed per-sat dv_used (v1/v2 rule)."""
    tick_lines = [
        line
        for line in lines
        if line.get("state") not in (STATE_INIT, STATE_SUMMARY) and "sats" in line
    ]
    if not tick_lines:
        return 0.0, 0.0, 0.0, 0.0
    both_ok = 0
    both_ok_functional = 0
    for line in tick_lines:
        sats = line["sats"]
        ok = all(
            any(s["role"] == role and s["status"] == STATUS_NOMINAL for s in sats)
            for role in CRITICAL_ROLES
        )
        ok_functional = all(
            any(
                s["role"] == role and s["status"] in (STATUS_NOMINAL, STATUS_DEGRADED)
                for s in sats
            )
            for role in CRITICAL_ROLES
        )
        both_ok += int(ok)
        both_ok_functional += int(ok_functional)
    total_dv = sum(float(s["dv_used"]) for s in tick_lines[-1]["sats"])
    coverage_mean = sum(float(line["coverage"]) for line in tick_lines) / len(tick_lines)
    return (
        both_ok / len(tick_lines),
        both_ok_functional / len(tick_lines),
        coverage_mean,
        total_dv,
    )


def log_bytes(lines: list[dict]) -> bytes:
    """Serialize exactly as cubesat.run writes logs (run.py:42-44): sorted-key
    JSON, one line per tick, LF line endings."""
    return "".join(json.dumps(line, sort_keys=True) + "\n" for line in lines).encode("utf-8")


def run_point(
    sc_name: str, sc_path: Path, policy: str, l_nominal: float, t_f_min: float, t_settle: float
) -> dict:
    """Run one (scenario, policy, L) point; write the variant scenario and the
    JSONL log under OUT_DIR; return the report row (gains filled by the caller
    once the reactive baseline exists). policy: "reactive" (L=0, oracle off) /
    "oracle" (L>0, oracle on, v2 cap logic) / "degrade_trigger" (no oracle,
    reassign_on_degrade=true, no L)."""
    effective_l = l_nominal
    capped = False
    if policy != "degrade_trigger" and (t_f_min - t_settle) < l_nominal:
        effective_l = max(0.0, t_f_min - t_settle)  # v1's cap logic
        capped = True

    variant = json.loads(sc_path.read_text(encoding="utf-8"))
    if policy == "degrade_trigger":
        variant["oracle"] = {"enabled": False, "lead_s": 0.0}
        variant["reassign_on_degrade"] = True
        effective_l, capped = 0.0, False
    elif effective_l > 0:
        variant["oracle"] = {"enabled": True, "lead_s": effective_l}
    else:
        variant["oracle"] = {"enabled": False, "lead_s": 0.0}  # reactive baseline
    scenario = Scenario.model_validate(variant)

    stem = f"{sc_name}__degrade_trigger" if policy == "degrade_trigger" else f"{sc_name}__L{l_nominal:g}"
    variant_rel = f"data/eval/oracle_sweep_v3/{stem}.json"
    log_rel = f"data/eval/oracle_sweep_v3/{stem}.jsonl"
    variant_path = ROOT / variant_rel
    log_path = ROOT / log_rel
    variant_path.parent.mkdir(parents=True, exist_ok=True)
    variant_path.write_text(json.dumps(variant, indent=2) + "\n", encoding="utf-8", newline="\n")

    lines = run_scenario(scenario)
    data = log_bytes(lines)
    log_path.write_bytes(data)
    health, health_functional, coverage_mean, dv = evaluate_log(lines)

    return {
        "scenario": sc_name,
        "policy": policy,
        "L_nominal_s": l_nominal,
        "L_effective_s": effective_l,
        "capped": capped,
        "oracle_enabled": policy == "oracle" and effective_l > 0,
        "critical_seat_frac": health,
        "critical_seat_frac_functional": health_functional,
        "coverage_mean": coverage_mean,
        "gain_pp": None,
        "gain_pp_functional": None,
        "gain_pp_coverage": None,
        "total_dv_mps": dv,
        "log": log_rel,
        "log_sha256": hashlib.sha256(data).hexdigest(),
        "command": (
            f"uv run python -m cubesat.run --scenario {variant_rel} "
            f"--seed {scenario.seed} --out {log_rel}"
        ),
    }


def run_sweep() -> dict:
    t_settle = measure_t_settle()
    results: dict = {
        "tool": "files/oracle_sweep_v3.py",
        "command": "uv run python files/oracle_sweep_v3.py",
        "pre_registered_threshold_pp": PRE_REGISTERED_THRESHOLD_PP,
        "pre_registration": TRIGGER_RULE,
        "t_settle_s": t_settle,
        "t_settle_rule": (
            "first tick of data/logs/nominal.jsonl whose coverage is within "
            f"+/-{SETTLE_REL_BAND:.0%} (relative) of that log's mean tick coverage; "
            "fallback = v1's t_settle=0.0 (files/oracle_sweep.py:93)"
        ),
        "cap_rule": (
            "L_effective = max(0, t_f_min - t_settle) when below the nominal L "
            "(ENDGAME_PLAN 7; v1 logic, files/oracle_sweep.py:102-107); every v3 "
            "scenario schedules exactly one failure, so per-failure capping and "
            "t_f_min capping coincide; the degrade_trigger policy has no L and is "
            "never capped"
        ),
        "metric": (
            "critical_seat_frac = fraction of tick lines where BOTH unique "
            "critical seats (leader, downlink) are held by a status-NOMINAL "
            "satellite (PINNED); critical_seat_frac_functional = same but "
            "NOMINAL-or-DEGRADED counts as held; coverage_mean = mean tick-line "
            "coverage; gain_pp / gain_pp_functional / gain_pp_coverage = each "
            "metric minus the reactive L=0 baseline of the same scenario, x100"
        ),
        "l_grid_s": L_GRID,
        "scenarios": {},
    }

    print("=" * 88)
    print("ORACLE SWEEP v3 (oracle value-of-warning + degrade-trigger policy)")
    print(f"Pre-registered trigger threshold: pinned gain >= {PRE_REGISTERED_THRESHOLD_PP} pp "
          f"AND coverage gain >= 0 (GATES.md 2026-10-29); t_settle = {t_settle:.1f} s")
    print("=" * 88)

    for sc_name, sc_path in SCENARIOS:
        base = load_scenario(sc_path)
        t_f_min = min((f.t for f in base.failures), default=base.duration_s)
        rows = [run_point(sc_name, sc_path, "oracle" if l > 0 else "reactive", l, t_f_min, t_settle)
                for l in L_GRID]
        rows.append(run_point(sc_name, sc_path, "degrade_trigger", 0.0, t_f_min, t_settle))
        baseline = rows[0]  # L=0 reactive row
        for row in rows:
            row["gain_pp"] = (row["critical_seat_frac"] - baseline["critical_seat_frac"]) * 100.0
            row["gain_pp_functional"] = (
                row["critical_seat_frac_functional"]
                - baseline["critical_seat_frac_functional"]
            ) * 100.0
            row["gain_pp_coverage"] = (
                row["coverage_mean"] - baseline["coverage_mean"]
            ) * 100.0
        results["scenarios"][sc_name] = {
            "scenario_path": f"data/scenarios/{sc_path.name}",
            "t_fail_s": t_f_min,
            "reactive_baseline_frac": baseline["critical_seat_frac"],
            "rows": rows,
        }
        print(f"--- {sc_name} (t_f={t_f_min:.0f}s, reactive baseline H={baseline['critical_seat_frac']:.6f}) ---")
        for row in rows:
            cap = f" (capped from {row['L_nominal_s']:.0f}s)" if row["capped"] else ""
            label = row["policy"] if row["policy"] == "degrade_trigger" else f"L={row['L_effective_s']:.0f}s"
            print(
                f"  {row['policy']:<15}{label:>8}{cap:<22} | H={row['critical_seat_frac']:8.6f} "
                f"| Hf={row['critical_seat_frac_functional']:8.6f} "
                f"| cov={row['coverage_mean']:8.6f} "
                f"| gain={row['gain_pp']:+9.4f} pp | dvcov={row['gain_pp_coverage']:+8.4f} pp "
                f"| dv={row['total_dv_mps']:9.2f} m/s"
            )

    # Oracle verdict (v2's rule, unchanged): max gain_pp at L=300 s across the
    # ORACLE rows (policy != degrade_trigger). max() returns the FIRST maximal
    # element over the fixed SCENARIOS order, so ties resolve deterministically.
    oracle_rows = [
        (sc_name, row)
        for sc_name, _ in SCENARIOS
        for row in results["scenarios"][sc_name]["rows"]
        if row["policy"] != "degrade_trigger"
    ]
    rows_l300 = [(n, r) for n, r in oracle_rows if r["L_nominal_s"] == 300.0]
    best300 = max(rows_l300, key=lambda item: item[1]["gain_pp"])
    best_any = max(oracle_rows, key=lambda item: item[1]["gain_pp"])
    gain300 = best300[1]["gain_pp"]
    results["max_gain_at_L300"] = {
        "pp": gain300,
        "scenario": best300[0],
        "L_effective_s": best300[1]["L_effective_s"],
        "threshold_pp": PRE_REGISTERED_THRESHOLD_PP,
    }
    results["max_gain_any_L"] = {
        "pp": best_any[1]["gain_pp"],
        "scenario": best_any[0],
        "L_nominal_s": best_any[1]["L_nominal_s"],
    }
    results["verdict"] = "CLEAR" if gain300 >= PRE_REGISTERED_THRESHOLD_PP else "CUT-STANDS"

    # Pre-registered trigger verdict: best of the two eps critical-seat families
    # by the PINNED metric; recommend iff pinned gain >= threshold AND coverage
    # gain >= 0. Ties keep the first family in SCENARIOS order (deterministic).
    trigger_candidates = [
        (sc_name, next(r for r in results["scenarios"][sc_name]["rows"] if r["policy"] == "degrade_trigger"))
        for sc_name in TRIGGER_FAMILIES
    ]
    best_family, best_trigger = max(trigger_candidates, key=lambda item: item[1]["gain_pp"])
    best_baseline = results["scenarios"][best_family]["rows"][0]
    recommend = (
        best_trigger["gain_pp"] >= PRE_REGISTERED_THRESHOLD_PP
        and best_trigger["gain_pp_coverage"] >= 0.0
    )
    results["trigger_verdict"] = {
        "family": best_family,
        "pinned_gain_pp": best_trigger["gain_pp"],
        "functional_gain_pp": best_trigger["gain_pp_functional"],
        "coverage_gain_pp": best_trigger["gain_pp_coverage"],
        "dv_trigger_mps": best_trigger["total_dv_mps"],
        "dv_baseline_mps": best_baseline["total_dv_mps"],
        "recommend": recommend,
        "rule": TRIGGER_RULE,
    }

    print("-" * 88)
    print(f"Oracle max gain at L=300 s: {gain300:+.4f} pp ({best300[0]}) -> verdict {results['verdict']}")
    tv = results["trigger_verdict"]
    print(
        f"TRIGGER VERDICT ({tv['family']}): pinned {tv['pinned_gain_pp']:+.4f} pp, "
        f"functional {tv['functional_gain_pp']:+.4f} pp, coverage {tv['coverage_gain_pp']:+.4f} pp, "
        f"dv {tv['dv_trigger_mps']:.2f} vs baseline {tv['dv_baseline_mps']:.2f} m/s -> "
        f"recommend={tv['recommend']}"
    )
    return results


if __name__ == "__main__":
    sweep = run_sweep()
    REPORT_PATH.write_text(json.dumps(sweep, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"\nReport written to {REPORT_PATH}")
