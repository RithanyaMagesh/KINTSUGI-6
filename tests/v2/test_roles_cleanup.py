"""Phase 5a fix round: role_priority permutation, light import, handoff_events, odd role sets."""

import itertools
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from cubesat.roles_v2 import DEFAULT_PRIORITY, handoff_events
from cubesat.scenario import Scenario
from cubesat.sim_v2 import run_scenario_v2

ROOT = Path(__file__).resolve().parents[2]
SENSOR = {"fov_half_angle_deg": 1.5, "grid_step_km": 5.0, "grid_extent_km": 5.0}


def _scn(name="nominal", **kw) -> Scenario:
    d = json.loads((ROOT / "data" / "scenarios" / f"{name}.json").read_text())
    return Scenario.model_validate({**d, "engine": "v2", "sensor": SENSOR, **kw})


def _ticks(lines):
    return [x for x in lines if "sats" in x]


@pytest.mark.parametrize("perm", list(itertools.permutations(["downlink", "imager", "leader"])))
def test_role_priority_accepts_every_permutation(perm):
    assert _scn(role_priority=list(perm)).role_priority == list(perm)


@pytest.mark.parametrize(
    "bad",
    [[], ["pilot"], ["leader", "leader", "imager"], ["downlink", "imager"], ["relay", "leader"],
     ["downlink", "imager", "leader", "spare"], ["downlink", "imager", "relay"]],
)
def test_role_priority_must_be_exactly_a_permutation_with_a_plain_message(bad):
    with pytest.raises(ValidationError, match="permutation of downlink, imager, leader"):
        _scn(role_priority=bad)


def test_default_priority_constants_agree():
    assert tuple(_scn().role_priority) == DEFAULT_PRIORITY == ("downlink", "imager", "leader")


def test_importing_scenario_does_not_import_scipy_optimize():
    code = "import sys, cubesat.scenario; print('scipy.optimize' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert out.stdout.strip() == "False", out.stderr


# --- handoff_events: pure ---------------------------------------------------------------------
PRI = ("downlink", "imager", "leader")


def test_handoff_events_only_for_critical_roles_with_the_old_holders_status():
    old = [["leader"], ["imager"], ["imager"], ["downlink"]]
    new = [[], ["imager", "leader"], ["imager"], ["downlink"]]
    got = handoff_events(old, new, ["DEAD", "NOMINAL", "NOMINAL", "NOMINAL"], PRI)
    assert got == [{"role": "leader", "from_sat": 0, "to_sat": 1, "reason": "DEAD"}]
    # the imager holder changed too (first holder 1 -> 1 here) but imagers never hand off
    moved = handoff_events([["imager"], ["imager"]], [[], ["imager"]], ["DEAD", "NOMINAL"], PRI)
    assert moved == []


def test_handoff_events_vacant_both_ways():
    gone = handoff_events([["leader"], []], [[], []], ["RADIO_SILENT", "NOMINAL"], PRI)
    assert gone == [{"role": "leader", "from_sat": 0, "to_sat": None, "reason": "RADIO_SILENT"}]
    back = handoff_events([[], []], [[], ["leader"]], ["NOMINAL", "NOMINAL"], PRI)
    assert back == [{"role": "leader", "from_sat": None, "to_sat": 1, "reason": "VACANT"}]


def test_handoff_events_order_follows_the_priority_and_no_change_means_no_event():
    old = [["leader", "downlink"], []]
    new = [[], ["downlink", "leader"]]
    got = handoff_events(old, new, ["DEAD", "NOMINAL"], PRI)
    assert [g["role"] for g in got] == ["downlink", "leader"]
    assert handoff_events(old, old, ["NOMINAL", "NOMINAL"], PRI) == []


# --- odd role sets (live scenarios) -----------------------------------------------------------
@pytest.mark.parametrize("name", ["live_2sat", "live_8sat", "live_12sat"])
def test_live_scenarios_run_and_emit_no_handoff_at_tick_zero(name):
    lines = _ticks(run_scenario_v2(_scn(name, duration_s=30.0)))
    first = lines[0]
    assert not first.get("events")
    assert [s["original_role"] for s in first["sats"]] == _scn(name).roles


def test_a_scenario_without_a_downlink_has_it_vacant_from_the_start():
    lines = _ticks(run_scenario_v2(_scn("live_2sat", duration_s=30.0)))
    assert all("downlink" not in s["roles"] for x in lines for s in x["sats"])
    assert [s["roles"] for s in lines[0]["sats"]] == [["leader"], ["imager"]]


def test_a_second_downlink_label_keeps_its_original_role_and_is_a_spare():
    first = _ticks(run_scenario_v2(_scn("live_8sat", duration_s=10.0)))[0]
    dl = [s for s in first["sats"] if s["original_role"] == "downlink"]
    assert [s["roles"] for s in dl] == [["downlink"], ["spare"]]  # lowest id keeps the role
