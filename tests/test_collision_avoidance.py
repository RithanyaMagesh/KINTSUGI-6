"""Continuous collision-avoidance (evasive maneuver) tests (BACKEND_SPEC
Addendum v1.2 item 5, GATES.md 2026-10-26 decision).

The evasion monitor is a DISCRETE BOUNDED MANEUVER, explicitly NOT potential
fields (MASTER_PROMPT 2 lock preserved; min_sep stays logged every tick). It
is additive and default-inert by GEOMETRY, not by a flag: the 1000 m default
radius sits below every measured clearance on committed scenarios (P0 worst
survivor-dead 1322.6 m, G4 worst min_sep 3095.1 m -- GATES.md), so canonical
runs stay byte-identical (pinned separately by tests/test_cli.py,
tests/test_failure_modes.py, tests/test_policy_selection.py) and emit zero
EVASIVE_MANEUVER events.

The firing data comes from the committed data/scenarios/proximity_stress.json:
a small 2-slot formation (radial amplitude 0.3 km) whose passive 2:1 relative
cycle dips to 2*A*sqrt(2) = 848.5 m -- inside the 1000 m sphere -- at t = 0
and every half orbit, so both members of the NOMINAL-NOMINAL close pair start
bounded evasion episodes; from t = 600 the dead sat coasts ballistically as a
hazard (AGENTS.md 5) and the survivor evades it on each close pass. No RNG,
no wall clock (AGENTS.md 2), so module-scoped fixtures are exact replays.
"""

import json
import math
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from cubesat.hcw import mean_motion, propagate_controlled
from cubesat.scenario import Safety, Scenario, load_scenario
from cubesat.sim import run_scenario
from cubesat.wire import SessionEnrich, to_messages

ROOT = Path(__file__).resolve().parents[1]
PROXIMITY = ROOT / "data" / "scenarios" / "proximity_stress.json"
NOMINAL = ROOT / "data" / "scenarios" / "nominal.json"
TWO_FAILURE = ROOT / "data" / "scenarios" / "two_failure.json"


def _serialized(lines) -> str:
    """The exact cubesat.run JSONL serialization (cubesat/run.py:44)."""
    return "".join(json.dumps(line, sort_keys=True) + "\n" for line in lines)


def _tick_lines(lines):
    return [line for line in lines if line["state"] not in ("INIT", "SUMMARY")]


def _events(lines, event_type):
    return [
        (line["t"], line["event"]["payload"])
        for line in lines
        if "event" in line and line["event"]["type"] == event_type
    ]


def _line_at(ticks, t):
    return next(line for line in ticks if line["t"] == t)


@pytest.fixture(scope="module")
def stress_scenario():
    return load_scenario(PROXIMITY)


@pytest.fixture(scope="module")
def stress_lines(stress_scenario):
    return run_scenario(stress_scenario)


@pytest.fixture(scope="module")
def nominal_lines():
    return run_scenario(load_scenario(NOMINAL))


@pytest.fixture(scope="module")
def two_failure_lines():
    return run_scenario(load_scenario(TWO_FAILURE))


def test_evasion_fires_on_synthetic_proximity(stress_scenario, stress_lines):
    """The tuned stress geometry forces a range below the 1000 m evade sphere
    (small n_slots on a tight passive ellipse -- the same post-replan keep-out
    geometry the P2 report measured), the monitor starts an episode, and one
    EVASIVE_MANEUVER event {sat_id, other_id, range_m, t} rides the log FIFO;
    every triggering range is inside the radius and measured from real states."""
    evasions = _events(stress_lines, "EVASIVE_MANEUVER")
    assert evasions, "evasion never fired on the stress scenario"
    radius = stress_scenario.safety.evade_radius_m
    ticks = _tick_lines(stress_lines)
    for _t_pop, payload in evasions:
        assert payload["range_m"] < radius
        assert payload["sat_id"] != payload["other_id"]
        # The payload range is measured on the log states at the detection tick.
        measured = _line_at(ticks, payload["t"])
        i, j = payload["sat_id"], payload["other_id"]
        assert measured["sats"][i]["status"] in ("NOMINAL", "DEGRADED")
        r = math.dist(measured["sats"][i]["r"], measured["sats"][j]["r"])
        assert r == pytest.approx(payload["range_m"], abs=1e-6)
        assert r < radius
        # The event is appended during the between-step AFTER the payload-t line
        # is emitted, so it pops on that tick or later (FIFO: at most one event
        # pops per tick line, and a same-tick sibling event can delay it).
        assert _t_pop >= payload["t"] + stress_scenario.dt_s


def test_evasion_direction_away_and_bounded(stress_scenario, stress_lines):
    """For the first fired episode the applied acceleration is exactly
    a_max * (r_i - r_j)/||r_i - r_j||: ||u|| <= a_max (bounded burn) and
    dot(u, r_i - r_j) > 0 (away from the intruder). Verified by reconstructing
    the episode's first step from the log states with the exact controlled
    propagator -- the logged next state proves which u actually ran."""
    scenario = stress_scenario
    dt = scenario.dt_s
    n = mean_motion(scenario.chief.altitude_km * 1000.0)
    a_max = scenario.a_max_mps2
    ticks = _tick_lines(stress_lines)
    _t_pop, payload = _events(stress_lines, "EVASIVE_MANEUVER")[0]
    i, j = payload["sat_id"], payload["other_id"]
    cur = _line_at(ticks, payload["t"])
    nxt = _line_at(ticks, payload["t"] + dt)

    ri = np.array(cur["sats"][i]["r"], dtype=float)
    rj = np.array(cur["sats"][j]["r"], dtype=float)
    d = ri - rj
    u = a_max * d / float(np.linalg.norm(d))
    assert float(np.linalg.norm(u)) <= a_max * (1.0 + 1e-12), "burn exceeded a_max"
    assert float(np.dot(u, d)) > 0.0, "burn did not point away from the intruder"

    expected = propagate_controlled(
        np.concatenate((ri, np.array(cur["sats"][i]["v"], dtype=float))), u, dt, n
    )
    got = np.concatenate(
        (np.array(nxt["sats"][i]["r"], dtype=float),
         np.array(nxt["sats"][i]["v"], dtype=float))
    )
    assert np.allclose(got, expected, rtol=1e-9, atol=1e-9), (
        "logged step does not match the a_max away-from-intruder burn"
    )


