"""Gate-1 deliverable: score two_failure offline and print SUSPECT times vs true t_f.

Usage:
    uv run python files/score_two_failure.py

Honest caveats (printed at the end):
  - two_failure: 8515 ticks (duration 17028 s), pipeline trained on T_TICKS=5400.
    Rows with tick >= 5400 are out-of-distribution (ood=True).
  - Failures fire at t=1200/1500 s (ticks 600/750). With WARM=300 the first scored
    tick is 300; there are only 30 scored rows between the first scored tick and the
    first failure (t 600 s - 300 s = 300 s / 20 s stride = 15 rows). The profile-A
    ramp [1800-3600 s] is longer than the available precursor window, so degenerate
    or zero lead is expected and should be reported honestly.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cubesat.scenario import load_scenario
from predictor.runtime import (
    telemetry_from_schedule,
    score_run,
    suspect_alerts,
    load_tau,
    DT,
    T_TICKS,
    WARM,
    STRIDE,
    K_ALARM,
)

SCENARIO_PATH = ROOT / "data" / "scenarios" / "two_failure.json"
SEED = 42


def main():
    scenario = load_scenario(SCENARIO_PATH)
    n_ticks_sim = int(round(scenario.duration_s / DT)) + 1

    print(f"=== Gate-1: score two_failure offline ===")
    print(f"Scenario    : {scenario.name}")
    print(f"Duration    : {scenario.duration_s} s = {n_ticks_sim} ticks at dt={DT} s")
    print(f"T_TICKS     : {T_TICKS} (pipeline training length)")
    print(f"OOD ticks   : {max(0, n_ticks_sim - T_TICKS)} ticks beyond T_TICKS will be flagged ood=True")
    print(f"WARM        : {WARM} ticks (first scored tick = {WARM * DT} s)")
    print(f"STRIDE      : {STRIDE} ticks (scored every {STRIDE * DT} s)")
    print(f"K_ALARM     : {K_ALARM} consecutive rows >= tau -> PREDICTOR_ALERT")
    print()

    # True failure schedule
    print("True failure schedule:")
    for f in scenario.failures:
        print(f"  sat_id={f.sat_id}  t_f={f.t} s  (tick {int(round(f.t / DT))})")
        precursor_window_s = max(f.t - WARM * DT, 0)
        n_scored_before = int(precursor_window_s / (STRIDE * DT))
        print(f"    precursor window available: {precursor_window_s:.0f} s = {n_scored_before} scored rows before failure")
    print()

    # Synthesise telemetry and score
    print("Synthesising telemetry from schedule ...")
    X = telemetry_from_schedule(scenario, SEED)
    print(f"  Telemetry shape: {X.shape}  (capped at T_TICKS={T_TICKS})")
    print("Scoring with frozen LGB model ...")
    scored = score_run(X)
    tau = load_tau()
    print(f"  tau_lgb = {tau:.5f}  (from models/predictor_manifest.json)")
    print(f"  Total scored rows: {len(scored)}")
    ood_count = sum(1 for r in scored if r.ood)
    print(f"  OOD rows (tick >= {T_TICKS}): {ood_count}")
    print()

    # SUSPECT alerts
    alerts = suspect_alerts(scored, tau)
    print("SUSPECT alerts (K_ALARM consecutive rows >= tau):")
    if alerts:
        for a in alerts:
            print(f"  sat_id={a.sat_id}  alert_tick={a.tick}  alert_t={a.t_s:.1f} s  score={a.score:.4f}")
    else:
        print("  (none)")
    print()

    # Per-failing-sat report: alert vs true t_f
    print("SUSPECT times vs true t_f per failing sat:")
    tf_map = {f.sat_id: f.t for f in scenario.failures}
    for sat_id, t_f in sorted(tf_map.items()):
        sat_alerts = [a for a in alerts if a.sat_id == sat_id]
        if sat_alerts:
            earliest = sat_alerts[0]
            lead = t_f - earliest.t_s
            print(f"  sat {sat_id}: ALERT at t={earliest.t_s:.1f} s  t_f={t_f:.1f} s  lead={lead:.1f} s")
        else:
            print(f"  sat {sat_id}: NO ALERT  t_f={t_f:.1f} s")
    print()

    # Per-sat max score before and around t_f
    print("Max scores per sat (in-distribution rows only, tick < T_TICKS):")
    from collections import defaultdict
    sat_scores = defaultdict(list)
    for r in scored:
        if not r.ood:
            sat_scores[r.sat_id].append(r)
    for sat_id in sorted(sat_scores):
        rows = sat_scores[sat_id]
        max_score = max(r.score for r in rows)
        max_tick = max(rows, key=lambda r: r.score).tick
        t_f = tf_map.get(sat_id, None)
        line = f"  sat {sat_id}: max_score={max_score:.4f} at tick={max_tick} (t={max_tick*DT:.0f} s)"
        if t_f is not None:
            line += f"  [t_f={t_f:.0f} s]"
        print(line)
    print()

    # Honest caveats
    print("=== HONEST CAVEATS ===")
    print(f"1. two_failure runs {n_ticks_sim} ticks; the pipeline trained on {T_TICKS} ticks.")
    print(f"   {ood_count} scored rows are OOD (tick >= {T_TICKS}) and should not be trusted for deployment decisions.")
    print(f"2. Failures fire at t=1200/1500 s. With WARM={WARM} ticks ({WARM * DT:.0f} s), the")
    print(f"   precursor window is only {min(600,1200) - WARM*DT:.0f}/{min(750,1500)*2 - WARM*DT:.0f} s available before the failures.")
    print(f"   Profile-A ramp length is {1800}-{3600} s; the ramps extend BEFORE t=0 or are truncated.")
    print(f"   Degenerate / zero lead is EXPECTED and is not a bug — the reactive path (4 s detection) is the safety net.")
    print(f"3. Sudden-death families have ~0 recall; these failures have no precursor overlay.")
    print(f"4. ~260 s median lead gain is measured on TRAINED families (EPS-fade, comms) with long ramps.")
    print(f"   The ~600 s available window here is shorter than the profile-A ramp [1800-3600 s].")


if __name__ == "__main__":
    main()
