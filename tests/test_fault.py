"""Failure injection, detection, state machine, and baseline tests (gate G4).

Covers docs/MASTER_PROMPT.md sections 3.5 (fault tolerance), 3.8 (required test
names), and research patch #2 (coverage must drop >= 15 points with 2 dead and
no recovery). Required names here: test_min_separation_never_below_threshold,
test_two_failures_reduce_coverage_visibly. Extras pin the detection latency, the
state-machine sequence, and the headline result (recovery beats no recovery).

Run data comes from the committed data/scenarios/two_failure.json (two DEAD
imagers at t=1200/1500) via cubesat.sim.run_scenario -- no RNG, no wall clock
(AGENTS.md 2), so the module-scoped fixtures are exact replays.
"""

import json
import math
from pathlib import Path

import pytest

from cubesat.hcw import mean_motion
from cubesat.scenario import load_scenario
from cubesat.sim import run_scenario

ROOT = Path(__file__).resolve().parents[1]
NOMINAL = ROOT / "data" / "scenarios" / "nominal.json"
TWO_FAILURE = ROOT / "data" / "scenarios" / "two_failure.json"


@pytest.fixture(scope="module")
def scenario():
    return load_scenario(TWO_FAILURE)


@pytest.fixture(scope="module")
def recovery_lines(scenario):
    """Full two_failure run with recovery enabled (the primary demo log)."""
    return run_scenario(scenario)


@pytest.fixture(scope="module")
def norecovery_lines(scenario):
    """Same scenario and failures with the replanner disabled (the baseline)."""
    return run_scenario(scenario.model_copy(update={"recovery_enabled": False}))


def _tick_lines(lines):
    return [line for line in lines if line["state"] not in ("INIT", "SUMMARY")]


def _events(lines, event_type):
    return [
        (line["t"], line["event"]["payload"])
        for line in lines
        if "event" in line and line["event"]["type"] == event_type
    ]


def test_failure_detection_latency():
    """Each sat emits a heartbeat every tick; a DEAD sat is declared after K missed
    ticks (MASTER_PROMPT 3.5). The event carries {sat_id, mode, t_fail, t_detect}
    and detection latency = t_detect - t_fail; the declaring tick's line shows the
    FAILURE_DETECTED state."""
    payload = json.loads(NOMINAL.read_text(encoding="utf-8"))
    payload["name"] = "detect_latency"
    payload["duration_s"] = 200.0
    payload["failures"] = [{"t": 100.0, "sat_id": 4, "mode": "DEAD"}]
    # Build the scenario through the real schema from a temp file (never committed).
    tmp = ROOT / ".pytest_tmp" / "g4_detect.json"
    tmp.parent.mkdir(exist_ok=True)
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    lines = run_scenario(load_scenario(tmp))

    detected = _events(lines, "FAILURE_DETECTED")
    assert len(detected) == 1
    t_detect, p = detected[0]
    assert p["sat_id"] == 4
    assert p["mode"] == "DEAD"
    assert p["t_fail"] == 100.0
    # The heartbeat is missed on the firing tick already, so K missed ticks span
    # [t_fail, t_fail + (K-1)*dt].
    k = load_scenario(tmp).detection.missed_ticks_k
    assert t_detect == pytest.approx(100.0 + (k - 1) * 2.0)
    assert t_detect - p["t_fail"] == pytest.approx((k - 1) * 2.0)
    declaring = [line for line in _tick_lines(lines) if line["t"] == t_detect]
    assert len(declaring) == 1
    assert declaring[0]["state"] == "FAILURE_DETECTED"


