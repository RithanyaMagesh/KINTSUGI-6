from pathlib import Path

import pytest
from pydantic import ValidationError

from cubesat.scenario import Scenario, load_scenario

ROOT = Path(__file__).resolve().parents[1]
NOMINAL = ROOT / "data" / "scenarios" / "nominal.json"


def test_nominal_loads_with_6_sats():
    scenario = load_scenario(NOMINAL)
    assert scenario.n_sats == 6
    assert scenario.roles.count("leader") == 1
    assert scenario.failures == []


def test_rejects_bad_altitude():
    payload = load_scenario(NOMINAL).model_dump()
    payload["chief"]["altitude_km"] = 5.0
    with pytest.raises(ValidationError):
        Scenario.model_validate(payload)


def test_rejects_bad_failure_mode():
    payload = load_scenario(NOMINAL).model_dump()
    payload["failures"] = [{"t": 100.0, "sat_id": 0, "mode": "EXPLODED"}]
    with pytest.raises(ValidationError):
        Scenario.model_validate(payload)


def test_rejects_unknown_failure_sat():
    payload = load_scenario(NOMINAL).model_dump()
    payload["failures"] = [{"t": 100.0, "sat_id": 9, "mode": "DEAD"}]
    with pytest.raises(ValidationError):
        Scenario.model_validate(payload)


def test_rejects_nonpositive_dt():
    payload = load_scenario(NOMINAL).model_dump()
    payload["dt_s"] = 0.0
    with pytest.raises(ValidationError):
        Scenario.model_validate(payload)


def test_rejects_slot_role_mismatch():
    payload = load_scenario(NOMINAL).model_dump()
    payload["formation"]["n_slots"] = 5  # roles stays 6: would log phantom sats
    with pytest.raises(ValidationError):
        Scenario.model_validate(payload)
