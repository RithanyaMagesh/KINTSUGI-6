"""Best-case promotion baseline: like role_swap_only (zero Δv, seats kept) but each lost critical
role goes to the survivor whose promotion keeps the most coverage (audit C-4 upper-bound check)."""

import itertools
from pathlib import Path

import cubesat.sim as sim_module
from cubesat.allocate import _coverage_estimate
from cubesat.benchmark import ALL_POLICIES, run_one, scenario_for_pair
from cubesat.benchmark_policies import role_swap_best_replan, role_swap_only_replan
from cubesat.scenario import load_scenario

TWO_FAILURE = Path(__file__).resolve().parents[1] / "data" / "scenarios" / "two_failure.json"


def _captured_replan_args(pair):
    """The exact replan arguments the sim passes for one two-failure pair (last replan)."""
    seen = []

    def spy(*args, **kwargs):
        seen.append((args, kwargs))
        return role_swap_only_replan(*args, **kwargs)

    original, sim_module.replan = sim_module.replan, spy
    try:
        base = load_scenario(TWO_FAILURE)
        sim_module.run_scenario(scenario_for_pair(base, pair, (1200.0, 1500.0)))
    finally:
        sim_module.replan = original
    return seen[-1]


def test_best_promotion_is_the_coverage_maximum_over_every_promotee_choice():
    args, kwargs = _captured_replan_args((0, 5))
    roles = ["imager"] * len(args[1])  # force leader AND downlink lost on the real geometry
    args = (args[0], roles, *args[2:])
    plan = role_swap_best_replan(*args, **kwargs)[0]
    pool = [i for i, r in enumerate(roles) if r not in ("leader", "downlink")]
    best = 0.0
    for a, b in itertools.permutations(pool, 2):
        trial = list(roles)
        trial[a], trial[b] = "leader", "downlink"
        cov = _coverage_estimate(list(kwargs["current_slots"]), trial, r_f=args[7],
                                 grid=args[8], n=args[9], t_replan=args[11])
        best = max(best, cov)
    assert plan.coverage == best
    assert sorted(plan.seat_roles).count("leader") == 1
    assert sorted(plan.seat_roles).count("downlink") == 1
    only = role_swap_only_replan(*args, **kwargs)[0]
    assert plan.coverage >= only.coverage


def test_best_promotion_is_zero_dv_and_keeps_seats():
    args, kwargs = _captured_replan_args((1, 5))
    plan, pairs, total, method, max_transfer, _ = role_swap_best_replan(*args, **kwargs)
    assert plan.slots == list(kwargs["current_slots"])
    assert pairs == [(i, i) for i in range(len(args[1]))]
    assert (total, method, max_transfer) == (0.0, "role_swap_best", 0.0)


def test_policy_is_runnable_from_the_benchmark():
    assert "role_swap_best" in ALL_POLICIES
    lines = run_one(scenario_for_pair(load_scenario(TWO_FAILURE), (0, 5), (1200.0, 1500.0)),
                    "role_swap_best")
    final = [ln for ln in lines if ln["state"] not in ("INIT", "SUMMARY")][-1]
    held = {s["role"] for s in final["sats"] if s["status"] == "NOMINAL"}
    assert {"leader", "downlink"} <= held
