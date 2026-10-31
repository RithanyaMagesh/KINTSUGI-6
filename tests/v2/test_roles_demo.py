"""Measured role demonstration (Phase 5a): two_failure.json as engine v2 (a_max 0.01, spacecraft
block), every pair (i, j) of the 6 sats DEAD at 1200 / 1500 s, then 4-of-6 and 5-of-6 dead.
Roles are a pure capability assignment: no replan, no motion change, so this measures the
assignment rule, not a recovery planner (coverage is the surviving original imagers).

Command: uv run python -m pytest tests/v2/test_roles_demo.py -s -m slow
"""

import itertools
import json
from pathlib import Path

import pytest

from cubesat.scenario import Scenario
from cubesat.sim_v2 import EngineV2

ROOT = Path(__file__).resolve().parents[2]
BASE = json.loads((ROOT / "data" / "scenarios" / "two_failure.json").read_text())
BASE.update(engine="v2", a_max_mps2=0.01, spacecraft={})


def _last(dead: tuple[int, ...], times: tuple[float, ...], duration: float) -> dict:
    fails = [{"t": t, "sat_id": i, "mode": "DEAD"} for i, t in zip(dead, times, strict=True)]
    scn = Scenario.model_validate({**BASE, "failures": fails, "duration_s": duration})
    return [x for x in EngineV2(scn).run() if "sats" in x][-1]


def _held(line: dict) -> dict:
    alive = {s["id"] for s in line["sats"] if s["status"] != "DEAD"}
    out = {
        r: [s["id"] for s in line["sats"] if r in s["roles"]]
        for r in ("leader", "downlink", "imager")
    }
    assert all(i in alive for ids in out.values() for i in ids)  # nobody dead holds a role
    return out


@pytest.mark.slow
def test_two_failure_pairs_hold_both_critical_roles():
    print(f"\n{'pair':>6} {'leader':>6} {'downlink':>8} {'imagers':>7} {'coverage':>9}")
    ok, covs = 0, []
    for i, j in itertools.combinations(range(6), 2):
        line = _last((i, j), (1200.0, 1500.0), BASE["duration_s"])
        h = _held(line)
        both = len(h["leader"]) == 1 and len(h["downlink"]) == 1
        ok += both
        covs.append(line["coverage"])
        print(f"({i},{j}) {h['leader']!s:>6} {h['downlink']!s:>8} {len(h['imager']):>7}"
              f" {line['coverage']:>9.4f}")
    print(f"leader and downlink each held by one capable sat: {ok}/15")
    print(f"mean last-tick coverage over the 15 pairs: {sum(covs) / 15:.4f}")
    assert ok == 15


@pytest.mark.slow
@pytest.mark.parametrize("n_dead", [4, 5])
def test_four_and_five_of_six_dead_still_hold_every_role(n_dead):
    ok, imagers, covs = 0, [], []
    combos = list(itertools.combinations(range(6), n_dead))
    for dead in combos:
        times = tuple(1200.0 + 100.0 * k for k in range(n_dead))
        line = _last(dead, times, 2000.0)
        h = _held(line)
        imagers.append(len(h["imager"]))
        covs.append(line["coverage"])
        ok += all(len(h[r]) >= 1 for r in h) and len(h["leader"]) == len(h["downlink"]) == 1
    print(f"\n{n_dead} of 6 dead: leader + downlink + imager held in {ok}/{len(combos)} subsets;"
          f" imagers min {min(imagers)} mean {sum(imagers) / len(imagers):.2f};"
          f" last-tick coverage min {min(covs):.4f} mean {sum(covs) / len(covs):.4f}")
    assert ok == len(combos)


@pytest.mark.slow
def test_critical_vacancy_equals_the_detection_latency(tmp_path):
    """benchmark.metrics_from_log on v2 logs: a dead leader or downlink is vacant from the
    failure tick until the heartbeat declares it ((K - 1) dt = 4 s for K = 3, dt = 2 s)."""
    from cubesat.benchmark import metrics_from_log

    print(f"\n{'dead sats':>10} {'held at end':>11} {'vacancy s':>9} {'imagers':>7}")
    for dead in ((0,), (5,), (0, 5)):
        fails = [{"t": 100.0, "sat_id": i, "mode": "DEAD"} for i in dead]
        scn = Scenario.model_validate({**BASE, "failures": fails, "duration_s": 400.0})
        path = tmp_path / f"v{'_'.join(map(str, dead))}.jsonl"
        path.write_text("\n".join(json.dumps(x) for x in EngineV2(scn).run()) + "\n")
        m = metrics_from_log(path, first_failure_t=100.0, dead_ids=list(dead), duration_s=400.0)
        print(f"{dead!s:>10} {m['critical_roles_held_end']!s:>11} {m['critical_vacancy_s']:>9.1f}"
              f" {m['imagers_end']:>7}")
        assert m["critical_roles_held_end"] and m["critical_vacancy_s"] == 4.0
