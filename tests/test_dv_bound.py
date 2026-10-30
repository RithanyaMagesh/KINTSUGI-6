"""Δv lower-bound tests (ENDGAME_PLAN section 2 resolution method): the
two-impulse CW transfer solver and its log-analysis path. Zero core diffs --
imports only cubesat.hcw physics and the log schema, never cubesat.sim."""

from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

from cubesat.dv_bound import two_impulse_dv
from cubesat.hcw import mean_motion, propagate, slot_initial_state


def test_two_impulse_bound_properties():
    """Non-circular physics checks: a sat already on the target trajectory (the
    slot ellipse one full orbit later is the same trajectory) costs ~0; a real
    displacement costs > 0 with dv_total = dv1 + dv2; windows far from the
    t = k*pi/n singularities are recorded as such."""
    n = mean_motion(500_000.0)
    period = 2.0 * math.pi / n
    t0 = 1206.0
    slot = slot_initial_state(8000.0, 8000.0, 0.5236 + 2.0 * math.pi * 2 / 4, n)
    # A start state already ON the target trajectory costs ~0 at any
    # non-singular window (free propagation is the answer).
    on_traj = two_impulse_dv(propagate(slot, t0, n), slot, t0, t0 + 1710.0, n)
    assert on_traj["dv_total_mps"] < 1e-6
    # At exactly one orbital period (nt = 2*pi) the Phi_rv xy block is singular
    # (the t = k*pi/n hazard, ENDGAME_PLAN section 2): the guard must flag it --
    # the raw solve there returns garbage (~49 m/s instead of ~0), which is
    # exactly why singular solves are never quoted.
    one_orbit = two_impulse_dv(propagate(slot, t0, n), slot, t0, t0 + period, n)
    assert one_orbit["singular"]
    # A displaced start must pay, and the two impulses sum.
    x0 = propagate(slot, t0, n) + [3000.0, -6000.0, 500.0, 0.5, -3.0, 0.1]
    moved = two_impulse_dv(x0, slot, t0, t0 + 1710.0, n)
    assert moved["dv1_mps"] > 0.0 and moved["dv2_mps"] > 0.0
    assert moved["dv_total_mps"] == moved["dv1_mps"] + moved["dv2_mps"]
    # Singularity bookkeeping: nt = n*1710 = 1.892 rad, far from k*pi; the
    # 298 s truncated window sits 298 s from the k = 0 point (recorded, not
    # near-singular: sin(nt) = 0.324, well-conditioned solve).
    assert not moved["singular"] and moved["dist_to_singular_s"] > 100.0
    short = two_impulse_dv(x0, slot, t0, t0 + 298.0, n)
    assert abs(short["sin_nt"] - math.sin(n * 298.0)) < 1e-12
    assert not short["singular"]


def test_dv_bound_pure_log_analysis():
    """The dv-bound module is log analysis: importing it in a fresh interpreter
    must not pull in the sim core (same isolation contract as the P2 report)."""
    out = subprocess.run(
        [sys.executable, "-c", "import cubesat.dv_bound, sys; print('cubesat.sim' in sys.modules)"],
        capture_output=True, text=True, check=True,
    )
    assert out.stdout.strip() == "False"


def test_dv_bound_report_rows_carry_command_and_sha256():
    """Every committed number carries its command and its log sha256
    (AGENTS.md invariant 1); the G4-scale sat reproduces 193.68 m/s and the
    completed-transfer ratio is measured, not assumed."""
    from cubesat.dv_bound import run_dv_bound

    p0_dir = Path("data/eval/benchmark")
    if not (p0_dir / "pair_0-1__hungarian.jsonl").exists():
        import pytest

        pytest.skip("P0 logs are gitignored; regenerate with the benchmark command")
    import json

    base = json.loads(Path("data/scenarios/two_failure.json").read_text(encoding="utf-8"))
    report = run_dv_bound(
        base_scenario_path=Path("data/scenarios/two_failure.json"),
        p0_dir=p0_dir,
        policy="hungarian",
        command="test",
        n=mean_motion(base["chief"]["altitude_km"] * 1000.0),
    )
    assert len(report["pairs"]) == 15
    for row in report["pairs"]:
        assert row["command"] == "test"
        assert len(row["log_sha256"]) == 64
        assert row["bound_total_mps"] > 0.0
        assert row["completed_episode"]["bound_total_mps"] > 0.0
        assert row["min_dist_to_singular_s"] > 100.0
        assert row["n_singular_solves"] == 0
    h = report["headline"]
    assert abs(h["controller_dv_used_total_mps"] - 193.68) < 0.01
    assert h["ratio_completed"] > 1.0
    assert report["worst_completed_per_sat"]["ratio"] > h["ratio_completed"]


