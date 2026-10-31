"""P0 benchmark tests (docs/ENDGAME_PLAN.md section 3.5, test-first).

The seven required names:
    test_benchmark_enumerates_15_pairs
    test_benchmark_policies_registry_complete
    test_benchmark_double_run_byte_identical
    test_benchmark_replanning_rebinding_restored
    test_even_split_assigns_all_survivors_deterministically
    test_keepout_cost_never_negative
    test_benchmark_report_rows_carry_command_and_sha256

Monte Carlo robustness mode (P4, appended):
    test_mc_double_run_identical_report
    test_mc_jitter_within_bounds
    test_mc_report_rows_carry_command_and_sha

Benchmark-side only: the replan seam override rebinds cubesat.sim.replan inside
the process and MUST restore it (try/finally) -- asserted explicitly so sibling
in-process sim tests are never polluted. No RNG, no wall clock (AGENTS.md 2) --
except the MC driver's own seeded PCG64 jitter, which is asserted reproducible.
"""

import hashlib
import json
import math
import shutil
from pathlib import Path

import numpy as np
import pytest

import cubesat.allocate as allocate
import cubesat.sim as sim_module
from cubesat.benchmark import POLICY_ORDER, enumerate_pairs, main, run_benchmark
from cubesat.benchmark_policies import (
    W4,
    even_split_replan,
    hungarian_keepout_replan,
    keepout_penalties,
)
from cubesat.hcw import mean_motion, slot_initial_state
from cubesat.scenario import Failure, FailureMode, load_scenario

ROOT = Path(__file__).resolve().parents[1]
TWO_FAILURE = ROOT / "data" / "scenarios" / "two_failure.json"


def test_benchmark_enumerates_15_pairs():
    """C(6,2)=15 pairs in lexicographic order (itertools.combinations, index
    iteration only -- AGENTS.md invariant 2)."""
    pairs = enumerate_pairs(6)
    assert pairs == [
        (0, 1), (0, 2), (0, 3), (0, 4), (0, 5),
        (1, 2), (1, 3), (1, 4), (1, 5),
        (2, 3), (2, 4), (2, 5),
        (3, 4), (3, 5),
        (4, 5),
    ]
    assert len(pairs) == 15


def test_benchmark_policies_registry_complete():
    """Exactly the five plan policies, in the plan's fixed order."""
    assert POLICY_ORDER == (
        "do_nothing",
        "even_split",
        "greedy",
        "hungarian",
        "hungarian_keepout",
    )


@pytest.fixture(scope="module")
def scenario():
    return load_scenario(TWO_FAILURE)


def test_benchmark_double_run_byte_identical(scenario):
    """AGENTS.md invariant 2 through the benchmark driver: one pair x policy
    (full two_failure scale) replayed twice in-process gives identical logs
    (the tests/test_scenario_zoo.py double-replay pattern)."""
    from cubesat.benchmark import run_one

    pair_scenario = scenario.model_copy(
        update={
            "name": "bench_pair_0-1",
            "failures": [
                Failure(t=1200.0, sat_id=0, mode=FailureMode.DEAD),
                Failure(t=1500.0, sat_id=1, mode=FailureMode.DEAD),
            ],
        }
    )
    first = run_one(pair_scenario, "hungarian")
    second = run_one(pair_scenario, "hungarian")
    assert first == second


def test_benchmark_replanning_rebinding_restored(scenario):
    """After a benchmark run with a seam override, cubesat.sim.replan IS
    cubesat.allocate.replan again (ENDGAME_PLAN section 3.3 isolation)."""
    from cubesat.benchmark import run_one

    pair_scenario = scenario.model_copy(
        update={
            "name": "bench_pair_0-1",
            "failures": [
                Failure(t=1200.0, sat_id=0, mode=FailureMode.DEAD),
                Failure(t=1500.0, sat_id=1, mode=FailureMode.DEAD),
            ],
        }
    )
    run_one(pair_scenario, "even_split")
    assert sim_module.replan is allocate.replan


