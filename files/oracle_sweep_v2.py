"""Oracle value-of-warning sweep v2: the Gate-2 kill switch, re-measured on
FAIR failure families (GATES.md 2026-10-26 pre-registration).

v1 (files/oracle_sweep.py) swept the committed scenarios, where the
critical-seat metric is structurally flat -- imager deaths never touch the
leader/downlink seats, so the CUT verdict was never tested where the oracle
could help. v2 sweeps four single-failure 6-sat scenarios
(roles leader/imager x4/downlink, two_failure's geometry, failure at t=2400):

  eps_leader_6sat      EPS_DEGRADE sat 0 (leader),   degrade_s=1800
  eps_downlink_6sat    EPS_DEGRADE sat 5 (downlink), degrade_s=1800
  eps_imager_6sat      EPS_DEGRADE sat 1 (imager),   degrade_s=1800 (CONTROL:
                       structurally flat -- expected to show ~zero gain)
  thruster_leader_6sat THRUSTER_OUT sat 0 (leader) -- self-reports at t_fail,
                       so this measures the oracle's RESIDUAL gain over the
                       reactive path (detection latency is already 0 there)

Sweep: oracle.lead_s in {0, 30, 60, 300, 1800} s per scenario. L is capped per
failure at t_f - t_settle (ENDGAME_PLAN 7); t_settle is measured from the
committed nominal log's first in-band tick, and the capping logic is v1's
(files/oracle_sweep.py:93-107). L=0 runs the reactive baseline (oracle off).
NOTHING integrates into the control loop regardless of the verdict -- the
pre-registered threshold only decides what the report says.

Metric (post-hoc from each log, no core diff): critical-seat health fraction =
fraction of tick lines where BOTH unique critical seats (leader, downlink) are
held by a status-NOMINAL satellite; plus total dv (final tick's per-sat
dv_used). Verdict rule (GATES.md 2026-10-26): CLEAR iff some scenario gains
>= 0.5 pp at L=300 s, else CUT-STANDS (the Gate-2 CUT verdict of 2026-10-04
stands, re-measured on fair families).

Output: data/eval/oracle_sweep_v2.json (machine-written; committed) plus the
per-point scenario variants and JSONL logs under data/eval/oracle_sweep_v2/
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
from cubesat.sim import STATE_INIT, STATE_SUMMARY, STATUS_NOMINAL, run_scenario  # noqa: E402

SCENARIOS = [
    ("eps_leader_6sat", ROOT / "data" / "scenarios" / "eps_leader_6sat.json"),
    ("eps_downlink_6sat", ROOT / "data" / "scenarios" / "eps_downlink_6sat.json"),
    ("eps_imager_6sat", ROOT / "data" / "scenarios" / "eps_imager_6sat.json"),
    ("thruster_leader_6sat", ROOT / "data" / "scenarios" / "thruster_leader_6sat.json"),
]
L_GRID = [0.0, 30.0, 60.0, 300.0, 1800.0]
PRE_REGISTERED_THRESHOLD_PP = 0.5
CRITICAL_ROLES = ("leader", "downlink")
NOMINAL_LOG = ROOT / "data" / "logs" / "nominal.jsonl"
OUT_DIR = ROOT / "data" / "eval" / "oracle_sweep_v2"
REPORT_PATH = ROOT / "data" / "eval" / "oracle_sweep_v2.json"
SETTLE_REL_BAND = 0.10  # nominal coverage band half-width, relative to the log mean


def measure_t_settle(path: Path = NOMINAL_LOG, rel_band: float = SETTLE_REL_BAND) -> float:
    """t_settle for the ENDGAME_PLAN 7 cap rule: the first tick of the committed
    nominal log whose coverage sits inside the nominal band, taken here as the
    log's mean tick coverage +/- rel_band (relative). Falls back to 0.0 -- v1's
    rule (files/oracle_sweep.py:93, 'the formation starts settled at t=0') --
    when the log is missing or carries no tick lines. The committed log's tick 0
    (coverage 0.4474 vs mean 0.4387) is in-band, so this measures 0.0 and
    coincides with v1."""
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


def evaluate_log(lines: list[dict]) -> tuple[float, float]:
    """(critical_seat_frac, total_dv_mps), post-hoc from the log lines.

    critical_seat_frac: fraction of tick lines where BOTH unique critical seats
    (leader, downlink) are held by a status-NOMINAL satellite -- the v2 AND
    definition the pre-registration pins; v1 averaged the two seats per tick.
    total_dv: the final tick's summed per-sat dv_used, as in v1."""
    tick_lines = [
        line
        for line in lines
        if line.get("state") not in (STATE_INIT, STATE_SUMMARY) and "sats" in line
    ]
    if not tick_lines:
        return 0.0, 0.0
    both_ok = 0
    for line in tick_lines:
        sats = line["sats"]
        ok = all(
            any(s["role"] == role and s["status"] == STATUS_NOMINAL for s in sats)
            for role in CRITICAL_ROLES
        )
        both_ok += int(ok)
    total_dv = sum(float(s["dv_used"]) for s in tick_lines[-1]["sats"])
    return both_ok / len(tick_lines), total_dv


