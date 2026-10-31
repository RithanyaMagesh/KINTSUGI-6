"""P2 keep-out report tests (docs/ENDGAME_PLAN.md section 5, test-first).

The two required names:
    test_keepout_report_pure_log_analysis
    test_dead_drift_clearance_reported

The analysis path is pure log analysis: cubesat/keepout.py imports no sim
internals beyond the log schema (asserted in a fresh interpreter). No RNG, no
wall clock (AGENTS.md invariant 2).
"""

import math
import subprocess
import sys
from pathlib import Path

import pytest

from cubesat.hcw import mean_motion
from cubesat.keepout import (
    dead_death_states,
    drift_horizon_clearance,
    keepout_report,
    keepout_verdict,
    secular_drift_rate,
)
from cubesat.scenario import Failure, FailureMode, load_scenario

ROOT = Path(__file__).resolve().parents[1]
TWO_FAILURE = ROOT / "data" / "scenarios" / "two_failure.json"


def test_keepout_report_pure_log_analysis(tmp_path):
    """(1) A fresh interpreter can import cubesat.keepout WITHOUT pulling in
    cubesat.sim or the benchmark driver -- the code path consumes only log
    bytes, hcw.propagate and mean_motion (ENDGAME_PLAN 5 'module' note).
    (2) Functionally, the report runs on a tiny written log and carries every
    section-5 field with finite values and an honest horizon."""
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import cubesat.keepout, sys\n"
            "assert 'cubesat.sim' not in sys.modules, 'keepout imported the sim core'\n"
            "assert 'cubesat.benchmark' not in sys.modules, 'keepout imported the driver'\n",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr

    scenario = load_scenario(TWO_FAILURE).model_copy(
        update={
            "name": "keepout_short",
            "duration_s": 600.0,
            "failures": [
                Failure(t=100.0, sat_id=0, mode=FailureMode.DEAD),
                Failure(t=150.0, sat_id=1, mode=FailureMode.DEAD),
            ],
        }
    )
    from cubesat.benchmark import _write_log, run_one

    log_dir = tmp_path / "logs"
    for policy in ("do_nothing", "hungarian"):
        _write_log(run_one(scenario, policy), log_dir / f"pair_0-1__{policy}.jsonl")

    n = mean_motion(scenario.chief.altitude_km * 1000.0)
    report = keepout_report(
        log_paths={
            "do_nothing": [log_dir / "pair_0-1__do_nothing.jsonl"],
            "hungarian": [log_dir / "pair_0-1__hungarian.jsonl"],
        },
        n=n,
        tick_dt=scenario.dt_s,
        keepout_radius_m=scenario.allocation.min_sep_km * 1000.0,
        command="pytest test_keepout_report_pure_log_analysis",
    )
    assert set(report["policies"]) == {"do_nothing", "hungarian"}
    for _pol, entries in report["per_policy"].items():
        assert len(entries) == 2  # one per dead sat of the pair
        for e in entries:
            assert e["t_death_s"] in (100.0, 150.0)
            assert math.isfinite(e["drift_rate_mps"])
            assert math.isfinite(e["run_window_min_clearance_m"])
            assert e["effective_horizon_s"] <= 600.0 + 1e-9
            assert e["effective_horizon_orbits"] <= 3.0 + 1e-9
            assert math.isfinite(e["min_clearance_logged_overlap_m"])
            assert math.isfinite(e["counterfactual_min_clearance_full_horizon_m"])
            assert e["n_samples_past_log_end_labeled_counterfactual"] >= 0
    comp = report["keepout_binding_comparison"]
    assert comp["keepout_radius_m"] == pytest.approx(2000.0)
    assert comp["decision"] in ("KEEP", "CUT")
    assert comp["decision_text"]
    assert report["j2_drag_caveat"]