def test_evasion_dv_accounted(stress_scenario, stress_lines):
    """The evading sat's dv_used grows by ~a_max * evade_ticks * dt across one
    full episode: the bounded burn replaces PD seat-holding for exactly
    evade_ticks steps and dv_used is logged before each tick's step."""
    scenario = stress_scenario
    dt = scenario.dt_s
    a_max = scenario.a_max_mps2
    ticks = _tick_lines(stress_lines)
    _t_pop, payload = _events(stress_lines, "EVASIVE_MANEUVER")[0]
    i = payload["sat_id"]
    t0 = payload["t"]
    t_end = t0 + scenario.safety.evade_ticks * dt
    dv0 = _line_at(ticks, t0)["sats"][i]["dv_used"]
    dv1 = _line_at(ticks, t_end)["sats"][i]["dv_used"]
    expected = a_max * scenario.safety.evade_ticks * dt
    print(
        f"test_evasion_dv_accounted: episode dv = {dv1 - dv0:.4f} m/s over "
        f"{scenario.safety.evade_ticks} ticks (a_max*ticks*dt = {expected:.4f} m/s)"
    )
    assert dv1 - dv0 == pytest.approx(expected, rel=1e-6)


def test_evasion_double_run_byte_identical(stress_scenario):
    """AGENTS.md invariant 2 on the new family: same scenario + seed =>
    byte-identical JSONL, evasion episodes included (run.py serialization)."""
    first = _serialized(run_scenario(stress_scenario))
    second = _serialized(run_scenario(stress_scenario))
    assert first == second


def test_evasion_inert_on_canonical_scenarios(nominal_lines, two_failure_lines):
    """Default-inertness is geometric (Addendum v1.2 item 5): no canonical
    scenario ever comes within the 1000 m default radius, so the nominal and
    two_failure runs emit ZERO EVASIVE_MANEUVER events."""
    for lines in (nominal_lines, two_failure_lines):
        assert _events(lines, "EVASIVE_MANEUVER") == []


def test_safety_block_defaults():
    """Safety defaults exactly as specced (Addendum v1.2 item 5): enabled,
    1000 m radius, 25 ticks; every Scenario carries the block by default; the
    field constraints (radius > 0, ticks >= 1) are enforced by pydantic."""
    safety = Safety()
    assert safety.evasion_enabled is True
    assert safety.evade_radius_m == 1000.0
    assert safety.evade_ticks == 25

    payload = {
        "name": "safety_defaults",
        "seed": 0,
        "duration_s": 100.0,
        "dt_s": 2.0,
        "chief": {"altitude_km": 500.0},
        "formation": {"n_slots": 2, "radial_amp_km": 1.0},
        "a_max_mps2": 0.01,
        "gains": {"wn": 0.01, "zeta": 1.0},
        "sensor": {
            "fov_half_angle_deg": 1.5,
            "grid_step_km": 2.0,
            "grid_extent_km": 30.0,
        },
        "roles": ["leader", "downlink"],
    }
    scenario = Scenario.model_validate(payload)
    assert isinstance(scenario.safety, Safety)
    assert scenario.safety == Safety()

    with pytest.raises(ValidationError):
        Safety(evade_radius_m=0.0)
    with pytest.raises(ValidationError):
        Safety(evade_ticks=0)


def test_proximity_stress_scenario_runs(stress_scenario, stress_lines):
    """Structural: the committed tuned scenario parses through the real schema,
    runs end to end (INIT header -> SUMMARY), fires evasion with ranges inside
    the radius, and its fired event renders through the wire authority as an
    info event 'SAT-x evasive maneuver (SAT-y, range Z m)'."""
    assert stress_lines[0]["state"] == "INIT"
    assert stress_lines[0]["scenario"] == "proximity_stress"
    assert stress_lines[-1]["state"] == "SUMMARY"

    evasions = _events(stress_lines, "EVASIVE_MANEUVER")
    assert evasions
    radius = stress_scenario.safety.evade_radius_m
    assert min(p["range_m"] for _t, p in evasions) < radius

    ticks = _tick_lines(stress_lines)
    fired_line = next(
        line for line in ticks if "event" in line and line["event"]["type"] == "EVASIVE_MANEUVER"
    )
    messages = to_messages(fired_line, SessionEnrich())
    assert [m["type"] for m in messages] == ["sim_state", "event"]
    payload = fired_line["event"]["payload"]
    assert messages[1] == {
        "type": "event",
        "sim_time": fired_line["t"],
        "level": "info",
        "message": (
            f"SAT-{payload['sat_id'] + 1} evasive maneuver "
            f"(SAT-{payload['other_id'] + 1}, range {payload['range_m']:.0f} m)"
        ),
        "sat_id": f"SAT-{payload['sat_id'] + 1}",  # additive wire key (2026-10-31)
    }
