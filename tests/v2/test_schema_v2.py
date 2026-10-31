"""Task 1.1: engine flag, chief orbit fields, v2 seam. v1 JSON must validate unchanged."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from cubesat.canon import canonical_log_hash
from cubesat.scenario import Scenario, load_scenario
from cubesat.sim import run_scenario

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = sorted((ROOT / "data" / "scenarios").glob("*.json"))
# Same pin as tests/test_cli.py (nominal.json, duration 600 s, seed 42); copied, not imported.
GOLDEN_NOMINAL_SHORT = "64b88c46843f99cdeaff654c4eccef1bf9e94e500d5171b236c17ce9d8def3a8"


@pytest.mark.parametrize("path", SCENARIOS, ids=lambda p: p.name)
def test_v1_json_validates_without_new_fields(path):
    s = load_scenario(path)
    assert s.engine == "v1"
    assert s.chief.inclination_deg == 97.4
    assert s.chief.raan_deg == 0.0
    assert s.chief.epoch_utc  # documented fixed default


def test_v1_nominal_bytes_unchanged():
    payload = json.loads((ROOT / "data" / "scenarios" / "nominal.json").read_text())
    payload["duration_s"] = 600.0
    lines = run_scenario(Scenario.model_validate(payload))
    assert canonical_log_hash(lines) == GOLDEN_NOMINAL_SHORT


def test_engine_rejects_other_values():
    payload = json.loads((ROOT / "data" / "scenarios" / "nominal.json").read_text())
    with pytest.raises(ValidationError):
        Scenario.model_validate({**payload, "engine": "v3"})
    assert Scenario.model_validate({**payload, "engine": "v2"}).engine == "v2"


def test_v2_seam_delegates_to_sim_v2():
    payload = json.loads((ROOT / "data" / "scenarios" / "nominal.json").read_text())
    s = Scenario.model_validate({**payload, "engine": "v2", "duration_s": 10.0})
    import cubesat.sim_v2 as sim_v2

    called = []
    orig = sim_v2.run_scenario_v2
    sim_v2.run_scenario_v2 = lambda sc, ev=None: called.append(sc) or []
    try:
        assert run_scenario(s) == []
    finally:
        sim_v2.run_scenario_v2 = orig
    assert called == [s]