def test_state_machine_sequence(scenario, recovery_lines):
    """NOMINAL -> FAILURE_DETECTED -> REPLANNING -> RECONFIGURING -> RECOVERED, with
    every transition visible at sim time; two failures drive two full cycles; dead
    sats coast (AGENTS.md invariant 5)."""
    ticks = _tick_lines(recovery_lines)
    first_seen = {}
    for line in ticks:
        first_seen.setdefault(line["state"], line["t"])
    order = sorted(first_seen, key=lambda s: first_seen[s])
    assert order == [
        "NOMINAL",
        "FAILURE_DETECTED",
        "REPLANNING",
        "RECONFIGURING",
        "RECOVERED",
    ]

    detected = _events(recovery_lines, "FAILURE_DETECTED")
    assert len(detected) == 2
    for _t, p in detected:
        assert p["mode"] == "DEAD"
        assert p["t_detect"] - p["t_fail"] == pytest.approx(
            (scenario.detection.missed_ticks_k - 1) * scenario.dt_s
        )
    assert len(_events(recovery_lines, "ASSIGNMENT")) == 2
    transitions = _events(recovery_lines, "STATE")
    assert [p["to"] for _t, p in transitions].count("REPLANNING") == 2
    # The 2nd failure is detected mid-reconfiguration (300 s after the 1st, while
    # transfers take ~0.6 orbits), so the machine re-enters FAILURE_DETECTED from
    # RECONFIGURING: two replanning cycles, one final RECOVERED.
    assert [p["to"] for _t, p in transitions].count("RECOVERED") == 1

    # Event/state coherence: each event lands on the first tick of its new state.
    by_type = {"FAILURE_DETECTED": "FAILURE_DETECTED", "ASSIGNMENT": "RECONFIGURING"}
    for line in ticks:
        if "event" not in line:
            continue
        etype = line["event"]["type"]
        if etype in by_type:
            assert line["state"] == by_type[etype], line["t"]

    # Dead sats coast ballistically, never freeze (positions keep changing).
    dead_id = scenario.failures[0].sat_id
    t_declared = detected[0][0]
    r_then = next(ln for ln in ticks if ln["t"] == t_declared)["sats"][dead_id]["r"]
    r_late = ticks[-1]["sats"][dead_id]["r"]
    assert math.dist(r_then, r_late) > 1000.0

    summary = recovery_lines[-1]
    assert summary["state"] == "SUMMARY"
    assert 0.0 < summary["coverage_mean_last_orbit"] <= 1.0


def test_min_separation_never_below_threshold(scenario, recovery_lines):
    """Logged min separation (all pairs, dead sats included as coasting obstacles)
    never drops below the scenario threshold -- including while survivors maneuver
    to their reassigned seats (MASTER_PROMPT 3.8)."""
    threshold = scenario.allocation.min_sep_km * 1000.0
    seps = [(line["t"], line["min_sep"]) for line in _tick_lines(recovery_lines)]
    worst_t, worst = min(seps, key=lambda x: x[1])
    print(
        f"test_min_separation_never_below_threshold: worst min_sep = {worst:.1f} m "
        f"at t = {worst_t:.0f} s (threshold {threshold:.0f} m, "
        f"{len(seps)} ticks incl. reconfiguration transfers)"
    )
    assert worst >= threshold


def test_two_failures_reduce_coverage_visibly(scenario, norecovery_lines):
    """Research patch #2: with 2 sats dead and NO recovery, time-averaged coverage
    drops >= 15 percentage points (pre-failure window vs last orbit). Tuning lever
    is slot spacing / FOV, never the metric definition."""
    ticks = _tick_lines(norecovery_lines)
    t_first_fail = min(f.t for f in scenario.failures)
    pre = [line["coverage"] for line in ticks if line["t"] < t_first_fail]
    period = 2.0 * math.pi / mean_motion(scenario.chief.altitude_km * 1000.0)
    window_start = scenario.duration_s - period
    post = [line["coverage"] for line in ticks if line["t"] >= window_start]
    assert pre and post
    pre_mean = sum(pre) / len(pre)
    post_mean = sum(post) / len(post)
    drop = pre_mean - post_mean
    print(
        f"test_two_failures_reduce_coverage_visibly: no-recovery mean coverage "
        f"pre-failure = {pre_mean:.4f}, last orbit = {post_mean:.4f}, "
        f"drop = {100.0 * drop:.2f} pts (target >= 15, research patch #2)"
    )
    assert drop >= 0.15


def test_recovery_beats_no_recovery(scenario, recovery_lines, norecovery_lines):
    """The headline result (MASTER_PROMPT 3.4 / gate G4): on two_failure, the
    with-recovery coverage curve beats the no-recovery curve over the last orbit."""
    rec = recovery_lines[-1]["coverage_mean_last_orbit"]
    norec = norecovery_lines[-1]["coverage_mean_last_orbit"]
    print(
        f"test_recovery_beats_no_recovery: last-orbit mean coverage with recovery = "
        f"{rec:.4f}, without = {norec:.4f}, gain = {100.0 * (rec - norec):.2f} pts"
    )
    assert rec > norec
