"""Track C2: laser crosslinks in EngineV2 (opt-in `comms.model = "laser"`)."""

import json
import math
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from cubesat import isl
from cubesat.comms_v2 import sun_lvlh
from cubesat.scenario import Failure, Scenario
from cubesat.scenario_models import LaserTerminal
from cubesat.sim_v2 import EngineV2, run_scenario_v2

ROOT = Path(__file__).resolve().parents[2]
NOMINAL = json.loads((ROOT / "data" / "scenarios" / "nominal.json").read_text())
SENSOR = {"fov_half_angle_deg": 1.5, "grid_step_km": 5.0, "grid_extent_km": 5.0}
LASER = {"model": "laser"}
K_DT = 2.0 * 2.0  # (missed_ticks_k - 1) * dt for the default K = 3, dt = 2 s


def _scn(failures=(), comms=LASER, **kw) -> Scenario:
    d = {**NOMINAL, "engine": "v2", "duration_s": 300.0, "sensor": SENSOR, "failures": failures}
    if comms is not None:
        d["comms"] = comms
    return Scenario.model_validate({**d, **kw})


def _ticks(lines):
    return [x for x in lines if "sats" in x]


def _events(lines, kind):
    return [(x["t"], e["payload"]) for x in _ticks(lines) for e in x.get("events", [])
            if e["type"] == kind]


def _dump(lines):
    return json.dumps(lines, sort_keys=True)


# --- defaults inert, validation ---
def test_no_comms_and_ideal_comms_give_the_same_log_without_link_keys():
    base = run_scenario_v2(_scn(comms=None))
    assert _dump(run_scenario_v2(_scn(comms={"model": "ideal"}))) == _dump(base)
    assert all({"links", "components"}.isdisjoint(x) for x in base)


def test_laser_requires_engine_v2():
    with pytest.raises(ValidationError, match="engine"):
        Scenario.model_validate({**NOMINAL, "comms": LASER})
    Scenario.model_validate({**NOMINAL, "comms": {"model": "ideal"}})  # ideal is fine on v1


def test_terminal_defaults_mirror_isl_terminal():
    assert isl.Terminal(**LaserTerminal().model_dump()) == isl.Terminal()


# --- links in the log ---
def test_nominal_laser_run_is_one_locked_component_and_declares_nobody():
    lines = _ticks(run_scenario_v2(_scn()))
    for x in lines:
        assert x["components"] == [[0, 1, 2, 3, 4, 5]]
        assert all(state == isl.LOCKED and rate > 0 for _, _, state, _, rate in x["links"])
        deg = [sum(i in link[:2] for link in x["links"]) for i in range(6)]
        assert max(deg) <= 2
    assert not _events(lines, "FAILURE_DETECTED") and not _events(lines, "PARTITION")


def test_dead_partner_drops_the_link_the_same_tick_and_a_new_link_locks_after_acquisition():
    lines = _ticks(run_scenario_v2(_scn([{"t": 100.0, "sat_id": 0, "mode": "DEAD"}])))
    at = {x["t"]: x for x in lines}
    lost = _events(lines, "LINK_LOST")
    assert lost and {t for t, _ in lost} == {100.0}
    assert all(0 in p["link"] and p["reason"] == "partner_down" for _, p in lost)
    assert all(0 not in link[:2] for link in at[100.0]["links"])
    new = [link[:2] for link in at[100.0]["links"] if link[2] == isl.ACQUIRING]
    assert new, "the two orphaned neighbours must start a new link"
    t_lock = 100.0 + (math.ceil(30.0 / 2.0) - 1) * 2.0
    for i, j in new:
        states = {x["t"]: s for x in lines for a, b, s, _, _ in x["links"] if (a, b) == (i, j)}
        assert states[t_lock - 2.0] == isl.ACQUIRING and states[t_lock] == isl.LOCKED
        assert (t_lock, {"link": [i, j]}) in _events(lines, "LINK_LOCKED")
    # ring/mesh: losing a node does not isolate anyone, only sat 0 is declared
    assert [p["sat_id"] for _, p in _events(lines, "FAILURE_DETECTED")] == [0]


