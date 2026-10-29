"""Tests for the v2 oracle value-of-warning sweep (fair failure families).

v2 re-measures the pre-registered Gate-2 kill switch on the four single-failure
6-sat families that can actually move the critical-seat metric (GATES.md
2026-10-26 pre-registration) -- the committed imager-death scenarios are
structurally flat on that metric, so v1's CUT never tested the oracle where it
could help.

  test_v2_scenarios_parse_and_run: each NEW v2 scenario parses through the
  pydantic schema and runs through the pure core on a short duration variant
  (the t=2400 failure still fires; full-length runs are the sweep's job,
  files/oracle_sweep_v2.py).
  test_v2_report_schema_and_verdict: the machine-written report carries the
  pre-registered threshold and a verdict that follows from its own rows.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cubesat.scenario import Scenario, load_scenario  # noqa: E402
from cubesat.sim import (  # noqa: E402
    STATE_SUMMARY,
    STATUS_DEGRADED,
    STATUS_NOMINAL,
    run_scenario,
)

V2_SCENARIOS = [
    ROOT / "data" / "scenarios" / "eps_leader_6sat.json",
    ROOT / "data" / "scenarios" / "eps_downlink_6sat.json",
    ROOT / "data" / "scenarios" / "eps_imager_6sat.json",
    ROOT / "data" / "scenarios" / "thruster_leader_6sat.json",
]
REPORT = ROOT / "data" / "eval" / "oracle_sweep_v2.json"
CRITICAL_ROLES = ("leader", "downlink")

# Tiny 4-sat base mirroring tests/test_failure_modes.py BASE (1 km slots,
# min_sep 0.5 km so the 3-survivor formation sweep stays feasible). EPS_DEGRADE
# on sat 3 (downlink, seat 3) with a 30 s fade from t=30; oracle lead_s=25 puts
# the alert at t=36, mid-fade -- so the oracle-triggered replan at t=38 runs
# while a sat is DEGRADED, the only way any replan can.
ORPHAN_SCENARIO: dict = {
    "name": "v2_degraded_orphan",
    "seed": 7,
    "duration_s": 2400.0,
    "dt_s": 2.0,
    "chief": {"altitude_km": 500.0},
    "formation": {"n_slots": 4, "radial_amp_km": 1.0, "phase_offset_deg": 0.0},
    "a_max_mps2": 0.01,
    "gains": {"wn": 0.01, "zeta": 1.0},
    "sensor": {"fov_half_angle_deg": 1.5, "grid_step_km": 5.0, "grid_extent_km": 5.0},
    "roles": ["leader", "imager", "imager", "downlink"],
    "allocation": {
        "w1": 1.0,
        "w2": 0.5,
        "w3": 2.0,
        "min_sep_km": 0.5,
        "dv_budget_mps": 200.0,
    },
    "failures": [{"t": 60.0, "sat_id": 3, "mode": "EPS_DEGRADE", "degrade_s": 30.0}],
    "oracle": {"enabled": True, "lead_s": 25.0},
}


def test_v2_scenarios_parse_and_run():
    """Each v2 scenario parses and runs (short duration variant, t=2400 still fires)."""
    for path in V2_SCENARIOS:
        scenario = load_scenario(path)
        assert scenario.n_sats == 6
        assert scenario.roles == ["leader", "imager", "imager", "imager", "imager", "downlink"]
        assert scenario.duration_s == 17028.0 and scenario.dt_s == 2.0
        assert scenario.a_max_mps2 == 0.1
        assert len(scenario.failures) == 1 and scenario.failures[0].t == 2400.0

        short = scenario.model_copy(update={"duration_s": 2600.0})
        lines = run_scenario(short)
        assert lines[0]["state"] == "INIT" and lines[-1]["state"] == STATE_SUMMARY
        ticks = [line for line in lines if "sats" in line]
        assert len(ticks) == 1301  # 2600/2 + 1

        # the scheduled failure fires: the failing sat is non-NOMINAL somewhere
        sat_id = scenario.failures[0].sat_id
        assert any(
            s["id"] == sat_id and s["status"] != STATUS_NOMINAL
            for line in ticks
            for s in line["sats"]
        )
        # the reactive path re-elected both critical seats to NOMINAL holders by run end
        for role in CRITICAL_ROLES:
            assert any(
                s["role"] == role and s["status"] == STATUS_NOMINAL
                for s in ticks[-1]["sats"]
            ), f"{path.name}: {role} seat not held by a NOMINAL sat at end of short run"


def test_v2_degraded_seat_preserved_across_oracle_replan(tmp_path):
    """Regression for the sweep-v2 blocker: a replan that fires while a sat is
    DEGRADED (only the oracle hook can trigger one -- the reactive path replans
    only after the sat dies) must keep the degraded sat PD-holding its assigned
    seat (Addendum v1.2 semantics, sim.py module docstring). Before the fix the
    stale seat_of index either crashed the step loop with IndexError
    (eps_downlink_6sat: seat 5 vs a 5-seat survivor formation) or silently
    double-booked a survivor's seat (eps_leader_6sat: seat 0)."""
    path = tmp_path / "orphan.json"
    path.write_text(json.dumps(ORPHAN_SCENARIO), encoding="utf-8")
    scenario = load_scenario(path)
    # full re-validation, not model_copy(update=...): pydantic v2 model_copy
    # does not re-validate, so an injected oracle dict would bypass the model
    nofail = Scenario.model_validate(
        dict(ORPHAN_SCENARIO, failures=[], oracle={"enabled": False, "lead_s": 0.0})
    )

    lines = run_scenario(scenario)  # pre-fix: IndexError at the t=38 replan step
    assert lines[-1]["state"] == STATE_SUMMARY
    clean = run_scenario(nofail)

    ticks = [line for line in lines if "sats" in line]
    clean_ticks = [line for line in clean if "sats" in line]
    # the fade window runs DEGRADED-but-reporting, and the alert lands mid-fade
    assert any(line["sats"][3]["status"] == STATUS_DEGRADED for line in ticks)
    assert any(
        line.get("event", {}).get("type") == "ORACLE_ALERT"
        and 30.0 <= line["t"] < 60.0
        for line in lines
    )
    # across the replan the degraded sat KEEPS PD-holding its assigned seat:
    # trajectory and dv equal the no-failure run (same seat reference, same PD)
    # at every tick up to its death, exactly like test_failure_modes' window check
    for line, ref in zip(ticks, clean_ticks, strict=True):
        if line["t"] <= 60.0:
            assert line["sats"][3]["r"] == ref["sats"][3]["r"], f"seat moved at t={line['t']}"
            assert line["sats"][3]["dv_used"] == ref["sats"][3]["dv_used"]
    # re-election after the alert gave both critical seats NOMINAL holders
    for role in CRITICAL_ROLES:
        assert any(
            s["role"] == role and s["status"] == STATUS_NOMINAL
            for s in ticks[-1]["sats"]
        ), f"{role} seat not held by a NOMINAL sat at end of run"


