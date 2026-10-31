"""C5 comms benchmark: per-run metrics from synthetic log lines, cells, hypothesis verdicts."""

import json

import pytest

from cubesat.comms_bench import CELLS, NA_CELLS, kill_sets, run_metrics, verdicts


def _sat(i, status="NOMINAL", roles=("imager",)):
    return {"id": i, "status": status, "roles": list(roles), "role": roles[0] if roles else "none"}


def _tick(t, sats, comps=None, links=None, events=(), **extra):
    line = {"t": t, "state": "NOMINAL", "sats": sats, **extra}
    if comps is not None:
        line["components"], line["links"] = comps, links or []
    if events:
        line["event"], line["events"] = events[0], list(events)
    return line


def _det(sat, t_fail, t, cause=None):
    p = {"sat_id": sat, "t_fail": t_fail, "t_detect": t}
    if cause:
        p["cause"] = cause
    return {"type": "FAILURE_DETECTED", "payload": p}


LEAD, DOWN = ("leader", "imager"), ("downlink",)


def _laser_log():
    ok = [_sat(0, roles=LEAD), _sat(1), _sat(2, roles=DOWN)]
    dead = [_sat(0, "DEAD", LEAD), _sat(1), _sat(2, roles=DOWN)]
    handed = [_sat(0, "DEAD", ()), _sat(1, roles=LEAD), _sat(2, roles=DOWN)]
    up = [[0, 1, "LOCKED", 1.0, 1.0], [1, 2, "LOCKED", 1.0, 1.0]]
    return [
        {"state": "INIT", "t": 0.0},
        _tick(0.0, ok, [[0, 1, 2]], up),
        _tick(2.0, dead, [[1], [2]], [[1, 2, "ACQUIRING", 1.0, 0.0]]),  # partition, 1 and 2 alone
        _tick(4.0, dead, [[1], [2]], [[1, 2, "ACQUIRING", 1.0, 0.0]],
              events=[_det(0, 2.0, 4.0), _det(1, 2.0, 4.0, "isolated")]),
        _tick(6.0, handed, [[1, 2]], [[1, 2, "LOCKED", 1.0, 1.0]]),
        {"state": "SUMMARY", "t": 6.0, "coverage_mean_last_orbit": 0.25},
    ]


def test_run_metrics_on_a_hub_death():
    m = run_metrics(_laser_log(), killed=[0], first_failure_t=2.0, period_s=8.0, dt=2.0)
    assert m["detection_latency_s"] == 2.0
    assert m["false_isolations"] == 1
    assert m["isolated_sat_s"] == 8.0  # 2 sats x 2 ticks x 2 s
    assert m["partition_s"] == 4.0
    assert m["partition_s_per_orbit"] == pytest.approx(4.0 / (8.0 / 8.0))  # 8 s logged = 1 orbit
    assert m["locked_frac"] == pytest.approx(3 / 5)
    assert m["critical_vacancy_s"] == 4.0  # t = 2 and 4: dead leader is not service
    assert m["coverage_mean_last_orbit"] == 0.25


def test_ideal_log_has_no_link_metrics():
    lines = [_tick(0.0, [_sat(0, roles=LEAD), _sat(1, roles=DOWN)]),
             _tick(2.0, [_sat(0, roles=LEAD), _sat(1, roles=DOWN)])]
    m = run_metrics(lines, killed=[], first_failure_t=0.0, period_s=4.0, dt=2.0)
    assert m["locked_frac"] is None and m["partition_s"] is None
    assert m["detection_latency_s"] is None and m["false_isolations"] == 0


def test_decentral_leader_counts_as_held_when_no_function_is_vacant():
    sats = [_sat(0, roles=("imager",)), _sat(1, roles=DOWN)]
    lines = [_tick(0.0, sats, functions_vacant=["time_sync"]),
             _tick(2.0, sats, functions_vacant=[])]
    m = run_metrics(lines, killed=[], first_failure_t=0.0, period_s=4.0, dt=2.0)
    assert m["critical_vacancy_s"] == 2.0
    assert m["function_vacancy_s"] == 2.0


def test_cells_and_na_cells():
    assert [c["name"] for c in CELLS[:3]] == ["ideal-central", "laser-mesh-central",
                                              "laser-star-central"]
    assert {c["name"] for c in NA_CELLS} == {"ideal-decentral", "ideal-mesh/ideal-star"}


def test_kill_sets_are_15_pairs_plus_a_leader_kill():
    ks = kill_sets(6)
    assert len(ks) == 16 and ks[-1] == (0,)
    assert sum(1 for k in ks if 0 in k) == 6