def test_star_hub_death_isolates_every_leaf_and_they_are_declared_after_k_ticks():
    lines = _ticks(run_scenario_v2(_scn([{"t": 100.0, "sat_id": 0, "mode": "DEAD"}],
                                        comms={"model": "laser", "topology": "star"})))
    assert len(lines[0]["links"]) == 5  # every sat links to the hub (sat 0 holds leader)
    parts = _events(lines, "PARTITION")
    assert parts[0] == (100.0, {"components": [[1], [2], [3], [4], [5]]})
    det = {p["sat_id"]: (t, p) for t, p in _events(lines, "FAILURE_DETECTED")}
    assert det[0][0] == 100.0 + K_DT
    for leaf in range(1, 6):
        assert det[leaf][0] == 100.0 + K_DT and det[leaf][1]["cause"] == "isolated"
    # the new leader becomes the hub and the star re-forms after an acquisition
    hub = lines[-1]["sats"].index(next(s for s in lines[-1]["sats"] if "leader" in s["roles"]))
    assert hub != 0 and lines[-1]["components"] == [[1, 2, 3, 4, 5]]


def test_radio_fail_drops_links_and_declares_only_that_sat():
    lines = _ticks(run_scenario_v2(_scn([{"t": 50.0, "sat_id": 3, "mode": "RADIO_FAIL"}])))
    assert all(3 not in link[:2] for link in lines[-1]["links"])
    assert [p["sat_id"] for _, p in _events(lines, "FAILURE_DETECTED")] == [3]
    assert lines[-1]["components"] == [[0, 1, 2, 4, 5]]


def test_sun_in_the_cone_blinds_the_link():
    two = {"roles": ["leader", "downlink"],
           "formation": {**NOMINAL["formation"], "n_slots": 2}, "duration_s": 20.0}
    s = _scn(**two)
    eng = EngineV2(s)
    sun = sun_lvlh(eng.X[0], s.chief.epoch_utc, 0.0)
    start = np.zeros((2, 6))
    start[0, :3] = [1000.0, 0.0, 0.0]
    aligned, off = start.copy(), start.copy()
    aligned[1, :3] = start[0, :3] + 5000.0 * sun
    off[1, :3] = start[0, :3] + 5000.0 * np.cross(sun, [0.0, 0.0, 1.0]) / np.linalg.norm(
        np.cross(sun, [0.0, 0.0, 1.0]))
    blind = _ticks(list(EngineV2(s, initial_lvlh=aligned).run()))
    clear = _ticks(list(EngineV2(s, initial_lvlh=off).run()))
    assert blind[0]["links"][0][2] == isl.DOWN and blind[0]["components"] == [[0], [1]]
    assert _events(blind, "LINK_LOST")[0] == (0.0, {"link": [0, 1], "reason": "sun"})
    assert clear[0]["links"][0][2] == isl.LOCKED and clear[0]["components"] == [[0, 1]]


# --- engine contract ---
def test_laser_run_is_deterministic():
    s = _scn([{"t": 100.0, "sat_id": 0, "mode": "DEAD"}])
    assert _dump(run_scenario_v2(s)) == _dump(run_scenario_v2(s))


def test_inject_mid_run_equals_a_fresh_run_with_that_injection():
    s = _scn()
    live = EngineV2(s)
    out = [live.header()] + [live.step() for _ in range(40)]
    live.inject(Failure(t=0.0, sat_id=2, mode="DEAD"))  # clamps to now (t = 80 s)
    out += list(live.run())
    assert _dump(out) == _dump(list(EngineV2(s, injections=live.injections).run()))


def test_snapshot_mid_acquisition_replays_identically():
    s = _scn([{"t": 100.0, "sat_id": 0, "mode": "DEAD"}])
    a = EngineV2(s)
    for _ in range(55):  # t = 108 s: the replacement link is ACQUIRING
        line = a.step()
    assert any(link[2] == isl.ACQUIRING for link in line["links"])
    blob = a.snapshot()
    tail_a = list(a.run())
    b = EngineV2(s)
    b.restore(blob)
    assert _dump(list(b.run())) == _dump(tail_a)


def test_restore_without_comms_state_raises_and_changes_nothing():
    s = _scn()
    a = EngineV2(s)
    for _ in range(5):
        a.step()
    doc = json.loads(a.snapshot())
    del doc["state"]["comms"]
    before = a.snapshot()
    with pytest.raises(ValueError):
        a.restore(json.dumps(doc).encode())
    assert a.snapshot() == before