def test_v2_report_schema_and_verdict():
    """The report carries the threshold + verdict fields; the verdict matches the rows."""
    if not REPORT.exists():
        pytest.skip("report not generated yet (run files/oracle_sweep_v2.py)")
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    threshold = report["pre_registered_threshold_pp"]
    assert threshold == 0.5
    assert report["verdict"] in ("CLEAR", "CUT-STANDS")

    rows_l300 = [
        row
        for sc in report["scenarios"].values()
        for row in sc["rows"]
        if row["L_nominal_s"] == 300.0
    ]
    assert len(rows_l300) == len(report["scenarios"]), "one L=300 s row per scenario"
    max_gain = max(row["gain_pp"] for row in rows_l300)
    assert report["max_gain_at_L300"]["pp"] == max_gain
    assert report["max_gain_at_L300"]["threshold_pp"] == threshold
    assert (report["verdict"] == "CLEAR") == (max_gain >= threshold)

    for sc in report["scenarios"].values():
        for row in sc["rows"]:
            assert row["command"].startswith("uv run python -m cubesat.run")
            assert len(row["log_sha256"]) == 64
            assert 0.0 <= row["critical_seat_frac"] <= 1.0
            assert row["total_dv_mps"] >= 0.0
            # a committed report's shas stay verifiable whenever the log is on disk
            log_path = ROOT / row["log"]
            if log_path.exists():
                assert (
                    hashlib.sha256(log_path.read_bytes()).hexdigest() == row["log_sha256"]
                ), f"sha mismatch for {row['log']}"
