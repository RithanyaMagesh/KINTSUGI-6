"""Failure-semantics round tests (BACKEND_SPEC Addendum v1.2).

Covers the two additive, default-inert failure modes: EPS_DEGRADE (gradual
power death -- the sat reports DEGRADED for degrade_s before failing, then dies
exactly like DEAD) and the self-reported THRUSTER_OUT (a sat that announces its
own dead thruster is detected on the firing tick with no heartbeat misses and
drives the standard recovery arc). The canonical two_failure sha pin guards the
default-inert contract: every existing scenario must keep producing
byte-identical logs.

Run data comes from pytest-owned JSON built through the real schema (the
tests/test_fault.py pattern) plus the committed data/scenarios/two_failure.json
-- no RNG, no wall clock (AGENTS.md 2), so every run is an exact replay.
"""

import hashlib
import json
import math
from pathlib import Path

from cubesat.scenario import load_scenario
from cubesat.sim import run_scenario

ROOT = Path(__file__).resolve().parents[1]
TWO_FAILURE = ROOT / "data" / "scenarios" / "two_failure.json"

# Round key regression pin: sha256 of the canonical two_failure log (both
# failures DEAD, so nothing in the failure-semantics round may move a byte).
# Serialization is exactly cubesat/run.py's (json.dumps, sort_keys, LF).
CANONICAL_TWO_FAILURE_SHA256_SET = {
    "450d537107c36205880b4e7a63e9d804e64e6352553b97b019cf3961ed044801",  # win32 UCRT
    "b8f72df8d1c75043bf72ca78dfbbccb9b9a6d8d64117072460d62da3c834a362",  # linux glibc
}
CANONICAL_TWO_FAILURE_SHA256 = (
    "450d537107c36205880b4e7a63e9d804e64e6352553b97b019cf3961ed044801"
)

# Small 4-sat base: dt 2 s, 1 km slots. min_sep is set explicitly (0.5 km) so
# the 3-survivor formation sweep stays feasible at this small amplitude, and
# the duration covers the full recovery arc (measured settle at t = 1332 for
# the self-report run below, 1950 for the degrade run).
BASE: dict = {
    "name": "eps_degrade_tiny",
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
}

# EPS_DEGRADE on sat 1 at t = 60 with a 30 s fade: DEGRADED from t = 30,
# DEAD from t = 60 (both tick-aligned).
T_FAIL = 60.0
DEGRADE_S = 30.0
FADE_T = T_FAIL - DEGRADE_S


def _scenario(tmp_path, payload, name):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return load_scenario(path)


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


def test_eps_degrade_window_semantics(tmp_path):
    """During the fade the sat reports (heartbeats keep it undetectable), keeps
    PD-holding its assigned seat -- states byte-identical to a no-failure run
    -- and a DEGRADE_START event {sat_id, t_fail, degrade_s} appears; at t_fail
    it is DEAD and coasts ballistically (never frozen)."""
    degrade = _scenario(
        tmp_path,
        dict(BASE, failures=[{"t": T_FAIL, "sat_id": 1, "mode": "EPS_DEGRADE",
                              "degrade_s": DEGRADE_S}]),
        "degrade.json",
    )
    nofail = _scenario(tmp_path, dict(BASE, name="eps_nofail", failures=[]), "nofail.json")
    lines = run_scenario(degrade)
    ticks = _tick_lines(lines)
    clean_ticks = _tick_lines(run_scenario(nofail))

    starts = _events(lines, "DEGRADE_START")
    assert starts == [(FADE_T, {"sat_id": 1, "t_fail": T_FAIL, "degrade_s": DEGRADE_S})]

    # Fade window: DEGRADED, mission stays NOMINAL (still reporting), and the
    # sat holds its seat -- identical states/dv to the no-failure run.
    for line, ref in zip(ticks, clean_ticks, strict=True):
        if FADE_T <= line["t"] < T_FAIL:
            assert line["sats"][1]["status"] == "DEGRADED"
            assert line["state"] == "NOMINAL"
        if line["t"] <= T_FAIL:
            assert line["sats"][1]["r"] == ref["sats"][1]["r"]
            assert line["sats"][1]["dv_used"] == ref["sats"][1]["dv_used"]

    # Reporting, not failing: the only detection is the real death, after the
    # K-miss heartbeat window following t_fail.
    detected = _events(lines, "FAILURE_DETECTED")
    assert len(detected) == 1
    t_detect, payload = detected[0]
    assert payload["sat_id"] == 1 and payload["mode"] == "EPS_DEGRADE"
    assert t_detect == T_FAIL + 2.0 * (degrade.detection.missed_ticks_k - 1)

    # At t_fail: DEAD, then coasting ballistically -- a frozen sat would show
    # one position to the end of the run.
    death = next(line for line in ticks if line["t"] == T_FAIL)
    assert death["sats"][1]["status"] == "DEAD"
    assert math.dist(death["sats"][1]["r"], ticks[-1]["sats"][1]["r"]) > 100.0


