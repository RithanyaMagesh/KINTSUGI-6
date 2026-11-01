"""C6: laser-comms pass-through on the wire (links, components, link events, formation shape)."""

import json
import math

import pytest

from cubesat import geo_v2
from cubesat.scenario import load_scenario
from cubesat.wire import SessionEnrich, to_messages


def _sat(i=0, status="NOMINAL"):
    return {"id": i, "role": "imager", "status": status, "r": [1.0, 2.0, 3.0],
            "v": [0.0, 0.0, 0.0], "dv_used": 0.0}


def _line(events=(), **extra):
    line = {"v": 1, "t": 10.0, "state": "NOMINAL", "coverage": 0.1, "min_sep": 50.0,
            "sats": [_sat(0), _sat(1), _sat(2)], **extra}
    if events:
        line["event"], line["events"] = events[0], list(events)
    return line


def _msgs(line):
    return to_messages(line, SessionEnrich())


def _events(line):
    return [m for m in _msgs(line) if m["type"] == "event"]


LINKS = [[0, 1, "LOCKED", 15600.5, 2.0e7], [1, 2, "ACQUIRING", 22000.0, 0.0]]


def test_links_and_components_pass_through_with_display_ids():
    st = _msgs(_line(links=LINKS, components=[[0, 1], [2]]))[0]
    assert st["links"] == [["SAT-1", "SAT-2", "LOCKED", 15600.5, 2.0e7],
                           ["SAT-2", "SAT-3", "ACQUIRING", 22000.0, 0.0]]
    assert st["components"] == [["SAT-1", "SAT-2"], ["SAT-3"]]


def test_frames_without_link_keys_gain_no_keys():
    st = _msgs(_line())[0]
    assert "links" not in st and "components" not in st


def test_non_finite_numbers_become_null_so_the_frame_still_encodes():
    st = _msgs(_line(links=[[0, 1, "LOCKED", math.nan, math.inf]], components=[[0, 1]]))[0]
    assert st["links"] == [["SAT-1", "SAT-2", "LOCKED", None, None]]
    json.dumps(st, allow_nan=False)


def test_malformed_link_rows_are_dropped_not_crashing():
    bad = [[0, 1], "x", [0, "a", "LOCKED", 1.0, 1.0], [True, 1, "LOCKED", 1.0, 1.0], None]
    st = _msgs(_line(links=bad + LINKS[:1], components=[[0, "q"], "z"]))[0]
    assert st["links"] == [["SAT-1", "SAT-2", "LOCKED", 15600.5, 2.0e7]]
    assert st["components"] == [["SAT-1"]]


def test_link_locked_sentence():
    (ev,) = _events(_line([{"type": "LINK_LOCKED", "payload": {"link": [0, 1]}}]))
    assert ev["level"] == "info" and ev["message"] == "Laser link SAT-1 to SAT-2 locked"
    assert ev["link"] == ["SAT-1", "SAT-2"]


def test_link_lost_sentences_by_reason():
    cases = {
        "sun": ("warning", "Laser link SAT-1 to SAT-2 lost: the sun is in a receiver's view"),
        "partner_down": ("warning", "Laser link SAT-1 to SAT-2 lost: a partner is down"),
        "budget": ("warning", "Laser link SAT-1 to SAT-2 lost: out of link budget"),
        "replan": ("info", "Laser link SAT-1 to SAT-2 dropped: the network re-routed"),
        "?": ("warning", "Laser link SAT-1 to SAT-2 lost"),
    }
    for reason, (level, text) in cases.items():
        payload = {"link": [0, 1], "reason": reason}
        (ev,) = _events(_line([{"type": "LINK_LOST", "payload": payload}]))
        assert (ev["level"], ev["message"]) == (level, text)
        assert ev["link"] == ["SAT-1", "SAT-2"] and ev["reason"] == reason


def test_partition_sentence():
    payload = {"components": [[0, 1], [2]]}
    (ev,) = _events(_line([{"type": "PARTITION", "payload": payload}]))
    assert ev["level"] == "warning"
    assert ev["message"] == "Swarm split into 2 groups: SAT-1, SAT-2 | SAT-3"
    assert ev["components"] == [["SAT-1", "SAT-2"], ["SAT-3"]]


def test_junk_link_payloads_degrade_the_message_not_the_driver():
    for etype in ("LINK_LOCKED", "LINK_LOST"):
        (ev,) = _events(_line([{"type": etype, "payload": {"link": "x"}}]))
        assert ev["message"].startswith("Laser link") and "link" not in ev
    (ev,) = _events(_line([{"type": "PARTITION", "payload": {"components": 5}}]))
    assert ev["message"] == "Swarm split" and "components" not in ev


def test_isolated_detection_says_cut_off_not_failed():
    payload = {"sat_id": 2, "mode": None, "t_fail": 6.0, "t_detect": 10.0, "cause": "isolated"}
    enrich = SessionEnrich()
    line = _line([{"type": "FAILURE_DETECTED", "payload": payload}])
    (ev,) = [m for m in to_messages(line, enrich) if m["type"] == "event"]
    assert ev["level"] == "warning" and ev["sat_id"] == "SAT-3"
    assert ev["message"] == "SAT-3 cut off: no laser link reaches it, so the swarm cannot hear it"
    assert ev["cause"] == "isolated"
    assert enrich.detection_latency_s is None  # isolation is not a failure detection


def test_huge_integer_in_a_link_row_becomes_null_not_overflow():
    st = _msgs(_line(links=[[0, 1, "LOCKED", 1.0, 10**400]]))[0]
    assert st["links"] == [["SAT-1", "SAT-2", "LOCKED", 1.0, None]]