def test_dead_drift_clearance_reported():
    """A dead sat that dies OFF its drift-free condition (vy0 != -2 n x0)
    carries the CW secular along-track drift term: the reported drift rate is
    the STM secular slope -(6 n x0 + 3 vy0), and the clearance over the drift
    horizon decays below the run-window clearance."""
    n = mean_motion(500_000.0)
    dt = 2.0
    # Dead state OFF the drift-free condition: x0 = 0, vy0 = -10 (drift-free
    # would be vy0 = -2 n x0 = 0). Secular drift rate = -(3 * vy0) = +30 m/s.
    y0 = 10000.0
    vy0 = -10.0
    drift_expected = -(6.0 * n * 0.0 + 3.0 * vy0)
    assert abs(drift_expected) > 10.0  # a real drift, not a numerical speck
    # Synthetic log: survivor pinned at the origin (logged positions only);
    # sat 1 goes DEAD at t = 100 s from [0, y0, 0, 0, vy0, 0]. The secular
    # along-track drift carries it ~4 km closer to the survivor inside the
    # logged window (verified numerically with hcw.propagate before pinning).
    ticks = []
    for k in range(501):
        t = k * dt
        is_dead = t >= 100.0 - 1e-9
        sats = [
            {"id": 0, "role": "imager", "status": "NOMINAL",
             "r": [0.0, 0.0, 0.0], "v": [0.0, 0.0, 0.0], "dv_used": 0.0},
            {"id": 1, "role": "imager",
             "status": "DEAD" if is_dead else "NOMINAL",
             "r": [0.0, y0, 0.0], "v": [0.0, vy0, 0.0], "dv_used": 0.0},
        ]
        ticks.append({"t": t, "state": "NOMINAL", "sats": sats,
                      "coverage": 0.5, "min_sep": y0})
    deaths = dead_death_states(ticks)
    assert [d["sat_id"] for d in deaths] == [1]
    assert deaths[0]["t_death_s"] == pytest.approx(100.0)
    assert secular_drift_rate(deaths[0], n) == pytest.approx(drift_expected, rel=1e-9)

    horizon = 3.0 * 2.0 * math.pi / n
    h = drift_horizon_clearance(
        ticks, deaths[0], survivor_ids=[0], n=n, horizon_s=horizon,
        log_end=ticks[-1]["t"], tick_dt=dt, n_samples=601,
    )
    # Run window: dead sat sits at [0, y0, 0] the whole time -> clearance y0.
    assert h["run_window_min_clearance_m"] == pytest.approx(y0, rel=1e-9)
    # Drift horizon: the secular term carries the dead sat toward the survivor.
    assert h["min_clearance_logged_overlap_m"] < 0.7 * y0
    # Log ends at 1000 s, so most of the 3-orbit horizon is counterfactual.
    assert h["effective_horizon_s"] == pytest.approx(1000.0)
    assert h["n_samples_past_log_end_labeled_counterfactual"] > 300
    assert h["counterfactual_min_clearance_full_horizon_m"] <= h["min_clearance_logged_overlap_m"]


R = 2000.0


def test_verdict_exclusion_helps_is_keep():
    """Both runs bind, the exclusion RAISES the worst clearance -> KEEP, and the
    sentence says improves and names both policies with their numbers."""
    decision, text = keepout_verdict(1500.0, 1800.0, True, True, False, R)
    assert decision == "KEEP"
    assert "improves" in text and "worsens" not in text
    assert "1500.0 m" in text and "1800.0 m" in text
    assert "hungarian_keepout" in text and "hungarian" in text


def test_verdict_exclusion_hurts_is_cut():
    """C-1 regression: the committed artifact had 1852.5 m without, 1322.6 m with
    and still printed 'improves' + KEEP. Lower clearance with the exclusion must
    be CUT and must say worsens."""
    decision, text = keepout_verdict(1852.5, 1322.6, True, True, False, R)
    assert decision == "CUT"
    assert "worsens" in text and "improves" not in text
    assert "1852.5 m" in text and "1322.6 m" in text


def test_verdict_tie_is_cut():
    """Different trajectories but the same worst clearance: no measured benefit."""
    decision, text = keepout_verdict(1700.0, 1700.0, True, True, False, R)
    assert decision == "CUT"
    assert "improves" not in text and "worsens" not in text
    assert "unchanged" in text


def test_verdict_identical_and_never_binding_are_cut():
    d1, t1 = keepout_verdict(1322.6, 1322.6, True, True, True, R)
    assert d1 == "CUT" and "never fired" in t1
    d2, t2 = keepout_verdict(2500.0, 2600.0, False, False, False, R)
    assert d2 == "CUT" and "never binding" in t2


def test_report_notes_state_do_no_harm_confound(tmp_path):
    """The A/B changes two things at once (exclusion term AND the do-no-harm
    hold, which hungarian_keepout lacks): the report must say so."""
    scenario = load_scenario(TWO_FAILURE).model_copy(
        update={
            "name": "keepout_notes",
            "duration_s": 600.0,
            "failures": [
                Failure(t=100.0, sat_id=0, mode=FailureMode.DEAD),
                Failure(t=150.0, sat_id=1, mode=FailureMode.DEAD),
            ],
        }
    )
    from cubesat.benchmark import _write_log, run_one

    log = tmp_path / "pair_0-1__hungarian.jsonl"
    _write_log(run_one(scenario, "hungarian"), log)
    report = keepout_report(
        log_paths={"hungarian": [log]},
        n=mean_motion(scenario.chief.altitude_km * 1000.0),
        tick_dt=scenario.dt_s,
        keepout_radius_m=2000.0,
        command="pytest",
    )
    assert "do-no-harm" in report["notes"]
