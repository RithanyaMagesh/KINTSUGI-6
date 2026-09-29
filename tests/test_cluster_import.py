"""CelesTrak OMM import and hypothetical-swarm generation tests.

cubesat.cluster_import turns
a real OMM snapshot into a chief orbit and a runnable swarm scenario:
chief_from_omm parses one OMM record into {name, norad_cat_id,
mean_motion_rad_s, altitude_km, eccentricity}, build_swarm_scenario generates a
schema-valid scenario dict around it, and load_omm_records reads a snapshot
file. Conversion convention: n = MEAN_MOTION * 2*pi / 86400 (solar day, sgp4
convention), a = (MU/n^2)^(1/3), altitude_km = a - R_EARTH; the hard numbers
below were verified against cubesat.hcw.MU / R_EARTH. Space-Track emits numeric
fields as strings and CelesTrak as numbers, so both must parse to the identical
chief. Guards: near-circular LEO chiefs only (eccentricity and altitude gates
raise ValueError), and the generator never starves the formation (leader +
at least one imager + the downlink must survive).

The end-to-end fixture runs the FIREFLY-1 record from the committed
data/celestrak/firefly_omm.json (CelesTrak snapshot fetched 2026-09-28) through
cubesat.sim.run_scenario -- no RNG, no wall clock (AGENTS.md 2), so it is an
exact replay.
"""

import json
import math
from pathlib import Path

import pytest

from cubesat.cluster_import import build_swarm_scenario, chief_from_omm, load_omm_records
from cubesat.hcw import MU, R_EARTH
from cubesat.scenario import Scenario
from cubesat.sim import run_scenario

ROOT = Path(__file__).resolve().parents[1]
FIREFLY_OMM = ROOT / "data" / "celestrak" / "firefly_omm.json"
FIREFLY_SWARM = ROOT / "data" / "scenarios" / "firefly_swarm.json"


def _synthetic_record():
    """Near-circular LEO OMM record: e = 0.00071 passes the e-gate and
    MEAN_MOTION 15.48675883 rev/day converts to 420.599 km (checked against the
    cubesat.hcw constants to 1e-6 km)."""
    return {
        "OBJECT_NAME": "SYNTHETIC-A",
        "NORAD_CAT_ID": 99999,
        "MEAN_MOTION": 15.48675883,
        "ECCENTRICITY": 0.00071,
    }


def _events(lines, event_type):
    return [
        (line["t"], line["event"]["payload"])
        for line in lines
        if "event" in line and line["event"]["type"] == event_type
    ]


def test_omm_parses_mean_motion_to_altitude():
    chief = chief_from_omm(_synthetic_record())
    assert set(chief) == {
        "name",
        "norad_cat_id",
        "mean_motion_rad_s",
        "altitude_km",
        "eccentricity",
    }
    # sgp4 convention: revs per solar day, then a = (MU/n^2)^(1/3).
    n = 15.48675883 * 2.0 * math.pi / 86400.0
    a_km = ((MU / n**2) ** (1.0 / 3.0) - R_EARTH) / 1000.0
    assert chief["altitude_km"] == pytest.approx(a_km, abs=0.01)
    assert chief["altitude_km"] == pytest.approx(420.599, abs=0.01)
    assert chief["mean_motion_rad_s"] == pytest.approx(n)
    assert chief["name"] == "SYNTHETIC-A"
    assert chief["norad_cat_id"] == 99999
    assert chief["eccentricity"] == pytest.approx(0.00071)


def test_omm_rejects_eccentric_chief():
    with pytest.raises(ValueError):
        chief_from_omm({**_synthetic_record(), "ECCENTRICITY": 0.0017})


def test_omm_rejects_altitude_out_of_bounds():
    # MEAN_MOTION 1.0027 rev/day is the geosynchronous rate -> ~35787 km.
    with pytest.raises(ValueError):
        chief_from_omm({**_synthetic_record(), "MEAN_MOTION": 1.0027})


def test_omm_accepts_string_numeric_fields():
    numeric = chief_from_omm(_synthetic_record())
    as_strings = {
        key: value if key == "OBJECT_NAME" else str(value)
        for key, value in _synthetic_record().items()
    }
    assert chief_from_omm(as_strings) == numeric


def test_generated_scenario_passes_schema():
    chief = chief_from_omm(_synthetic_record())
    scenario = Scenario.model_validate(build_swarm_scenario(chief))
    assert scenario.formation.n_slots == len(scenario.roles)
    assert scenario.name.startswith("hypothetical-swarm-on-")


def test_generator_guards_survivor_minimum():
    # 5 - 3 = 2 survivors cannot fill leader + at least 1 imager + downlink.
    with pytest.raises(ValueError):
        build_swarm_scenario(chief_from_omm(_synthetic_record()), n_sats=5, n_failures=3)


def test_generator_gates_rounded_altitude():
    """The emitted scenario carries the 3-decimal-rounded altitude, so a chief
    that clears the raw gate by < 0.0005 km can round onto a schema bound."""
    with pytest.raises(ValueError):
        build_swarm_scenario({"name": "EDGE", "altitude_km": 160.0004})


def test_committed_firefly_swarm_matches_generator():
    """data/scenarios/firefly_swarm.json is the flagship demo scenario the
    cluster_import CLI generated from FIREFLY-1 (records[1], NORAD 62701).
    Pinning the committed file to a fresh build gives the byte-determinism
    check actual teeth: any drift in the generator's output or in the
    committed file fails here. Serialized exactly as the CLI writes scenario
    files: json.dumps(indent=2, sort_keys=True) plus a trailing newline."""
    chief = chief_from_omm(load_omm_records(FIREFLY_OMM)[1])
    expected = json.dumps(build_swarm_scenario(chief), indent=2, sort_keys=True) + "\n"
    assert FIREFLY_SWARM.read_text(encoding="utf-8") == expected


@pytest.fixture(scope="module")
def firefly_run():
    """FIREFLY-1 (records[1], NORAD 62701) generated into a full recovery run."""
    records = load_omm_records(FIREFLY_OMM)
    chief = chief_from_omm(records[1])
    assert chief["name"] == "FIREFLY-1"
    scenario = Scenario.model_validate(build_swarm_scenario(chief))
    return scenario, run_scenario(scenario)


def test_generated_swarm_from_real_snapshot_recovers(firefly_run):
    scenario, lines = firefly_run
    assert scenario.chief.altitude_km == pytest.approx(589.309, abs=0.01)
    assert len(_events(lines, "FAILURE_DETECTED")) == 2
    assert len(_events(lines, "ASSIGNMENT")) == 2
    ticks = [line for line in lines if line["state"] not in ("INIT", "SUMMARY")]
    assert "RECOVERED" in [line["state"] for line in ticks]