def _replan_inputs(scenario):
    """Synthetic replan() inputs matching pair (0, 1) at the first replan tick:
    survivors 2-5 (three imagers + downlink), the 6-slot original ellipse."""
    n = mean_motion(scenario.chief.altitude_km * 1000.0)
    amp = scenario.formation.radial_amp_km * 1000.0
    survivors = [slot_initial_state(amp, amp, 2.0 * math.pi * j / 6.0, n) for j in (2, 3, 4, 5)]
    obstacles = [slot_initial_state(amp, amp, 0.0, n)]
    from cubesat.coverage import footprint_radius, target_grid

    r_f = footprint_radius(
        scenario.chief.altitude_km * 1000.0, math.radians(scenario.sensor.fov_half_angle_deg)
    )
    grid = target_grid(
        scenario.sensor.grid_step_km * 1000.0, scenario.sensor.grid_extent_km * 1000.0
    )
    return {
        "survivor_states": survivors,
        "survivor_roles": ["imager", "imager", "imager", "downlink"],
        "survivor_fuel": [200.0] * 4,
        "obstacle_states": obstacles,
        "original_roles": list(scenario.roles),
        "allocation": scenario.allocation,
        "base_amp_m": amp,
        "r_f": r_f,
        "grid": grid,
        "n": n,
        "a_max": scenario.a_max_mps2,
        "t_replan": 1210.0,
    }


def test_even_split_assigns_all_survivors_deterministically(scenario):
    """Policy 2: survivor i in id order takes re-phased slot round(i*(6-1)/(k-1))
    (k = 4 -> phase indices {0, 2, 3, 5}), identity assignment, no sweep, and a
    second call reproduces the identical plan."""
    kwargs = _replan_inputs(scenario)
    plan, pairs, _total, method, _max_transfer, cost = even_split_replan(**kwargs)
    assert method == "even_split"
    assert pairs == [(0, 0), (1, 1), (2, 2), (3, 3)]
    assert len(plan.slots) == 4
    n = kwargs["n"]
    phase0 = math.radians(scenario.allocation.phase_sweep_deg[0])
    for i, slot_index in enumerate((0, 2, 3, 5)):
        expected = slot_initial_state(
            kwargs["base_amp_m"],
            kwargs["base_amp_m"],
            phase0 + 2.0 * math.pi * slot_index / 6.0,
            n,
        )
        assert np.allclose(plan.slots[i], expected)
    plan2, pairs2, total2, _m2, _mt2, cost2 = even_split_replan(**kwargs)
    assert pairs2 == pairs
    assert total2 == _total
    assert np.array_equal(cost, cost2)
    assert all(np.array_equal(a, b) for a, b in zip(plan.slots, plan2.slots, strict=True))


def test_keepout_cost_never_negative(scenario):
    """Policy 5: the keep-out penalty is clamp((r_ko - d)/r_ko, 0, 1) -- always in
    [0, 1], zero when the nearest dead sat is at/over the radius, clamped at 1
    when a dead sat sits on the seat -- and the augmented cost is never below the
    base cost matrix."""
    kwargs = _replan_inputs(scenario)
    r_ko = scenario.allocation.min_sep_km * 1000.0
    n = kwargs["n"]
    # No obstacle anywhere near the seats: zero penalty everywhere.
    seats = [
        slot_initial_state(kwargs["base_amp_m"], kwargs["base_amp_m"], 2.0 * math.pi * j / 6.0, n)
        for j in (2, 3, 4, 5)
    ]
    far = [slot_initial_state(kwargs["base_amp_m"], kwargs["base_amp_m"], 0.0, n)]
    pens_far = keepout_penalties(
        seats,
        far,
        r_ko_m=r_ko,
        n=n,
        t_replan=1210.0,
    )
    assert all(p == 0.0 for p in pens_far)
    # Obstacle exactly on a seat: penalty clamped to 1.
    on_seat = [
        slot_initial_state(kwargs["base_amp_m"], kwargs["base_amp_m"], 2.0 * math.pi * 3 / 6.0, n)
    ]
    pens_on = keepout_penalties(
        seats,
        on_seat,
        r_ko_m=r_ko,
        n=n,
        t_replan=0.0,
    )
    assert pens_on[1] == pytest.approx(1.0)
    assert all(0.0 <= p <= 1.0 for p in pens_on + pens_far)
    # Augmented cost >= base cost, entrywise (w4 pinned > 0).
    plan, _pairs, _total, method, _mt, cost = hungarian_keepout_replan(**kwargs)
    assert method == "hungarian_keepout"
    assert W4 == 1.0
    base_cost = allocate.build_cost_matrix(
        np.array([np.asarray(s)[:3] for s in kwargs["survivor_states"]]),
        np.array([allocate.propagate(s, kwargs["t_replan"], n)[:3] for s in plan.slots]),
        kwargs["survivor_fuel"],
        kwargs["survivor_roles"],
        plan.seat_roles,
        w1=scenario.allocation.w1,
        w2=scenario.allocation.w2,
        w3=scenario.allocation.w3,
    )
    assert np.all(cost >= base_cost - 1e-12)