def test_partition_with_one_valid_component_left_says_only_swarm_split():
    payload = {"components": [[0.0], [1]]}
    (ev,) = _events(_line([{"type": "PARTITION", "payload": payload}]))
    assert ev["message"] == "Swarm split" and "components" not in ev


def test_v2_hello_carries_the_formation_shape():
    scn = load_scenario("data/scenarios/formation_helix_6sat.json")
    assert geo_v2.hello_fields(scn)["formation_shape"] == "helix"


def test_a_real_laser_run_streams_links_and_named_link_events():
    from cubesat.scenario import Scenario
    from cubesat.sim_v2 import run_scenario_v2

    d = json.loads(open("data/scenarios/nominal.json").read())
    d.update(engine="v2", duration_s=160.0, comms={"model": "laser", "topology": "star"},
             failures=[{"sat_id": 0, "t": 20.0, "mode": "DEAD"}])
    enrich, msgs = SessionEnrich(), []
    for line in run_scenario_v2(Scenario.model_validate(d)):
        msgs += to_messages(line, enrich)
    states = [m for m in msgs if m["type"] == "sim_state" and m["sats"]]
    assert all("links" in m and "components" in m for m in states)
    json.dumps(msgs, allow_nan=False)
    texts = {m["message"].split(" ")[0] for m in msgs if m["type"] == "event"}
    assert not texts & {"LINK_LOCKED", "LINK_LOST", "PARTITION"}  # all got sentences
    assert any(m["message"].startswith("Swarm split") for m in msgs if m["type"] == "event")


# --- C4 keys (decentral authority) ---------------------------------------------------------
def test_decentral_tick_keys_pass_through_and_sats_carry_functions():
    line = _line(consensus_rounds=20, split_brain=["time_sync"], functions_vacant=[])
    line["sats"][1]["functions"] = ["time_sync", "ground_relay"]
    st = _msgs(line)[0]
    assert (st["consensus_rounds"], st["split_brain"], st["functions_vacant"]) == \
        (20, ["time_sync"], [])
    assert st["sats"][1]["functions"] == ["time_sync", "ground_relay"]
    assert "functions" not in st["sats"][0]


def test_central_frames_carry_no_decentral_keys():
    st = _msgs(_line())[0]
    assert not {"consensus_rounds", "split_brain", "functions_vacant"} & set(st)


def _handoff(**payload):
    return _events(_line([{"type": "FUNCTION_HANDOFF", "payload": payload}]))[0]


def test_function_handoff_sentences():
    ev = _handoff(function="time_sync", **{"from": [0], "to": [2]})
    assert ev["level"] == "info"
    assert ev["message"] == "Consensus auction: time sync moved from SAT-1 to SAT-3"
    assert (ev["function"], ev["from"], ev["to"]) == ("time_sync", ["SAT-1"], ["SAT-3"])
    ev = _handoff(function="failure_detection", **{"from": [], "to": [1]})
    assert ev["message"] == "Consensus auction: SAT-2 took over failure detection"
    ev = _handoff(function="ground_relay", **{"from": [0], "to": []})
    assert ev["level"] == "warning"
    assert ev["message"] == "ground relay is vacant: no satellite holds it (was SAT-1)"
    ev = _handoff(function="time_sync", **{"from": [0], "to": [1, 3]})
    assert ev["level"] == "warning"
    assert ev["message"] == ("Consensus auction: time sync moved from SAT-1 to SAT-2, SAT-4 "
                             "(split-brain: one holder per group)")


def test_junk_function_handoff_degrades_the_message():
    ev = _handoff(function=5, **{"from": "x"})
    assert ev["message"] == "Consensus auction: a leader function changed holder"
    assert "function" not in ev


def test_a_real_decentral_run_streams_functions_and_handoff_sentences():
    from cubesat.scenario import Scenario
    from cubesat.sim_v2 import run_scenario_v2

    d = json.loads(open("data/scenarios/nominal.json").read())
    d.update(engine="v2", duration_s=200.0, comms={"model": "laser"},
             recovery={"authority": "decentral"},
             failures=[{"sat_id": 0, "t": 100.0, "mode": "DEAD"}])
    enrich, msgs = SessionEnrich(), []
    for line in run_scenario_v2(Scenario.model_validate(d)):
        msgs += to_messages(line, enrich)
    json.dumps(msgs, allow_nan=False)
    states = [m for m in msgs if m["type"] == "sim_state" and m["sats"]]
    assert all("consensus_rounds" in m and "functions" in m["sats"][0] for m in states)
    events = [m for m in msgs if m["type"] == "event"]
    assert not any(m["message"] == "FUNCTION_HANDOFF" for m in events)
    assert any(m["message"].startswith("Consensus auction:") for m in events)
    assert not any("CBBA" in m["message"] for m in events)


@pytest.mark.slow
@pytest.mark.parametrize("name,expect", [
    ("decentral_leader_kill_6sat", "Consensus auction:"),
    ("central_star_leader_kill_6sat", "Swarm split into"),
])
def test_track_c_demo_scenarios_stream_cleanly_with_named_events(name, expect):
    """The two T2 demo scenarios (leader kill, decentral mesh vs central star) through the wire."""
    from cubesat.scenario import load_scenario
    from cubesat.sim_v2 import run_scenario_v2

    enrich, msgs = SessionEnrich(), []
    for line in run_scenario_v2(load_scenario(f"data/scenarios/{name}.json")):
        msgs += to_messages(line, enrich)
    json.dumps(msgs, allow_nan=False)
    events = [m["message"] for m in msgs if m["type"] == "event"]
    raw = {"LINK_LOCKED", "LINK_LOST", "PARTITION", "FUNCTION_HANDOFF"}
    assert not raw & set(events) and not any("CBBA" in e for e in events)
    assert any(e.startswith(expect) for e in events)
    assert any("cut off" in e for e in events) == name.startswith("central_star")
