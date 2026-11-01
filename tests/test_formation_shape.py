"""Track C phase C3: `formation.shape` (cartwheel default, pco, gco, helix, string)."""

import json
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from cubesat import formations as F
from cubesat.canon import _canon
from cubesat.hcw import mean_motion, slot_initial_state
from cubesat.scenario import Scenario, load_scenario
from cubesat.sim import build_slots

ROOT = Path(__file__).resolve().parents[1]
N = mean_motion(500e3)
NOMINAL = ROOT / "data" / "scenarios" / "nominal.json"
SHAPE_FILES = {s: ROOT / "data" / "scenarios" / f"formation_{s}_6sat.json" for s in F.SHAPES}


def _payload(**formation):
    d = json.loads(NOMINAL.read_text())
    d["formation"].update(formation)
    return d


def test_cartwheel_slots_are_bytewise_v1_including_signed_zeros():
    # tobytes, not array_equal: -0.0 vs 0.0 would print differently in the JSONL log
    for j, s in enumerate(F.formation_slots("cartwheel", 6, 8000.0, N)):
        ref = slot_initial_state(8000.0, 8000.0, 2.0 * np.pi * j / 6, N)
        assert s.tobytes() == ref.tobytes()


def test_build_slots_dispatches_on_shape():
    s = Scenario.model_validate({**_payload(shape="pco"), "engine": "v2"})
    got = build_slots(s, N)
    want = F.formation_slots("pco", 6, 11000.0, N)
    assert all(a.tobytes() == b.tobytes() for a, b in zip(got, want, strict=True))


def test_shape_defaults_to_cartwheel_and_is_left_out_of_the_dump():
    plain = Scenario.model_validate(_payload())
    explicit = Scenario.model_validate(_payload(shape="cartwheel"))
    assert plain.formation.shape == "cartwheel"
    assert plain.model_dump_json() == explicit.model_dump_json()  # fingerprint unchanged
    assert "shape" not in plain.model_dump_json()
    pco = Scenario.model_validate({**_payload(shape="pco"), "engine": "v2"})
    assert '"shape":"pco"' in pco.model_dump_json()  # non-default shapes are fingerprinted


@pytest.mark.parametrize("shape", [s for s in F.SHAPES if s != "cartwheel"])
def test_v1_engine_only_accepts_cartwheel(shape):
    with pytest.raises(ValidationError, match="engine"):
        Scenario.model_validate(_payload(shape=shape))
    assert Scenario.model_validate({**_payload(shape=shape), "engine": "v2"}).formation.shape


def test_unknown_shape_rejected():
    with pytest.raises(ValidationError):
        Scenario.model_validate({**_payload(shape="tetrahedron"), "engine": "v2"})


@pytest.mark.parametrize("shape", [s for s in F.SHAPES if s != "cartwheel"])
def test_formation_scenario_files_differ_only_in_name_and_shape(shape):
    base = load_scenario(SHAPE_FILES["cartwheel"])
    sc = load_scenario(SHAPE_FILES[shape])
    assert sc.engine == "v2" and sc.formation.shape == shape and not sc.failures
    formation = sc.formation.model_copy(update={"shape": "cartwheel"})
    same = sc.model_copy(update={"name": base.name, "formation": formation})
    assert same.model_dump_json() == base.model_dump_json()


@pytest.mark.parametrize("shape", F.SHAPES)
def test_formation_scenario_runs_in_engine_v2(shape):
    from cubesat.sim_v2 import EngineV2

    sc = load_scenario(SHAPE_FILES[shape]).model_copy(update={"duration_s": 10.0})
    lines = [ln for ln in EngineV2(sc).run() if "sats" in ln]
    want = F.formation_slots(shape, 6, 8000.0, mean_motion(500e3))
    assert np.allclose([s["r"] for s in lines[0]["sats"]], [w[:3] for w in want], atol=1e-6)


@pytest.mark.slow
def test_formations_report_regenerates_and_is_sane(tmp_path):
    from cubesat.benchmark import main

    committed = json.loads((ROOT / "data" / "eval" / "formations_report.json").read_text())
    out = tmp_path / "r.json"
    assert main(["--mode", "formations", "--base", str(SHAPE_FILES["cartwheel"]),
                 "--report", str(out)]) == 0
    got = json.loads(out.read_text())
    assert committed["command"] == (
        "uv run python -m cubesat.benchmark --mode formations --base "
        "data/scenarios/formation_cartwheel_6sat.json --report data/eval/formations_report.json"
    )
    for d in (committed, got):
        d.pop("command")
        d["inputs_sha256"] = {Path(k).name: v for k, v in d["inputs_sha256"].items()}
        for row in d["shapes"].values():
            row["scenario"] = Path(row["scenario"]).name
    # 5 significant digits (canon.py rule, AGENTS.md 9): LP/RK4 bits may differ across OSes
    assert _canon(got, 5, 1e-6) == _canon(committed, 5, 1e-6)
    sh = got["shapes"]
    assert sh["cartwheel"]["switch_from_cartwheel"]["total_dv_l1_mps"] == 0.0
    assert sh["cartwheel"]["cw_min_sep_m"] == pytest.approx(11313.7, abs=0.1)  # spec table
    assert sh["helix"]["cw_worst_sep_any_along_track_drift_m"] == pytest.approx(8000.0, abs=1)
    for row in sh.values():  # truth stays within 10 m of CW over 2 orbits at 8 km
        assert abs(row["truth_min_sep_m"] - row["cw_min_sep_m"]) < 10.0