def test_benchmark_report_rows_carry_command_and_sha256(scenario, tmp_path):
    """Every report row carries the exact command string and a log_sha256 that
    matches the sha256 of the written JSONL log (AGENTS.md invariant 1)."""
    base = scenario.model_copy(
        update={
            "name": "bench_short",
            "duration_s": 600.0,
            "failures": [
                Failure(t=100.0, sat_id=0, mode=FailureMode.DEAD),
                Failure(t=150.0, sat_id=1, mode=FailureMode.DEAD),
            ],
        }
    )
    report = run_benchmark(
        base=base,
        pairs=[(0, 1)],
        policies=["do_nothing", "even_split"],
        out_dir=tmp_path / "logs",
        report_path=tmp_path / "results.json",
        manifest_path=tmp_path / "manifest.json",
        command="uv run python -m cubesat.benchmark --test",
        failure_times=(100.0, 150.0),
    )
    assert (tmp_path / "results.json").exists()
    assert (tmp_path / "manifest.json").exists()
    for row in report["rows"]:
        assert row["command"] == "uv run python -m cubesat.benchmark --test"
        log_path = tmp_path / "logs" / row["log"]
        digest = hashlib.sha256(log_path.read_bytes()).hexdigest()
        assert row["log_sha256"] == digest
        assert row["pair"] == [0, 1]
        assert row["policy"] in ("do_nothing", "even_split")
        assert row["n_ticks"] > 0
        assert math.isfinite(row["coverage_mean_last_orbit"])
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["command"] == "uv run python -m cubesat.benchmark --test"
    assert set(manifest["logs"]) == {
        "pair_0-1__do_nothing.jsonl",
        "pair_0-1__even_split.jsonl",
    }


# --- Monte Carlo robustness mode (P4) ----------------------------------------


def _mc_base(scenario):
    """Short two-failure base for fast MC tests: same shape as two_failure.json
    but a 600 s horizon with failures at 100/150 s on sats 0/1 (the +-10% time
    jitter cannot reorder them: [90, 110] vs [135, 165])."""
    return scenario.model_copy(
        update={
            "name": "mc_short",
            "duration_s": 600.0,
            "failures": [
                Failure(t=100.0, sat_id=0, mode=FailureMode.DEAD),
                Failure(t=150.0, sat_id=1, mode=FailureMode.DEAD),
            ],
        }
    )


def test_mc_double_run_identical_report(scenario, tmp_path):
    """AGENTS.md invariant 2 through the MC driver: two full run_monte_carlo
    invocations with the same (base, runs, seed) give identical report dicts and
    byte-identical report/manifest/log files -- seeded PCG64 jitter outside the
    core, RNG-free core inside."""
    from cubesat.monte_carlo import run_monte_carlo

    first = run_monte_carlo(
        base=_mc_base(scenario),
        runs=2,
        seed=7,
        out_dir=tmp_path / "logs1",
        report_path=tmp_path / "r1.json",
        manifest_path=tmp_path / "m1.json",
        command="uv run python -m cubesat.benchmark --test",
    )
    second = run_monte_carlo(
        base=_mc_base(scenario),
        runs=2,
        seed=7,
        out_dir=tmp_path / "logs2",
        report_path=tmp_path / "r2.json",
        manifest_path=tmp_path / "m2.json",
        command="uv run python -m cubesat.benchmark --test",
    )
    assert first == second
    assert (tmp_path / "r1.json").read_bytes() == (tmp_path / "r2.json").read_bytes()
    assert (tmp_path / "m1.json").read_bytes() == (tmp_path / "m2.json").read_bytes()
    for log_path in sorted((tmp_path / "logs1").iterdir()):
        twin = tmp_path / "logs2" / log_path.name
        assert twin.read_bytes() == log_path.read_bytes()


