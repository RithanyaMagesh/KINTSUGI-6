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


def test_ring_kill_of_a_function_holder_is_vacant_for_the_consensus_rounds_only():
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


def test_star_hub_death_is_split_brain_until_the_star_reforms():
    lines = _ticks(run_scenario_v2(_scn([{"t": 100.0, "sat_id": 0, "mode": "DEAD"}], "star")))
    at = {x["t"]: x for x in lines}
    assert at[98.0]["split_brain"] == []
    brain = [x["t"] for x in lines if x["split_brain"]]
    assert brain[0] == 100.0 and set(at[100.0]["split_brain"]) == set(
        LEADER_FUNCTIONS)
    assert lines[-1]["split_brain"] == []  # singletons elect themselves at once (0 rounds)
    assert lines[-1]["components"] == [[1, 2, 3, 4, 5]]


def test_a_radio_dead_sat_never_holds_a_function():
    lines = _ticks(run_scenario_v2(_scn([{"t": 50.0, "sat_id": 0, "mode": "RADIO_FAIL"}])))
    assert lines[0]["sats"][0]["functions"]  # it held something before
    assert all(x["sats"][0]["functions"] == [] for x in lines if x["t"] >= 50.0)
    assert lines[-1]["functions_vacant"] == []


# --- engine contract ---
def test_decentral_run_is_deterministic():
    s = _scn([{"t": 100.0, "sat_id": 0, "mode": "DEAD"}])
    assert _dump(run_scenario_v2(s)) == _dump(run_scenario_v2(s))


def test_inject_mid_run_equals_a_fresh_run_with_that_injection():
    s = _scn()
    live = EngineV2(s)
    out = [live.header()] + [live.step() for _ in range(40)]
    live.inject(Failure(t=0.0, sat_id=1, mode="DEAD"))
    out += list(live.run())
    assert _dump(out) == _dump(list(EngineV2(s, injections=live.injections).run()))


def test_snapshot_with_a_pending_auction_replays_identically():
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
