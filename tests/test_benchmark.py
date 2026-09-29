"""P0 benchmark tests (docs/ENDGAME_PLAN.md section 3.5, test-first).

The seven required names:
    test_benchmark_enumerates_15_pairs
    test_benchmark_policies_registry_complete
    test_benchmark_double_run_byte_identical
    test_benchmark_replanning_rebinding_restored
    test_even_split_assigns_all_survivors_deterministically
    test_keepout_cost_never_negative
    test_benchmark_report_rows_carry_command_and_sha256

Benchmark-side only: the replan seam override rebinds cubesat.sim.replan inside
the process and MUST restore it (try/finally) -- asserted explicitly so sibling
in-process sim tests are never polluted. No RNG, no wall clock (AGENTS.md 2).
"""

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pytest

import cubesat.allocate as allocate
import cubesat.sim as sim_module
from cubesat.benchmark import POLICY_ORDER, enumerate_pairs, run_benchmark
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
