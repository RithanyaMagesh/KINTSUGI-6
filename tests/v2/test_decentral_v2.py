"""Track C4: decentralised leader functions in EngineV2 (`recovery.authority = "decentral"`)."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from cubesat.decentral import LEADER_FUNCTIONS
from cubesat.scenario import Failure, Scenario
from cubesat.sim_v2 import EngineV2, run_scenario_v2

ROOT = Path(__file__).resolve().parents[2]
NOMINAL = json.loads((ROOT / "data" / "scenarios" / "nominal.json").read_text())
SENSOR = {"fov_half_angle_deg": 1.5, "grid_step_km": 5.0, "grid_extent_km": 5.0}
DECENTRAL = {"authority": "decentral"}


def _scn(failures=(), topology="mesh", recovery=DECENTRAL, **kw) -> Scenario:
    d = {**NOMINAL, "engine": "v2", "duration_s": 300.0, "sensor": SENSOR, "failures": failures,
         "comms": {"model": "laser", "topology": topology}}
    if recovery is not None:
        d["recovery"] = recovery
    return Scenario.model_validate({**d, **kw})


def _ticks(lines):
    return [x for x in lines if "sats" in x]


def _events(lines, kind):
    return [(x["t"], e["payload"]) for x in _ticks(lines) for e in x.get("events", [])
            if e["type"] == kind]


def _holders(line):
    return {f: [s["id"] for s in line["sats"] if f in s["functions"]] for f in LEADER_FUNCTIONS}


def _dump(lines):
    return json.dumps(lines, sort_keys=True)


def test_decentral_needs_laser_comms_and_central_is_inert():
    with pytest.raises(ValidationError, match="laser"):
        Scenario.model_validate({**NOMINAL, "engine": "v2", "recovery": DECENTRAL})
    base = run_scenario_v2(_scn(recovery=None))
    assert _dump(run_scenario_v2(_scn(recovery={"authority": "central"}))) == _dump(base)
    assert all("functions" not in s for x in _ticks(base) for s in x["sats"])


def test_connected_mesh_holds_every_function_once_and_no_leader_role():
    lines = _ticks(run_scenario_v2(_scn()))
    for x in lines:
        assert all(len(h) == 1 for h in _holders(x).values())
        assert x["split_brain"] == [] and x["functions_vacant"] == []
        assert all("leader" not in s["roles"] for s in x["sats"])
        assert any("downlink" in s["roles"] for s in x["sats"])
    assert lines[0]["consensus_rounds"] > 0
    assert max(len(s["functions"]) for s in lines[0]["sats"]) <= 2  # load is spread


def test_ring_leader_kill_no_vacancy_after_consensus_rounds_and_no_split_brain():
    """Ring (mesh) leader kill: the dead holder's functions are vacant from the death tick for
    exactly consensus_rounds ticks (one hop per tick: assumption), never after; no split-brain."""
    probe = _ticks(run_scenario_v2(_scn(duration_s=4.0)))[0]
    victim = max(probe["sats"], key=lambda s: (len(s["functions"]), -s["id"]))["id"]
    lines = _ticks(run_scenario_v2(_scn([{"t": 100.0, "sat_id": victim, "mode": "DEAD"}])))
    at = {x["t"]: x for x in lines}
    lost = probe["sats"][victim]["functions"]
    assert lost and sorted(at[100.0]["functions_vacant"]) == sorted(lost)
    hand = _events(lines, "FUNCTION_HANDOFF")
    t_done = hand[0][0]
    rounds = at[t_done]["consensus_rounds"]
    assert rounds > 0 and t_done == 100.0 + rounds * 2.0  # one hop per tick: assumption
    assert {p["function"] for _, p in hand if victim in p["from"]} == set(lost)
    for x in lines:
        assert (x["functions_vacant"] == []) == (not 100.0 <= x["t"] < t_done)
        assert x["split_brain"] == []
        if x["t"] >= 100.0:
            assert x["sats"][victim]["functions"] == []


def test_star_leader_kill_every_function_split_brain_until_the_replan_then_resolved():
    """Star hub kill: from the death tick every function is split-brain (each singleton elects
    itself at once, 0 rounds) without a gap, until the star re-forms and the auction lands;
    then resolved for the rest of the run."""
    lines = _ticks(run_scenario_v2(_scn([{"t": 100.0, "sat_id": 0, "mode": "DEAD"}], "star")))
    brain = [x["t"] for x in lines if x["split_brain"]]
    assert brain == [100.0 + 2.0 * k for k in range(len(brain))]  # one unbroken window
    assert len(brain) == 23  # 100 -> 144 s; resolved from 146 s
    assert all(x["split_brain"] == list(LEADER_FUNCTIONS) for x in lines if x["t"] in brain)
    assert all(x["functions_vacant"] == [] for x in lines)
    assert lines[-1]["components"] == [[1, 2, 3, 4, 5]]


def test_a_radio_dead_sat_never_holds_a_function():
    lines = _ticks(run_scenario_v2(_scn([{"t": 50.0, "sat_id": 0, "mode": "RADIO_FAIL"}])))
    assert lines[0]["sats"][0]["functions"]  # it held something before
    assert all(x["sats"][0]["functions"] == [] for x in lines if x["t"] >= 50.0)
    assert lines[-1]["functions_vacant"] == []


# --- engine contract ---
def test_decentral_run_is_byte_identical_twice():
    s = _scn([{"t": 100.0, "sat_id": 0, "mode": "DEAD"}])
    assert _dump(run_scenario_v2(s)) == _dump(run_scenario_v2(s))


def test_inject_mid_run_equals_a_fresh_run_with_that_injection():
    s = _scn()
    live = EngineV2(s)
    out = [live.header()] + [live.step() for _ in range(40)]
    live.inject(Failure(t=0.0, sat_id=1, mode="DEAD"))
    out += list(live.run())
    assert _dump(out) == _dump(list(EngineV2(s, injections=live.injections).run()))


def test_snapshot_restore_mid_auction_replays_identically():
    s = _scn([{"t": 100.0, "sat_id": 0, "mode": "DEAD"}])
    a = EngineV2(s)
    for _ in range(51):  # t = 100 s: the auction after the death is still converging
        line = a.step()
    assert line["functions_vacant"]
    blob = a.snapshot()
    tail_a = list(a.run())
    b = EngineV2(s)
    b.restore(blob)
    assert _dump(list(b.run())) == _dump(tail_a)


def test_restore_without_function_state_raises_and_changes_nothing():
    a = EngineV2(_scn())
    a.step()
    doc = json.loads(a.snapshot())
    del doc["state"]["functions"]
    before = a.snapshot()
    with pytest.raises(ValueError):
        a.restore(json.dumps(doc).encode())
    assert a.snapshot() == before


# --- review fixes ---
def test_star_decentral_with_the_leader_label_off_sat_0_is_quiet_and_holders_are_sorted():
    roles = ["imager", "imager", "leader", "imager", "imager", "downlink"]
    lines = _ticks(run_scenario_v2(_scn(topology="star", roles=roles, duration_s=60.0)))
    assert all(not x.get("events") for x in lines)
    assert {link[0] for link in lines[0]["links"]} == {0}  # hub = lowest talking sat from t=0
    star = _ticks(run_scenario_v2(_scn([{"t": 100.0, "sat_id": 0, "mode": "DEAD"}], "star")))
    for _, p in _events(star, "FUNCTION_HANDOFF"):
        assert p["from"] == sorted(p["from"]) and p["to"] == sorted(p["to"])


@pytest.mark.parametrize("patch", [{"holders": {}}, {"rounds": -5}, {"dirty": "no"},
                                   {"holders": {f: [1.7] for f in LEADER_FUNCTIONS}}])
def test_restore_rejects_malformed_function_state(patch):
    a = EngineV2(_scn())
    for _ in range(3):
        a.step()
    doc = json.loads(a.snapshot())
    doc["state"]["functions"].update(patch)
    before = a.snapshot()
    with pytest.raises(ValueError):
        a.restore(json.dumps(doc).encode())
    assert a.snapshot() == before


def test_measured_vacancy_and_split_brain_seconds_for_a_sat0_kill():
    """GATES.md C4 numbers (a count of 2 s ticks, one consensus hop per tick: assumption).
    Mesh: 38 s with failure_detection vacant (19 rounds on the broken ring), no split-brain.
    Star: no vacancy (each singleton elects itself), 46 s with all six functions split-brain
    until the star re-forms around sat 1 and the auction lands."""
    out = {}
    for topo in ("mesh", "star"):
        lines = _ticks(run_scenario_v2(_scn([{"t": 100.0, "sat_id": 0, "mode": "DEAD"}], topo)))
        vac = sum(bool(x["functions_vacant"]) for x in lines) * 2.0
        brain = sum(bool(x["split_brain"]) for x in lines) * 2.0
        out[topo] = (vac, brain, len(_events(lines, "FUNCTION_HANDOFF")))
    assert out == {"mesh": (38.0, 0.0, 8), "star": (0.0, 46.0, 12)}


def test_defaults_off_leave_the_v2_log_byte_identical():
    """No comms / recovery keys = comms ideal = recovery central (no laser): the same bytes.
    The golden pins (tests/test_cli.py, test_failure_modes.py, test_policy_selection.py,
    tests/v2 hash tests) cover the committed scenarios themselves."""
    d = {**NOMINAL, "engine": "v2", "duration_s": 300.0, "sensor": SENSOR,
         "failures": [{"t": 100.0, "sat_id": 0, "mode": "DEAD"}]}
    base = _dump(run_scenario_v2(Scenario.model_validate(d)))
    for extra in ({"comms": {"model": "ideal"}}, {"recovery": {"authority": "central"}},
                  {"comms": {"model": "ideal"}, "recovery": {"authority": "central"}}):
        assert _dump(run_scenario_v2(Scenario.model_validate({**d, **extra}))) == base