def log_bytes(lines: list[dict]) -> bytes:
    """Serialize exactly as cubesat.run writes logs (run.py:42-44): sorted-key
    JSON, one line per tick, LF line endings."""
    return "".join(json.dumps(line, sort_keys=True) + "\n" for line in lines).encode("utf-8")


def run_point(sc_name: str, sc_path: Path, l_nominal: float, t_f_min: float, t_settle: float) -> dict:
    """Run one (scenario, L) point; write the variant scenario and the JSONL log
    under OUT_DIR; return the report row (gain_pp filled by the caller once the
    reactive baseline exists)."""
    effective_l = l_nominal
    capped = False
    if (t_f_min - t_settle) < l_nominal:  # v1's cap logic, files/oracle_sweep.py:102-107
        effective_l = max(0.0, t_f_min - t_settle)
        capped = True

    variant = json.loads(sc_path.read_text(encoding="utf-8"))
    if effective_l > 0:
        variant["oracle"] = {"enabled": True, "lead_s": effective_l}
    else:
        variant["oracle"] = {"enabled": False, "lead_s": 0.0}  # L=0: reactive baseline
    scenario = Scenario.model_validate(variant)

    stem = f"{sc_name}__L{l_nominal:g}"
    variant_rel = f"data/eval/oracle_sweep_v2/{stem}.json"
    log_rel = f"data/eval/oracle_sweep_v2/{stem}.jsonl"
    variant_path = ROOT / variant_rel
    log_path = ROOT / log_rel
    variant_path.parent.mkdir(parents=True, exist_ok=True)
    variant_path.write_text(json.dumps(variant, indent=2) + "\n", encoding="utf-8", newline="\n")

    lines = run_scenario(scenario)
    data = log_bytes(lines)
    log_path.write_bytes(data)
    health, dv = evaluate_log(lines)

    return {
        "scenario": sc_name,
        "L_nominal_s": l_nominal,
        "L_effective_s": effective_l,
        "capped": capped,
        "oracle_enabled": effective_l > 0,
        "critical_seat_frac": health,
        "gain_pp": None,
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
        "tool": "files/oracle_sweep_v2.py",
        "command": "uv run python files/oracle_sweep_v2.py",
        "pre_registered_threshold_pp": PRE_REGISTERED_THRESHOLD_PP,
        "pre_registration": (
            "GATES.md decisions log 2026-10-26, recorded before any sweep number "
            "existed: CLEAR iff the max critical-seat health gain at L=300 s "
            "across these families is >= 0.5 pp; below 0.5 pp on every scenario "
            "=> the Gate-2 CUT verdict (2026-10-04) STANDS, re-measured on fair "
            "families. EITHER WAY nothing integrates into the control loop "
            "without a further user decision."
        ),
        "t_settle_s": t_settle,
        "t_settle_rule": (
            "first tick of data/logs/nominal.jsonl whose coverage is within "
            f"+/-{SETTLE_REL_BAND:.0%} (relative) of that log's mean tick coverage; "
            "fallback = v1's t_settle=0.0 (files/oracle_sweep.py:93)"
        ),
        "cap_rule": (
            "L_effective = max(0, t_f_min - t_settle) when below the nominal L "
            "(ENDGAME_PLAN 7; v1 logic, files/oracle_sweep.py:102-107); every v2 "
            "scenario schedules exactly one failure, so per-failure capping and "
            "t_f_min capping coincide"
        ),
        "metric": (
            "critical_seat_frac = fraction of tick lines where BOTH unique "
            "critical seats (leader, downlink) are held by a status-NOMINAL "
            "satellite; gain_pp = (frac - reactive_baseline_frac) * 100, the "
            "reactive baseline being the L=0 point with oracle disabled"
        ),
        "l_grid_s": L_GRID,
        "scenarios": {},
    }

    print("=" * 88)
    print("ORACLE VALUE-OF-WARNING SWEEP v2 (fair failure families)")
    print(f"Pre-registered threshold: gain at L=300 s >= {PRE_REGISTERED_THRESHOLD_PP} pp "
          f"(GATES.md 2026-10-26); t_settle = {t_settle:.1f} s")
    print("=" * 88)

    for sc_name, sc_path in SCENARIOS:
        base = load_scenario(sc_path)
        t_f_min = min((f.t for f in base.failures), default=base.duration_s)
        rows = [run_point(sc_name, sc_path, l, t_f_min, t_settle) for l in L_GRID]
        baseline = rows[0]["critical_seat_frac"]  # L=0, oracle off
        for row in rows:
            row["gain_pp"] = (row["critical_seat_frac"] - baseline) * 100.0
        results["scenarios"][sc_name] = {
            "scenario_path": f"data/scenarios/{sc_path.name}",
            "t_fail_s": t_f_min,
            "reactive_baseline_frac": baseline,
            "rows": rows,
        }
        print(f"--- {sc_name} (t_f={t_f_min:.0f}s, reactive baseline H={baseline:.6f}) ---")
        for row in rows:
            cap = f" (capped from {row['L_nominal_s']:.0f}s)" if row["capped"] else ""
            print(
                f"  L={row['L_effective_s']:6.1f}s{cap:<22} | H={row['critical_seat_frac']:8.6f} "
                f"| gain={row['gain_pp']:+9.4f} pp | dv={row['total_dv_mps']:9.2f} m/s"
            )

    # max() returns the FIRST maximal element, and the comprehensions iterate in
    # the fixed SCENARIOS order, so ties resolve deterministically (lowest
    # scenario, then lowest L, in declaration order).
    rows_l300 = [
        (sc_name, row)
        for sc_name, _ in SCENARIOS
        for row in results["scenarios"][sc_name]["rows"]
        if row["L_nominal_s"] == 300.0
    ]
    rows_all = [
        (sc_name, row)
        for sc_name, _ in SCENARIOS
        for row in results["scenarios"][sc_name]["rows"]
    ]
    best300 = max(rows_l300, key=lambda item: item[1]["gain_pp"])
    best_any = max(rows_all, key=lambda item: item[1]["gain_pp"])
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

    print("-" * 88)
    print(f"Max gain at L=300 s: {gain300:+.4f} pp ({best300[0]}, "
          f"L_effective={best300[1]['L_effective_s']:.0f}s)")
    print(f"Max gain at any L:   {best_any[1]['gain_pp']:+.4f} pp ({best_any[0]}, "
          f"L={best_any[1]['L_nominal_s']:.0f}s)")
    print(f"VERDICT: {results['verdict']} (threshold {PRE_REGISTERED_THRESHOLD_PP} pp at L=300 s; "
          "nothing integrates into the control loop either way)")
    return results


if __name__ == "__main__":
    sweep = run_sweep()
    REPORT_PATH.write_text(json.dumps(sweep, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"\nReport written to {REPORT_PATH}")