def test_mc_jitter_within_bounds(scenario):
    """Every generated scenario sits inside the declared jitter -- failure times
    x (1 +- 0.10), formation phase_offset_deg +- 30, radial amplitude x [0.9,
    1.1] -- and keeps the fixed fields fixed: failure sat ids/modes, everything
    else byte-identical to the base scenario (comparability)."""
    from cubesat.monte_carlo import (
        FAILURE_TIME_REL_PM,
        PHASE_OFFSET_ABS_PM_DEG,
        RADIAL_AMP_REL,
        jitter_spec,
        jittered_scenario,
        mc_rng,
    )

    base = scenario  # full two_failure.json: failures at 1200/1500 s on sats 1/2
    spec = jitter_spec(123, base)
    assert spec["seed"] == 123
    assert spec["failure_time_rel_pm"] == 0.10
    assert spec["phase_offset_abs_pm_deg"] == 30.0
    assert spec["radial_amp_multiplier_range"] == [0.9, 1.1]
    rng = mc_rng(123)
    for i in range(40):
        jittered, drawn = jittered_scenario(base, rng, i)
        assert jittered.name == f"mc_run_{i:03d}"
        for f_base, f_jit in zip(base.failures, jittered.failures, strict=True):
            assert f_jit.sat_id == f_base.sat_id
            assert f_jit.mode == f_base.mode
            assert abs(f_jit.t / f_base.t - 1.0) <= FAILURE_TIME_REL_PM + 1e-12
        phase_delta = jittered.formation.phase_offset_deg - base.formation.phase_offset_deg
        assert abs(phase_delta) <= PHASE_OFFSET_ABS_PM_DEG + 1e-12
        mult = jittered.formation.radial_amp_km / base.formation.radial_amp_km
        assert 1.0 - RADIAL_AMP_REL - 1e-12 <= mult <= 1.0 + RADIAL_AMP_REL + 1e-12
        # The row's drawn block agrees with the scenario it describes.
        assert drawn["failure_times_s"] == [f.t for f in jittered.failures]
        assert drawn["phase_offset_deg"] == jittered.formation.phase_offset_deg
        assert drawn["radial_amp_multiplier"] == pytest.approx(mult, rel=0.0, abs=1e-15)
        # Everything except the three jitter groups stays fixed.
        assert jittered.duration_s == base.duration_s
        assert jittered.dt_s == base.dt_s
        assert jittered.roles == base.roles
        assert jittered.allocation == base.allocation
        assert jittered.gains == base.gains
        assert jittered.sensor == base.sensor
        assert jittered.seed == base.seed


def test_mc_report_rows_carry_command_and_sha(scenario, tmp_path):
    """Every MC report row carries the exact command string and a log_sha256
    matching the written JSONL log; report and manifest both carry the jitter
    spec (seed + bounds), so the whole ensemble regenerates from the command."""
    from cubesat.monte_carlo import MC_POLICIES, run_monte_carlo

    command = "uv run python -m cubesat.benchmark --mode monte-carlo --test"
    report = run_monte_carlo(
        base=_mc_base(scenario),
        runs=2,
        seed=42,
        out_dir=tmp_path / "logs",
        report_path=tmp_path / "results.json",
        manifest_path=tmp_path / "manifest.json",
        command=command,
    )
    assert (tmp_path / "results.json").exists()
    assert (tmp_path / "manifest.json").exists()
    assert len(report["rows"]) == 2 * len(MC_POLICIES)
    for row in report["rows"]:
        assert row["command"] == command
        log_path = tmp_path / "logs" / row["log"]
        assert row["log_sha256"] == hashlib.sha256(log_path.read_bytes()).hexdigest()
        assert row["policy"] in MC_POLICIES
        assert row["run"] in (0, 1)
        assert math.isfinite(row["coverage_mean_last_orbit"])
        assert math.isfinite(row["min_sep_survivor_dead_m"])
    persisted = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert persisted == report
    assert manifest["command"] == command
    assert manifest["jitter_spec"] == report["jitter_spec"]
    assert manifest["jitter_spec"]["seed"] == 42
    assert manifest["jitter_spec"]["radial_amp_multiplier_range"] == [0.9, 1.1]
    assert set(manifest["logs"]) == {row["log"] for row in report["rows"]}
    for entry in manifest["logs"].values():
        assert set(entry) == {"sha256", "run", "policy"}


# --- CLI path-confinement guard (Mimosa medium: command-line parameter ->
#     path traversal; mirrors files/predictor_pipeline.py) ---------------------


