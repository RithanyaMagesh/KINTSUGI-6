"""cubesat/scenario.py was split into scenario.py + scenario_models.py (pure refactor).

The pinned hashes were produced from the pre-split module (git rev ffd5f2d):
  * SCHEMA_SHA256 = sha256(json.dumps(Scenario.model_json_schema(), sort_keys=True))
  * FINGERPRINTS  = EngineV2(scenario)._fingerprint()["scenario_sha256"], i.e.
    sha256(scenario.model_dump_json()), for data/scenarios/nominal.json (as committed,
    engine v1, and model_copy(update={"engine": "v2"}) -- the v2 engine variant).
"""

import hashlib
import json
from pathlib import Path

import pytest

import cubesat.scenario as scenario
import cubesat.scenario_models as models
from cubesat.scenario import Scenario, load_scenario
from cubesat.sim_v2 import EngineV2

ROOT = Path(__file__).resolve().parents[1]
# Re-pinned by track C phase C3 (pre-split value 7c470873...62b37b): the new optional
# formation.shape field must appear in the published JSON schema (hiding it would mislead
# API/UI consumers). Scenario dumps, so FINGERPRINTS below, are unchanged: the default
# shape is excluded from model_dump (exclude_if).
SCHEMA_SHA256 = "c5d50ef407665efef45ba94d3ae7166f1a922eeafbdcba8fa0b25bab1104f1b3"
FINGERPRINTS = {
    ("nominal", "v1"): "8b2ba0d0fa9c560ae8bb7c620bec20c61d42400063508c99219376d57b38475b",
    ("nominal", "v2"): "a5463052cc90ba0dc699bc587689b5501a1fcc5f638161a668d6e7cfacbfd9dc",
    ("two_failure", "v2"): "150d5e8252e164d98c52b2dc9b52e1dea9d648c07a6132d7b182a762ec9e0492",
}
MOVED = (
    "FailureMode V2_ONLY_MODES ChiefOrbit Truth Spacecraft Formation Gains Sensor Failure "
    "Detection Allocation Oracle Safety MAX_GRID_POINTS MAX_SWEEP_ENTRIES MAX_SATS "
    "MAX_FAILURES MAX_DURATION_S MAX_TICKS ROLE_PRIORITY"
).split()


@pytest.mark.parametrize("name", MOVED)
def test_reexports_have_identical_identity(name):
    assert getattr(scenario, name) is getattr(models, name)


def test_scenario_stays_in_scenario_module():
    assert Scenario.__module__ == "cubesat.scenario"
    assert scenario.load_scenario is load_scenario


@pytest.mark.parametrize("mod", [scenario, models])
def test_module_line_count_budget(mod):
    assert len(Path(mod.__file__).read_text().splitlines()) <= 310


def test_json_schema_unchanged():
    dump = json.dumps(Scenario.model_json_schema(), sort_keys=True)
    assert hashlib.sha256(dump.encode()).hexdigest() == SCHEMA_SHA256


@pytest.mark.parametrize(("name", "engine"), list(FINGERPRINTS))
def test_engine_fingerprint_stable(name, engine):
    sc = load_scenario(ROOT / "data" / "scenarios" / f"{name}.json")
    sc = sc.model_copy(update={"engine": engine})
    assert EngineV2(sc)._fingerprint()["scenario_sha256"] == FINGERPRINTS[(name, engine)]
