"""Review fixes for Phase 2 (each test was red before its fix): DEGRADE_START after another
failure, stuck-burn log key, dry-mass floor, atomic restore, re-entry detection label."""

import json
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from cubesat.scenario import Scenario
from cubesat.sim_v2 import EngineV2

ROOT = Path(__file__).resolve().parents[2]
NOMINAL = json.loads((ROOT / "data" / "scenarios" / "nominal.json").read_text())
SMALL_SENSOR = {"fov_half_angle_deg": 1.5, "grid_step_km": 5.0, "grid_extent_km": 5.0}


def _scn(**kw) -> Scenario:
    return Scenario.model_validate({**NOMINAL, "engine": "v2", "sensor": SMALL_SENSOR, **kw})


def _events(lines, kind):
    return [(x["t"], e) for x in lines for e in x.get("events", []) if e["type"] == kind]


# --- B3: DEGRADE_START survives an earlier Phase-2 failure ------------------------------------
def test_degrade_start_not_lost_after_partial_thrust():
    s = _scn(
        duration_s=500.0,
        failures=[
            {"t": 10.0, "sat_id": 1, "mode": "PARTIAL_THRUST"},
            {"t": 400.0, "sat_id": 1, "mode": "EPS_DEGRADE", "degrade_s": 100.0},
        ],
    )
    ev = _events(list(EngineV2(s).run()), "DEGRADE_START")
    assert [(t, e["payload"]["sat_id"]) for t, e in ev] == [(300.0, 1)]  # once, at the onset


# --- B4: stuck burn visible in the log --------------------------------------------------------
@pytest.mark.parametrize("order", [("THRUSTER_OUT", "THRUSTER_STUCK_OPEN"),
                                   ("THRUSTER_STUCK_OPEN", "THRUSTER_OUT")])
def test_stuck_flag_logged_while_label_is_thruster_out_and_fuel_falls(order):
    s = _scn(duration_s=40.0, failures=[{"t": 0.0, "sat_id": 1, "mode": m} for m in order])
    lines = [x for x in EngineV2(s).run() if "sats" in x]
    a, b = lines[0]["sats"][1], lines[10]["sats"][1]
    assert a["status"] == "THRUSTER_OUT" and a["k"] == 0.0
    assert a["stuck"] is True and b["stuck"] is True
    assert b["fuel_kg"] < a["fuel_kg"] <= 0.2  # burning with k = 0
    assert all(x["stuck"] is False for x in lines[0]["sats"] if x["id"] != 1)


# --- B5: dry-mass floor -----------------------------------------------------------------------
def test_dry_mass_must_be_at_least_half_the_wet_mass_for_v2_only():
    base = {**NOMINAL, "engine": "v2"}
    assert Scenario.model_validate({**base, "spacecraft": {"m_prop_kg": 0.2}})
    assert Scenario.model_validate({**base, "spacecraft": {"m_prop_kg": 2.0}})  # exactly half
    with pytest.raises(ValidationError, match="dry mass.*half"):
        Scenario.model_validate({**base, "spacecraft": {"m_prop_kg": 3.99}})
    assert Scenario.model_validate({**NOMINAL, "spacecraft": {"m_prop_kg": 100.0}})  # v1 inert


# --- B6: restore validates before it mutates --------------------------------------------------
@pytest.mark.parametrize(
    "drop", [("faults", "sats"), ("faults", "fuel_out"), ("faults", "fade_done"), ("dv",), ("rng",),
             ("X",), ("faults", "status")]
)
def test_restore_of_a_partial_snapshot_raises_valueerror_and_changes_nothing(drop):
    s = _scn(duration_s=60.0)
    a = EngineV2(s)
    for _ in range(5):
        a.step()
    doc = json.loads(a.snapshot())
    node = doc["state"]
    for key in drop[:-1]:
        node = node[key]
    del node[drop[-1]]
    b = EngineV2(s)
    for _ in range(10):
        b.step()
    before = (b.k, b.X.copy(), b.dv.copy(), list(b.faults.status), b.rng.bit_generator.state)
    with pytest.raises(ValueError):
        b.restore(json.dumps(doc).encode())
    assert b.k == before[0] and np.array_equal(b.X, before[1]) and np.array_equal(b.dv, before[2])
    assert b.faults.status == before[3] and b.rng.bit_generator.state == before[4]
    b.step()  # still runs


# --- B7: a re-entry silence announces REENTRY -------------------------------------------------
def test_reentry_silence_announces_reentry_not_the_failure_label():
    s = _scn(
        chief={"altitude_km": 161.0},
        dt_s=10.0,
        duration_s=30000.0,
        a_max_mps2=1e-12,
        truth={"density_factor": 50.0},  # an active-area sat re-enters in the run
        failures=[{"t": 0.0, "sat_id": 0, "mode": "PAYLOAD_FAIL"}],
    )
    lines = list(EngineV2(s).run())
    (t_re, _), = [(t, e) for t, e in _events(lines, "REENTRY") if e["payload"]["sat_id"] == 0]
    det = [(t, e["payload"]["mode"], e["payload"]["t_fail"]) for t, e in
           _events(lines, "FAILURE_DETECTED") if e["payload"]["sat_id"] == 0]
    assert det == [(0.0, "PAYLOAD_FAIL", 0.0), (t_re + 20.0, "REENTRY", t_re)]
