"""Degrade-trigger policy tests (reassign_on_degrade, GATES.md 2026-10-29
pre-registration round).

The EPS_DEGRADE fade window announces itself on the wire (status DEGRADED from
max(t_fail - degrade_s, 0)), so a plain reactive policy that fires the oracle
path's proactive critical-seat swap on the NOMINAL -> DEGRADED transition of a
critical-role holder gets oracle-L=degrade_s timing with no oracle and no
predictor. These tests pin the mechanism, its default-off byte-inertness, and
its no-op cases (imager fades, THRUSTER_OUT -- no DEGRADED transition there).

The flag-off byte-identity of the canonical runs is covered by the existing
golden pins -- tests/test_failure_modes.py::test_canonical_two_failure_sha_unchanged
(sha 450d5371..., re-asserted here under the flag ON, which is the stronger
direction: no degrade transition -> the trigger must stay silent) and the
tests/test_cli.py short-run golden c95f31b8.... Run data comes from the
committed data/scenarios/*.json (no RNG, no wall clock, AGENTS.md 2).
"""

import hashlib
import json
from pathlib import Path

from cubesat.scenario import Scenario, load_scenario
from cubesat.sim import run_scenario

ROOT = Path(__file__).resolve().parents[1]
EPS_LEADER = ROOT / "data" / "scenarios" / "eps_leader_6sat.json"
EPS_IMAGER = ROOT / "data" / "scenarios" / "eps_imager_6sat.json"
THRUSTER_LEADER = ROOT / "data" / "scenarios" / "thruster_leader_6sat.json"
TWO_FAILURE = ROOT / "data" / "scenarios" / "two_failure.json"

# Round key regression pin (shared with tests/test_failure_modes.py): the
# canonical two_failure log -- both failures DEAD, so nothing in this round may
# move a byte even with the flag ON (no EPS_DEGRADE -> no DEGRADED transition).
CANONICAL_TWO_FAILURE_SHA256_SET = {
    "450d537107c36205880b4e7a63e9d804e64e6352553b97b019cf3961ed044801",  # win32 UCRT
    "b8f72df8d1c75043bf72ca78dfbbccb9b9a6d8d64117072460d62da3c834a362",  # linux glibc
}
CANONICAL_TWO_FAILURE_SHA256 = (
    "450d537107c36205880b4e7a63e9d804e64e6352553b97b019cf3961ed044801"
)

FADE_T = 600.0  # eps_*_6sat: t_fail 2400 - degrade_s 1800
T_FAIL = 2400.0


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


def test_degrade_trigger_moves_critical_seat_to_nominal_holder():
    """eps_leader_6sat + flag: at the NOMINAL -> DEGRADED transition the leader
    seat moves to a NOMINAL holder via the oracle path's swap (ORACLE_SWAP,
    additive payload key mode='degrade_trigger'), within a couple of ticks of
    DEGRADE_START. The measured transient is pinned: identical physics through
    the transition tick, both swapped sats flying their new seats from the next
    step, and the fading sat never holding a critical role again."""
    scenario = load_scenario(EPS_LEADER)
    on = scenario.model_copy(update={"duration_s": 2600.0, "reassign_on_degrade": True})
    off = scenario.model_copy(update={"duration_s": 2600.0})
    lines = run_scenario(on)
    ref_ticks = _tick_lines(run_scenario(off))
    ticks = _tick_lines(lines)

    assert _events(lines, "DEGRADE_START") == [
        (FADE_T, {"sat_id": 0, "t_fail": T_FAIL, "degrade_s": 1800.0})
    ]
    # Same event vocabulary as the oracle path; the payload carries the
    # distinguishing mode label and pops onto the tick after DEGRADE_START
    # (FIFO: at most one event per line). target = min(candidates) = sat 1.
    assert _events(lines, "ORACLE_SWAP") == [
        (
            FADE_T + 2.0,
            {"role": "leader", "from_sat": 0, "to_sat": 1, "t": FADE_T,
             "mode": "degrade_trigger"},
        )
    ]

    # The transition tick's line ALREADY shows the moved seat: the fading sat
    # is DEGRADED in a non-critical slot, the leader seat on a NOMINAL holder.
    line600 = next(line for line in ticks if line["t"] == FADE_T)
    assert line600["sats"][0]["status"] == "DEGRADED"
    assert line600["sats"][0]["role"] == "imager"  # non-critical slot
    assert line600["sats"][1]["role"] == "leader"
    assert line600["sats"][1]["status"] == "NOMINAL"

    # Measured transient: byte-equal positions through the transition tick,
    # diverging at the first step after (both sats fly each other's seats).
    for line, ref in zip(ticks, ref_ticks, strict=True):
        if line["t"] <= FADE_T:
            assert line["sats"][0]["r"] == ref["sats"][0]["r"], f"moved early at t={line['t']}"
        elif line["t"] == FADE_T + 2.0:
            assert line["sats"][0]["r"] != ref["sats"][0]["r"]
            assert line["sats"][1]["r"] != ref["sats"][1]["r"]
            break
    else:  # pragma: no cover - the short run always passes t = 602
        raise AssertionError("never reached t = 602")

    # From the transition to the end: sat 0 never holds a critical role again,
    # and exactly one NOMINAL sat holds the leader seat at every tick.
    for line in ticks:
        if line["t"] >= FADE_T:
            assert line["sats"][0]["role"] not in ("leader", "downlink")
            holders = [s for s in line["sats"] if s["role"] == "leader"]
            assert len(holders) == 1 and holders[0]["status"] == "NOMINAL", (
                f"leader seat unhealthy at t={line['t']}"
            )