def _row(cell, kills, **m):
    return {"cell": cell, "killed": list(kills), **m}


def test_verdicts_apply_the_preregistered_thresholds():
    ks = kill_sets(6)
    rows = []
    for k in ks:
        rows.append(_row("ideal-central", k, detection_latency_s=4.0, critical_vacancy_s=6.0))
        rows.append(_row("laser-mesh-central", k, detection_latency_s=4.0, false_isolations=0,
                         partition_s_per_orbit=300.0, locked_frac=0.97, critical_vacancy_s=8.0))
        rows.append(_row("laser-star-central", k, false_isolations=1 if 0 in k else 0))
    v = verdicts(rows)
    assert [v[h]["verdict"] for h in ("C5-H1", "C5-H2", "C5-H3", "C5-H4", "C5-H5", "C5-H6")] \
        == ["PASS"] * 6
    rows[1]["critical_vacancy_s"] = 8.1  # 2.1 s over ideal on one kill set
    assert verdicts(rows)["C5-H5"]["verdict"] == "FAIL"
    assert v["C5-H7"]["verdict"] == "unmeasured"  # authority cells not run


def test_a_cell_field_the_engine_does_not_know_is_refused_not_ignored():
    from cubesat.comms_bench import _scenario
    from cubesat.scenario import Scenario

    base = {"name": "x"}
    bogus = {"name": "bogus", "update": {"no_such_field": 1}}
    with pytest.raises(ValueError, match="no_such_field"):
        _scenario(base, bogus, (0,))
    if "recovery" not in Scenario.model_fields:  # before C4: decentral is unmeasured
        with pytest.raises(ValueError, match="recovery"):
            _scenario(base, CELLS[3], (0,))


def test_decentral_rounds_handoffs_and_round_time_sensitivity():
    sats = [_sat(0, roles=("imager",)), _sat(1, roles=DOWN)]
    hand = {"type": "FUNCTION_HANDOFF",
            "payload": {"function": "time_sync", "from": [0], "to": [1]}}
    lines = [_tick(0.0, sats, functions_vacant=[], consensus_rounds=18, split_brain=[]),
             _tick(2.0, sats, functions_vacant=["time_sync"], consensus_rounds=18, split_brain=[]),
             _tick(4.0, sats, functions_vacant=["time_sync"], consensus_rounds=18, split_brain=[]),
             _tick(6.0, sats, functions_vacant=["time_sync"], consensus_rounds=18, split_brain=[]),
             _tick(8.0, sats, functions_vacant=[], consensus_rounds=2, split_brain=[],
                   events=[hand])]
    m = run_metrics(lines, killed=[], first_failure_t=1.0, period_s=10.0, dt=2.0)
    assert m["function_vacancy_s"] == 6.0
    assert m["consensus_rounds_max"] == 18  # max per-tick value at or after the first failure
    assert m["function_handoffs"] == 1
    # the 6 s window closed by an auction of 2 rounds: 6 - 2 * 2 + 2 * tau, floored at 0
    assert m["function_vacancy_s_by_round_time"] == pytest.approx({"0.1": 2.2, "0.5": 3.0,
                                                                    "2.0": 6.0})


def test_killed_sat_isolations_and_undetected_deaths_are_reported():
    sats = [_sat(0, roles=LEAD), _sat(1, roles=DOWN), _sat(2)]
    lines = [_tick(0.0, sats, [[0, 1, 2]]),
             _tick(2.0, sats, [[0, 1], [2]], events=[_det(2, 0.0, 2.0, "isolated")]),
             _tick(4.0, sats, [[0, 1]], events=[_det(0, 2.0, 4.0)])]
    m = run_metrics(lines, killed=[0, 2], first_failure_t=2.0, period_s=6.0, dt=2.0)
    assert m["false_isolations"] == 0  # pre-registered: never-killed sats only
    assert m["killed_sat_isolations"] == 1
    assert m["killed_detected"] == 1  # sat 2 died while declared isolated: never detected


def test_nested_cell_typos_are_refused_not_ignored():
    from cubesat.comms_bench import _scenario

    base = json.loads(open("data/scenarios/two_failure.json").read())
    typo = {"name": "t", "update": {"comms": {"model": "laser", "topolgy": "star"}}}
    with pytest.raises(ValueError, match="no field .*topolgy"):
        _scenario(base, typo, (0,))
    _scenario(base, CELLS[4], (0,))  # every real cell passes the guard