def test_cli_rejects_path_escaping_repo_root(capsys):
    """An --out (or --report) that resolves outside the repository root is
    refused with a clean argparse-style error (exit 2, 'refusing ... outside
    the repository' on stderr) BEFORE anything is read or written: the escape
    probe paths are never created. --base names a missing probe file so the
    guard must fire before even the base read (pre-guard this test fails with
    FileNotFoundError, never writing anything)."""
    escape_dir = ROOT.parent / "cubesat_escape_probe_out"
    escape_report = ROOT.parent / "cubesat_escape_probe_report.json"
    # Stale-probe pre-clean: only this cleanup may have created them; the test
    # asserts the CLI itself creates nothing.
    if escape_dir.exists():
        shutil.rmtree(escape_dir)
    if escape_report.exists():
        escape_report.unlink()
    missing_base = "data/scenarios/cli_probe_missing.json"
    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "--base", missing_base,
                "--out", str(escape_dir),
                "--report", "data/eval/benchmark_results.json",
            ]
        )
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "refusing" in err
    assert "outside the repository" in err
    assert not escape_dir.exists()
    # The flagged sink chain (--mode pareto: benchmark.py run_pareto dispatch ->
    # args.report write_text -> cubesat/pareto.py write_csv/write_svg): an
    # escaping --report is refused too.
    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "--base", missing_base,
                "--out", "data/eval/benchmark",
                "--report", str(escape_report),
            ]
        )
    assert excinfo.value.code == 2
    assert "refusing" in capsys.readouterr().err
    assert not escape_report.exists()


def test_cli_accepts_documented_paths(capsys):
    """Every documented GATES.md command's path shape still parses and passes
    the confinement guard (zero behavior change; all write under data/eval/).
    Each probe stops right after the guard -- benchmark mode on an unknown
    policy (argparse error), the other modes on the missing --base
    (FileNotFoundError) -- so no sim runs and nothing is written. Relative
    shapes are the exact GATES.md ones, invoked from the repo root like the
    documented commands."""
    # P0 (GATES.md:17): guard accepts the documented paths, argparse then
    # rejects the bogus policy -- the message must be about policies, not
    # refusal.
    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "--base", "data/scenarios/two_failure.json",
                "--out", "data/eval/benchmark",
                "--report", "data/eval/benchmark_results.json",
                "--policies", "do_nothing,not_a_policy",
            ]
        )
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "unknown policies" in err
    assert "refusing" not in err
    # P1-P4 (GATES.md:24,26,28,46): the guard accepts every documented shape;
    # dispatch then fails fast on the missing --base before any write.
    missing_base = "data/scenarios/cli_probe_missing.json"
    for extra in (
        ("--mode", "pareto", "--out", "data/eval/pareto",
         "--report", "data/eval/pareto_results.json"),
        ("--mode", "keepout-report", "--out", "data/eval/benchmark",
         "--report", "data/eval/benchmark_results.json"),
        ("--mode", "cw-curve", "--report", "data/eval/cw_error_report.json",
         "--csv", "data/eval/cw_error_curve.csv",
         "--svg", "data/eval/cw_error_curve.svg"),
        ("--mode", "monte-carlo", "--report",
         "data/eval/monte_carlo_results.json"),
    ):
        with pytest.raises(FileNotFoundError):
            main(["--base", missing_base, *extra])


def test_scenario_recovery_delay_default_zero():
    """recovery_delay_s defaults to 0.0, preserving immediate autonomous recovery."""
    sc = load_scenario(TWO_FAILURE)
    assert hasattr(sc, "recovery_delay_s")
    assert sc.recovery_delay_s == 0.0


def test_delayed_recovery_timing():
    """When recovery_delay_s=5400.0, sim stays in STATE_FAILURE_DETECTED until delay elapses."""
    sc = load_scenario(TWO_FAILURE)
    sc_delayed = sc.model_copy(update={"recovery_delay_s": 5400.0})
    lines = sim_module.run_scenario(sc_delayed)
    ticks = [line for line in lines if line["state"] not in ("INIT", "SUMMARY")]
    first_detect_tick = next(t for t in ticks if t["state"] == "FAILURE_DETECTED")
    replan_tick = next(t for t in ticks if t["state"] == "REPLANNING")
    t_detect = first_detect_tick["t"]
    t_replan = replan_tick["t"]
    assert t_replan >= t_detect + 5400.0 - 1e-9


def test_self_report_thruster_out_recovery_delay():
    """Self-reported THRUSTER_OUT failure initializes t_first_detect and honors recovery_delay_s."""
    sc = load_scenario(TWO_FAILURE)
    thruster_fail = Failure(t=1000.0, sat_id=1, mode=FailureMode.THRUSTER_OUT)
    sc_delayed = sc.model_copy(update={"failures": [thruster_fail], "recovery_delay_s": 5400.0})
    lines = sim_module.run_scenario(sc_delayed)
    ticks = [line for line in lines if line["state"] not in ("INIT", "SUMMARY")]
    first_detect_tick = next(t for t in ticks if t["state"] == "FAILURE_DETECTED")
    replan_tick = next(t for t in ticks if t["state"] == "REPLANNING")
    assert first_detect_tick["t"] == 1000.0
    assert replan_tick["t"] >= 1000.0 + 5400.0 - 1e-9