def test_eps_degrade_double_run_byte_identical(tmp_path):
    """AGENTS.md invariant 2 on the new family: same scenario + seed =>
    byte-identical log, including the DEGRADED window bytes."""
    degrade = _scenario(
        tmp_path,
        dict(BASE, failures=[{"t": T_FAIL, "sat_id": 1, "mode": "EPS_DEGRADE",
                              "degrade_s": DEGRADE_S}]),
        "degrade.json",
    )
    assert _serialized(run_scenario(degrade)) == _serialized(run_scenario(degrade))


def test_eps_degrade_zero_window_equals_dead(tmp_path):
    """degrade_s == 0 is sudden: the run equals the same failure declared DEAD
    -- same status flip at t_fail, same detection path, same coast. The one
    byte difference is the honest FAILURE_DETECTED mode label, which stays
    'EPS_DEGRADE' (asserted explicitly, then normalized for the comparison)."""
    zero = _scenario(
        tmp_path,
        dict(BASE, name="eps_zero",
             failures=[{"t": T_FAIL, "sat_id": 1, "mode": "EPS_DEGRADE", "degrade_s": 0.0}]),
        "zero.json",
    )
    dead = _scenario(
        tmp_path,
        dict(BASE, name="eps_zero", failures=[{"t": T_FAIL, "sat_id": 1, "mode": "DEAD"}]),
        "dead.json",
    )
    zero_lines = run_scenario(zero)
    dead_lines = run_scenario(dead)
    for line in zero_lines:
        event = line.get("event")
        if event is not None and event["type"] == "FAILURE_DETECTED":
            assert event["payload"]["mode"] == "EPS_DEGRADE"
            event["payload"]["mode"] = "DEAD"
    assert _serialized(zero_lines) == _serialized(dead_lines)


def test_self_report_triggers_replan(tmp_path):
    """A THRUSTER_OUT sat announces its own failure: FAILURE_DETECTED fires at
    the firing tick with self_report: True, the standard arc runs (REPLANNING
    -> re-election -> RECONFIGURING -> RECOVERED), the downlink role is
    re-elected onto a healthy sat, and the reporting sat keeps status
    THRUSTER_OUT but is in no assignment any more. (Its stale role label on the
    log line is pre-existing behavior shared with DEAD sats.)"""
    thruster = _scenario(
        tmp_path,
        dict(BASE, name="self_report_tiny",
             failures=[{"t": 6.0, "sat_id": 3, "mode": "THRUSTER_OUT"}]),
        "thruster.json",
    )
    lines = run_scenario(thruster)
    ticks = _tick_lines(lines)

    detected = _events(lines, "FAILURE_DETECTED")
    assert detected == [
        (6.0, {"sat_id": 3, "mode": "THRUSTER_OUT", "t_fail": 6.0, "t_detect": 6.0,
               "self_report": True})
    ]
    assert next(line for line in ticks if line["t"] == 6.0)["state"] == "FAILURE_DETECTED"

    transitions = _events(lines, "STATE")
    assert [p["to"] for _t, p in transitions].count("RECOVERED") == 1
    assert "RECOVERED" in [line["state"] for line in ticks]

    assignments = _events(lines, "ASSIGNMENT")
    assert len(assignments) == 1
    assigned = assignments[0][1]["assignments"]
    assert 3 not in [a["sat_id"] for a in assigned]  # lost its seat/role
    holder = next(a for a in assigned if a["role"] == "downlink")
    assert holder["sat_id"] != 3  # re-elected to a healthy sat
    assert ticks[-1]["sats"][3]["status"] == "THRUSTER_OUT"  # keeps reporting


def test_self_report_detection_latency_zero(tmp_path):
    """Self-reported detection carries no heartbeat-miss latency: the
    FAILURE_DETECTED fires on the firing tick, so t_fail == t_detect for a
    tick-aligned failure time (this test, every committed scenario, live
    injection; heartbeat-inferred DEAD is (missed_ticks_k - 1) * dt instead).
    A mid-tick t_fail reports t_detect as the enclosing tick -- the payload
    carries both, so latency stays auditable."""
    thruster = _scenario(
        tmp_path,
        dict(BASE, name="self_report_tiny",
             failures=[{"t": 6.0, "sat_id": 3, "mode": "THRUSTER_OUT"}]),
        "thruster.json",
    )
    lines = run_scenario(thruster)
    (_t, payload), = _events(lines, "FAILURE_DETECTED")
    assert payload["t_detect"] == payload["t_fail"] == 6.0


def test_canonical_two_failure_sha_unchanged():
    """Round key regression pin: the canonical two_failure log (both DEAD
    failures, no degrade, no self-report) stays byte-identical through the
    Addendum v1.2 core diffs -- the whole round is default-inert."""
    lines = run_scenario(load_scenario(TWO_FAILURE))
    digest = hashlib.sha256(_serialized(lines).encode("utf-8")).hexdigest()
    assert digest in CANONICAL_TWO_FAILURE_SHA256_SET, f"golden sha mismatch: got {digest}"