def test_a_reheard_sat_is_undeclared_so_its_real_death_is_detected_later():
    fails = [{"t": 100.0, "sat_id": 0, "mode": "DEAD"}, {"t": 200.0, "sat_id": 3, "mode": "DEAD"}]
    lines = _ticks(run_scenario_v2(_scn(fails, comms={"model": "laser", "topology": "star"})))
    det3 = [(t, p["mode"]) for t, p in _events(lines, "FAILURE_DETECTED") if p["sat_id"] == 3]
    assert det3 == [(100.0 + K_DT, ""), (200.0 + K_DT, "DEAD")]


# --- review fixes ---
def test_star_without_a_leader_holder_uses_the_lowest_talking_sat_as_hub():
    roles = ["imager"] * 5 + ["downlink"]
    lines = _ticks(run_scenario_v2(_scn(comms={"model": "laser", "topology": "star"},
                                        roles=roles, duration_s=40.0)))
    assert lines[0]["components"] == [[0, 1, 2, 3, 4, 5]]
    assert {link[0] for link in lines[0]["links"]} == {0}
    assert not _events(lines, "FAILURE_DETECTED")


@pytest.mark.parametrize("bad", [[0, 99, "LOCKED", 0.0], [1, 0, "LOCKED", 0.0],
                                 [0, 1, "BOGUS", 0.0]])
def test_restore_rejects_a_malformed_link(bad):
    a = EngineV2(_scn())
    a.step()
    doc = json.loads(a.snapshot())
    doc["state"]["comms"]["links"][0] = bad
    before = a.snapshot()
    with pytest.raises(ValueError):
        a.restore(json.dumps(doc).encode())
    assert a.snapshot() == before


def test_absurd_terminal_sizes_are_rejected_at_validation():
    with pytest.raises(ValidationError):
        _scn(comms={"model": "laser", "terminal": {"d_tx_m": 1e160}})


def test_isolated_detection_reports_when_isolation_began():
    lines = _ticks(run_scenario_v2(_scn([{"t": 100.0, "sat_id": 0, "mode": "DEAD"}],
                                        comms={"model": "laser", "topology": "star"})))
    leaf = [p for _, p in _events(lines, "FAILURE_DETECTED") if p["sat_id"] == 1][0]
    assert leaf["t_fail"] == 100.0 and leaf["cause"] == "isolated"


def test_partition_at_the_first_tick_is_reported():
    two = {"roles": ["leader", "downlink"],
           "formation": {**NOMINAL["formation"], "n_slots": 2}, "duration_s": 6.0}
    s = _scn(**two)
    sun = sun_lvlh(EngineV2(s).X[0], s.chief.epoch_utc, 0.0)
    start = np.zeros((2, 6))
    start[0, :3] = [1000.0, 0.0, 0.0]
    start[1, :3] = start[0, :3] + 5000.0 * sun
    lines = _ticks(list(EngineV2(s, initial_lvlh=start).run()))
    assert _events(lines, "PARTITION")[0] == (0.0, {"components": [[0], [1]]})


@pytest.mark.slow
def test_one_orbit_of_nominal_sun_splits_the_ring_and_isolates_a_star_leaf():
    """Measured (GATES.md C2): one orbit of data/scenarios/nominal.json, engine v2, laser, no
    failures. The 2-terminal ring loses two parallel links to the 3 deg sun cone twice per
    orbit and splits in two for 160 s each time; the star isolates sat 3 (declared, cause
    isolated). A finding against the "ring survives" story, reported, not tuned away."""
    full = {"duration_s": NOMINAL["duration_s"], "sensor": NOMINAL["sensor"]}
    mesh = _ticks(run_scenario_v2(_scn(**full)))
    star = _ticks(run_scenario_v2(_scn(comms={"model": "laser", "topology": "star"}, **full)))
    split = [t for t, _ in _events(mesh, "PARTITION")]
    assert split == [1352.0, 4190.0]
    assert _events(mesh, "PARTITION")[0][1] == {"components": [[0, 1, 5], [2, 3, 4]]}
    assert sum(len(x["components"]) > 1 for x in mesh) * 2.0 == 320.0
    assert not _events(mesh, "FAILURE_DETECTED")
    det = [(t, p["sat_id"], p.get("cause")) for t, p in _events(star, "FAILURE_DETECTED")]
    assert det == [(1356.0, 3, "isolated"), (4194.0, 3, "isolated")]
