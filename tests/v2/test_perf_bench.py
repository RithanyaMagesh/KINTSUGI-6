"""`--mode perf` (cubesat/perf_bench.py): report shape, no timing inside any log, CLI dispatch."""

import json
import shutil
from pathlib import Path

import pytest

from cubesat import benchmark, perf_bench
from cubesat.canon import canonical_log_hash
from cubesat.scenario import Scenario
from cubesat.sim import run_scenario

STAT_KEYS = {"median", "min", "max", "n"}
TINY_SCENARIO = {  # 2 sats, 20 s, one DEAD at t=6 (same shape as tests/conftest.py TINY_SCENARIO)
    "name": "tiny", "seed": 7, "duration_s": 20.0, "dt_s": 2.0, "chief": {"altitude_km": 500.0},
    "formation": {"n_slots": 2, "radial_amp_km": 1.0, "phase_offset_deg": 0.0},
    "a_max_mps2": 0.01, "gains": {"wn": 0.01, "zeta": 1.0},
    "sensor": {"fov_half_angle_deg": 1.5, "grid_step_km": 5.0, "grid_extent_km": 5.0},
    "roles": ["leader", "imager"], "failures": [{"t": 6.0, "sat_id": 0, "mode": "DEAD"}],
}


@pytest.fixture(scope="module")
def tiny_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("perf_scn")
    (d / "tiny.json").write_text(json.dumps(TINY_SCENARIO), encoding="utf-8")
    return d


@pytest.fixture(scope="module")
def report(tiny_dir) -> dict:
    out = tiny_dir / "perf.json"
    return perf_bench.run_perf(
        tiny_dir, out, repeats=1, variants=("tiny",), profile=("tiny", "tiny@v2"),
        ws_scenario="tiny", ws_speeds=(1e6,), ws_window_s=2.0, command="test",
    )


def test_report_has_the_documented_keys(report, tiny_dir):
    for key in ("schema", "command", "repeats", "machine", "load", "machine_busy", "inputs",
                "scenarios", "websocket", "notes"):
        assert key in report
    assert {"platform", "cpu_count", "python", "numpy"} <= set(report["machine"])
    assert set(report["load"]) == {"start", "end"}
    assert isinstance(report["machine_busy"], bool)
    sha = report["inputs"]["tiny.json"]
    assert len(sha) == 64 and sha == perf_bench.sha256_file(tiny_dir / "tiny.json")
    assert json.loads((tiny_dir / "perf.json").read_text()) == report


def test_every_scenario_row_is_complete(report):
    ids = [row["id"] for row in report["scenarios"]]
    assert ids == ["tiny", "tiny@v2"]
    for row in report["scenarios"]:
        assert row["variant"] == (row["id"] == "tiny@v2")
        for key in ("compute_s", "setup_s", "first_frame_s"):
            assert STAT_KEYS == set(row[key])
        assert set(row["inject_s"]) == {"25", "50", "75"}
        assert all(STAT_KEYS == set(v) for v in row["inject_s"].values())
        assert STAT_KEYS == set(row["tick_ms_mean"]) == set(row["tick_ms_p95"])
        wire = row["wire"]
        assert wire["bytes_per_frame_mean"] > 0 and wire["to_messages_us"]["n"] == 1
        assert len(row["profile"]) > 0 and {"function", "tottime_s"} <= set(row["profile"][0])


def test_websocket_section_measures_a_real_socket(report):
    ws = report["websocket"]
    assert ws["feasible"] is True and ws["scenario"] == "tiny"
    (row,) = ws["runs"]
    assert row["speed"] == 1e6 and row["sim_states_received"] > 0 and row["frames_total"] == 11


def test_timing_instrumentation_never_changes_a_log():
    v1 = Scenario.model_validate(TINY_SCENARIO)
    v2 = Scenario.model_validate({**TINY_SCENARIO, "engine": "v2"})
    for scn in (v1, v2):
        plain = canonical_log_hash(run_scenario(scn))
        timer = perf_bench.TickTimer()
        timed = canonical_log_hash(run_scenario(scn, timer))
        assert plain == timed
        assert len(timer.stamps) >= scn.n_sats  # the hook really fired once per tick
        assert "perf" not in json.dumps(run_scenario(scn, perf_bench.TickTimer()))


def test_cli_dispatch_writes_the_report(tiny_dir):
    out = Path(".pytest_tmp") / "perf_cli" / "perf.json"  # --report must stay inside the repo
    shutil.rmtree(out.parent, ignore_errors=True)
    rc = benchmark.main(
        ["--mode", "perf", "--base", str(tiny_dir), "--report", str(out), "--repeats", "1"]
    )
    assert rc == 0
    data = json.loads(out.read_text())
    assert data["repeats"] == 1 and data["command"].endswith("--repeats 1")
    assert data["websocket"]["feasible"] is False  # default ws scenario is not in tiny_dir


def test_gc_probe_reports_both_modes_and_leaves_gc_enabled(tiny_dir):
    import gc

    from cubesat import perf_gc

    out = Path(".pytest_tmp") / "perf_gc" / "gc.json"
    shutil.rmtree(out.parent, ignore_errors=True)
    data = perf_gc.run_gc_probe(tiny_dir, "tiny", out, repeats=2, command="test")
    assert gc.isenabled()
    assert set(data["modes"]) == {"gc_on", "gc_off"}
    for mode in data["modes"].values():
        assert STAT_KEYS == set(mode["total_s"]) == set(mode["tick_ms_max"])
        assert mode["total_s"]["n"] == 2 and set(mode["n_ticks_over_5ms"]) == STAT_KEYS
    assert data["inputs"]["tiny.json"] == perf_bench.sha256_file(tiny_dir / "tiny.json")
    assert json.loads(out.read_text()) == data