def test_reassign_on_degrade_defaults_false():
    """The field defaults False (explicit assert) -- canonical scenarios never
    set it, so the trigger never fires and the golden pins stay green: the
    flag-off canonical runs are covered by the existing golden pins
    (tests/test_failure_modes.py::test_canonical_two_failure_sha_unchanged and
    the tests/test_cli.py short-run golden); here the flag-ON two_failure run
    (no EPS_DEGRADE, hence no DEGRADED transition to trigger on) must still
    reproduce the committed canonical sha byte for byte."""
    minimal = Scenario.model_validate(
        {
            "name": "default_check",
            "seed": 0,
            "duration_s": 100.0,
            "dt_s": 2.0,
            "chief": {"altitude_km": 500.0},
            "formation": {"n_slots": 2, "radial_amp_km": 1.0},
            "a_max_mps2": 0.01,
            "gains": {"wn": 0.01, "zeta": 1.0},
            "sensor": {"fov_half_angle_deg": 1.5, "grid_step_km": 5.0,
                       "grid_extent_km": 5.0},
            "roles": ["leader", "downlink"],
        }
    )
    assert minimal.reassign_on_degrade is False

    lines = run_scenario(
        load_scenario(TWO_FAILURE).model_copy(update={"reassign_on_degrade": True})
    )
    digest = hashlib.sha256(_serialized(lines).encode("utf-8")).hexdigest()
    assert digest in CANONICAL_TWO_FAILURE_SHA256_SET, f"golden sha mismatch: got {digest}"


def test_imager_degrade_fires_no_reassignment():
    """eps_imager_6sat + flag: an imager fade is not a critical-role
    transition, so NO reassignment fires and the run stays byte-identical to
    its flag-off run (structurally flat, as the v2 control family predicted)."""
    scenario = load_scenario(EPS_IMAGER)
    off = scenario.model_copy(update={"duration_s": 2600.0})
    on = scenario.model_copy(update={"duration_s": 2600.0, "reassign_on_degrade": True})
    lines_on = run_scenario(on)
    assert _events(lines_on, "ORACLE_SWAP") == []
    assert _events(lines_on, "DEGRADE_START") == [
        (FADE_T, {"sat_id": 1, "t_fail": T_FAIL, "degrade_s": 1800.0})
    ]  # the fade itself still announces; only the swap is gated
    assert _serialized(lines_on) == _serialized(run_scenario(off))


def test_degrade_trigger_run_byte_deterministic():
    """AGENTS.md invariant 2 on the trigger path: same scenario + seed =>
    byte-identical log, swap event and seat-transfer bytes included."""
    scenario = load_scenario(EPS_LEADER).model_copy(
        update={"duration_s": 2600.0, "reassign_on_degrade": True}
    )
    assert _serialized(run_scenario(scenario)) == _serialized(run_scenario(scenario))


def test_thruster_out_has_no_degrade_transition():
    """thruster_leader_6sat + flag: THRUSTER_OUT has no DEGRADED transition, so
    the trigger never fires and the run stays byte-identical to its flag-off
    run -- the self-report path already reacts on the firing tick (pre-existing
    Addendum v1.2 semantics, asserted here once for the record)."""
    scenario = load_scenario(THRUSTER_LEADER)
    off = scenario.model_copy(update={"duration_s": 2600.0})
    on = scenario.model_copy(update={"duration_s": 2600.0, "reassign_on_degrade": True})
    lines_on = run_scenario(on)
    assert _events(lines_on, "ORACLE_SWAP") == []
    assert _events(lines_on, "DEGRADE_START") == []
    detected = _events(lines_on, "FAILURE_DETECTED")
    assert len(detected) == 1
    (_t, payload), = detected
    assert payload["self_report"] is True and payload["t_fail"] == T_FAIL
    assert _serialized(lines_on) == _serialized(run_scenario(off))
