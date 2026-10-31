"""Replan seam contract (audit B4): sim.py calls replan(..., current_slots=...)
unconditionally, so benchmark policies must accept it and a TypeError raised
inside a replanner must propagate (no silent re-call that drops do-no-harm)."""

import inspect
from pathlib import Path

import pytest

import cubesat.sim as sim_module
from cubesat.benchmark_policies import even_split_replan, hungarian_keepout_replan
from cubesat.scenario import Failure, FailureMode, load_scenario
from tests.test_benchmark import _replan_inputs

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("fn", [even_split_replan, hungarian_keepout_replan])
def test_benchmark_policies_accept_current_slots(fn):
    assert "current_slots" in inspect.signature(fn).parameters
    scenario = load_scenario(ROOT / "data" / "scenarios" / "two_failure.json")
    out = fn(**_replan_inputs(scenario), current_slots=None)
    assert len(out) == 6


def test_replan_typeerror_propagates(monkeypatch):
    scenario = load_scenario(ROOT / "data" / "scenarios" / "two_failure.json")
    scenario = scenario.model_copy(
        update={
            "failures": [
                Failure(t=1200.0, sat_id=0, mode=FailureMode.DEAD),
                Failure(t=1500.0, sat_id=1, mode=FailureMode.DEAD),
            ],
        }
    )

    real, calls = sim_module.replan, []

    def boom(*args, **kwargs):
        # first call fails; a silent re-call (the old fallback) would succeed
        calls.append(1)
        if len(calls) == 1:
            raise TypeError("bug inside replanner")
        return real(*args, **kwargs)

    monkeypatch.setattr(sim_module, "replan", boom)
    with pytest.raises(TypeError, match="bug inside replanner"):
        sim_module.run_scenario(scenario)
