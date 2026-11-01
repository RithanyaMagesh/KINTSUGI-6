"""Critical-role metrics for the benchmark (problem statement: "maintain
mission-critical coverage"; docs/superpowers/specs/KINTSUGI-6_v2_master_map.md D3).

Definitions (derived from log bytes only, NOMINAL holders only -- a DEAD or
DEGRADED sat holding a role label does not count as holding it):
    critical_roles_held_end  leader AND downlink each on a NOMINAL sat, final tick
    critical_seat_frac       fraction of ticks with t >= first failure where both held
    critical_vacancy_s       seconds (ticks x dt) with t >= first failure where either
                             critical role has no NOMINAL holder; includes detection latency
    imagers_end              count of NOMINAL imagers on the final tick
"""

from pathlib import Path

import pytest

from cubesat.benchmark import (
    _policies_summary,
    _write_log,
    metrics_from_log,
    run_one,
    scenario_for_pair,
)
from cubesat.scenario import load_scenario

ROOT = Path(__file__).resolve().parents[1]
TWO_FAILURE = ROOT / "data" / "scenarios" / "two_failure.json"


def _tick(t, sats):
    return {
        "v": 1, "t": t, "state": "NOMINAL", "coverage": 0.3, "min_sep": 5000.0,
        "sats": [
            {"id": i, "role": role, "status": status, "r": [0.0, 0.0, 0.0],
             "v": [0.0, 0.0, 0.0], "dv_used": 0.0}
            for i, (role, status) in enumerate(sats)
        ],
    }


def _write(tmp_path, ticks):
    lines = [{"v": 1, "t": 0.0, "state": "INIT", "scenario": "x", "seed": 0, "n_sats": 3}]
    lines += ticks
    lines.append({"v": 1, "t": ticks[-1]["t"], "state": "SUMMARY", "coverage_mean_last_orbit": 0.3})
    path = tmp_path / "log.jsonl"
    _write_log(lines, path)
    return path


def test_critical_metrics_synthetic(tmp_path):
    """dt=2. t=0,2: all held. t=4,6: downlink sat dead (vacant). t=8,10: swap done,
    leader+downlink on NOMINAL sats again. first failure at t=4."""
    ok = [("leader", "NOMINAL"), ("imager", "NOMINAL"), ("downlink", "NOMINAL")]
    dead = [("leader", "NOMINAL"), ("imager", "NOMINAL"), ("downlink", "DEAD")]
    healed = [("leader", "NOMINAL"), ("downlink", "NOMINAL"), ("downlink", "DEAD")]
    ticks = [_tick(0.0, ok), _tick(2.0, ok), _tick(4.0, dead), _tick(6.0, dead),
             _tick(8.0, healed), _tick(10.0, healed)]
    path = _write(tmp_path, ticks)
    m = metrics_from_log(path, first_failure_t=4.0, dead_ids=[2], duration_s=10.0)
    assert m["critical_roles_held_end"] is True
    assert m["critical_vacancy_s"] == pytest.approx(4.0)  # ticks t=4,6 x dt 2
    assert m["critical_seat_frac"] == pytest.approx(0.5)  # 2 of 4 ticks with t>=4
    assert m["imagers_end"] == 0


def test_critical_metrics_never_healed(tmp_path):
    ok = [("leader", "NOMINAL"), ("imager", "NOMINAL"), ("downlink", "NOMINAL")]
    dead = [("leader", "NOMINAL"), ("imager", "NOMINAL"), ("downlink", "DEAD")]
    ticks = [_tick(0.0, ok), _tick(2.0, dead), _tick(4.0, dead)]
    m = metrics_from_log(_write(tmp_path, ticks), first_failure_t=2.0, dead_ids=[2], duration_s=4.0)
    assert m["critical_roles_held_end"] is False
    assert m["critical_vacancy_s"] == pytest.approx(4.0)
    assert m["critical_seat_frac"] == pytest.approx(0.0)
    assert m["imagers_end"] == 1


def test_summary_counts_pairs_with_critical_roles_held():
    def row(policy, held, frac, vac):
        return {
            "policy": policy, "coverage_mean_last_orbit": 0.27, "total_dv_mps": 1.0,
            "per_sat_dv_mps": [0.5], "min_sep_survivor_dead_m": 3000.0,
            "gain_vs_do_nothing_pts": 0.0, "critical_roles_held_end": held,
            "critical_seat_frac": frac, "critical_vacancy_s": vac, "imagers_end": 2,
        }
    rows = [row("hungarian", True, 0.99, 8.0), row("hungarian", True, 0.97, 12.0),
            row("do_nothing", False, 0.0, 100.0), row("do_nothing", True, 1.0, 0.0)]
    s = _policies_summary(rows, ["hungarian", "do_nothing"])
    assert s["hungarian"]["pairs_critical_roles_held"] == 2
    assert s["do_nothing"]["pairs_critical_roles_held"] == 1
    assert s["hungarian"]["mean_critical_seat_frac"] == pytest.approx(0.98)
    assert s["hungarian"]["mean_critical_vacancy_s"] == pytest.approx(10.0)
    assert s["do_nothing"]["worst_critical_vacancy_s"] == pytest.approx(100.0)


@pytest.mark.parametrize("policy,expected", [("do_nothing", False), ("hungarian", True)])
def test_pair_0_5_kills_both_critical_seats(tmp_path, policy, expected):
    """Pair (0,5) kills the leader and the downlink: do-nothing leaves both roles
    vacant for the rest of the run; recovery must refill both."""
    base = load_scenario(TWO_FAILURE)
    sc = scenario_for_pair(base, (0, 5), (1200.0, 1500.0))
    path = tmp_path / f"{policy}.jsonl"
    _write_log(run_one(sc, policy), path)
    m = metrics_from_log(path, first_failure_t=1200.0, dead_ids=[0, 5], duration_s=sc.duration_s)
    assert m["critical_roles_held_end"] is expected
    if expected:
        assert m["critical_vacancy_s"] < 600.0  # healed within a replan or two
    else:
        assert m["critical_vacancy_s"] == pytest.approx(sc.duration_s - 1200.0 + 2.0, abs=4.0)
