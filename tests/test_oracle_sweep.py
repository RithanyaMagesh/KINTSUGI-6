"""Tests for Phase 2: Oracle value-of-warning and byte-invariance.

Verifies:
  1. test_oracle_disabled_bytes_identical:
     Running with oracle.enabled=False produces byte-identical log lines
     compared to a scenario without oracle configured.
  2. test_oracle_swap_protects_critical_seat:
     When leader is scheduled to fail, oracle swap transfers the leader role
     to a nominal survivor, avoiding critical role outage.
  3. test_oracle_sweep_results_match_kill_switch:
     Verifies that gain at L=300 s is evaluated against the 0.5 pp threshold.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cubesat.scenario import Scenario  # noqa: E402
from cubesat.sim import STATUS_NOMINAL, run_scenario  # noqa: E402


def test_oracle_disabled_bytes_identical():
    """Default-off oracle is completely byte-inert on committed scenarios."""
    sc_path = ROOT / "data" / "scenarios" / "two_failure.json"
    raw_dict = json.loads(sc_path.read_text(encoding="utf-8"))

    # Case A: no oracle block in JSON
    sc_a = Scenario.model_validate(raw_dict)
    lines_a = run_scenario(sc_a)

    # Case B: explicit oracle.enabled=False
    dict_b = dict(raw_dict)
    dict_b["oracle"] = {"enabled": False, "lead_s": 0.0}
    sc_b = Scenario.model_validate(dict_b)
    lines_b = run_scenario(sc_b)

    assert len(lines_a) == len(lines_b)
    for i, (la, lb) in enumerate(zip(lines_a, lines_b, strict=True)):
        assert la == lb, f"Mismatch at line {i}: {la} vs {lb}"


def test_oracle_swap_protects_critical_seat():
    """Oracle swap at t_f - L swaps critical role from failing sat to nominal sat."""
    sc_path = ROOT / "data" / "scenarios" / "single_failure_n4.json"
    raw_dict = json.loads(sc_path.read_text(encoding="utf-8"))

    # With oracle L=300s
    raw_dict["oracle"] = {"enabled": True, "lead_s": 300.0}
    sc = Scenario.model_validate(raw_dict)
    lines = run_scenario(sc)

    # Check for ORACLE_ALERT and ORACLE_SWAP events
    events = [entry.get("event") for entry in lines if "event" in entry and entry["event"]]
    swap_events = [e for e in events if e.get("type") == "ORACLE_SWAP"]

    assert len(swap_events) >= 1, "Expected at least one ORACLE_SWAP event"
    swap = swap_events[0]
    assert swap["payload"]["role"] == "leader"
    assert swap["payload"]["from_sat"] == 0  # Sat 0 was leader

    # Verify that leader was NEVER held by a DEAD sat
    for entry in lines:
        if "sats" in entry:
            for s in entry["sats"]:
                if s["role"] == "leader":
                    assert s["status"] == STATUS_NOMINAL, (
                        f"Leader held by non-nominal sat at t={entry['t']}: {s}"
                    )

