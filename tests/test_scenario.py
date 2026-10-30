"""Tests for scenario definitions and execution behaviors."""

from pathlib import Path

from cubesat.scenario import load_scenario
from cubesat.sim import run_scenario


def test_eps_leader_6sat_reassign_on_degrade():
    scenario = load_scenario(Path("data/scenarios/eps_leader_6sat.json"))
    assert scenario.reassign_on_degrade is True
    assert scenario.failures[0].mode == "EPS_DEGRADE"
    assert scenario.failures[0].degrade_s == 1800.0

    lines = run_scenario(scenario)
    swap_events = [
        {
            **line["event"],
            **line["event"]["payload"],
            "old_holder": f"SAT-{line['event']['payload']['from_sat']}",
        }
        for line in lines
        if line.get("event", {}).get("type") == "ORACLE_SWAP"
    ]
    assert len(swap_events) == 1
    assert swap_events[0]["mode"] == "degrade_trigger"
    assert swap_events[0]["old_holder"] == "SAT-0"
    assert swap_events[0]["from_sat"] == 0
    assert swap_events[0]["role"] == "leader"