def test_dv_bound_g4_block_is_pair_1_2():
    """The G4-comparison block must name the pair two_failure.json actually is
    (sat 1 fails t=1200, sat 2 t=1500 => P0 pair (1,2), NOT (0,1): pair (0,1)'s
    worst per-sat dv is 172.75 m/s, not the G4 193.68), and the measured
    193.68-reproducing set must stay pinned: sat 0's whole-run total is
    identical in SEVEN pairs (1,2) (1,3) (1,4) (1,5) (3,4) (3,5) (4,5) -- in
    (4,5) sat 0 is not the worst sat (sat 2 spends 251.24 m/s)."""
    from cubesat.dv_bound import run_dv_bound

    p0_dir = Path("data/eval/benchmark")
    if not (p0_dir / "pair_0-1__hungarian.jsonl").exists():
        import pytest

        pytest.skip("P0 logs are gitignored; regenerate with the benchmark command")
    import json

    base = json.loads(Path("data/scenarios/two_failure.json").read_text(encoding="utf-8"))
    report = run_dv_bound(
        base_scenario_path=Path("data/scenarios/two_failure.json"),
        p0_dir=p0_dir,
        policy="hungarian",
        command="test",
        n=mean_motion(base["chief"]["altitude_km"] * 1000.0),
    )
    # The dedicated G4-comparison block is the two_failure pair (1,2).
    block = report["g4_headline_pair_1_2"]
    assert block["pair"] == [1, 2]
    assert abs(block["controller_worst_per_sat_mps"] - 193.68) < 0.01
    assert block["sat_id"] == 0
    assert report["headline"]["pair"] == [1, 2]
    # Measured set of (pair, sat) rows reproducing the G4 193.68 figure:
    # seven pairs, always sat 0 (review-fix pin, 2026-09-30).
    hits = {
        (tuple(row["pair"]), int(sat))
        for row in report["pairs"]
        for sat, dv in row["per_sat_controller_dv_mps"].items()
        if abs(dv - 193.68) < 0.01
    }
    assert hits == {
        ((1, 2), 0), ((1, 3), 0), ((1, 4), 0), ((1, 5), 0),
        ((3, 4), 0), ((3, 5), 0), ((4, 5), 0),
    }


# --- CLI path-confinement guard (audit: the benchmark.py guard had not been
#     rolled out here; mirrors tests/test_benchmark.py's guard tests) ---------


def test_dv_bound_cli_rejects_path_escaping_repo_root(capsys):
    """--report/--csv used to write to any path on disk (audit, low); the same
    confinement guard as cubesat/benchmark.py refuses with a clean argparse
    error (exit 2) BEFORE anything is read or written."""
    import pytest

    from cubesat.dv_bound import main

    root = Path(__file__).resolve().parents[1]
    escape_report = root.parent / "dv_bound_escape_probe_report.json"
    escape_csv = root.parent / "dv_bound_escape_probe.csv"
    for probe in (escape_report, escape_csv):
        if probe.exists():
            probe.unlink()  # stale-probe pre-clean only
    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "--base", "data/scenarios/two_failure.json",
                "--p0-dir", "data/eval/missing_p0_probe",
                "--report", str(escape_report),
                "--csv", "data/eval/dv_lower_bounds.csv",
            ]
        )
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "refusing" in err and "outside the repository" in err
    assert not escape_report.exists()
    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "--base", "data/scenarios/two_failure.json",
                "--p0-dir", "data/eval/missing_p0_probe",
                "--report", "data/eval/dv_lower_bounds.json",
                "--csv", str(escape_csv),
            ]
        )
    assert excinfo.value.code == 2
    assert "refusing" in capsys.readouterr().err
    assert not escape_csv.exists()
