"""F3 (perf audit 2026-11-01): injecting one DEAD failure into live_24sat raised
RuntimeError("no feasible survivor formation in the sweep grid") -> HTTP 500.

Root cause: every sweep candidate is k = 23 evenly phase-spaced seats on the
SAME 8 km ellipse the dead satellite coasts on, so some seat is always within
pi/23 of the dead sat's phase -> at most 2*A*sin(pi/46)*sqrt(2) = 1546 m < the
2 km floor (measured best 1416 m). The survivors' current seats (24-spacing,
2953 m from the dead sat) are feasible but were never a candidate.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from conftest import TINY_SCENARIO, write_tiny_scenario
from fastapi.testclient import TestClient

from cubesat.allocate import InfeasibleFormation, replan
from cubesat.api import app
from cubesat.coverage import footprint_radius, target_grid
from cubesat.hcw import mean_motion, propagate
from cubesat.scenario import load_scenario
from cubesat.scenario_models import Failure, FailureMode
from cubesat.sim import build_slots, run_scenario

LIVE_24 = Path("data/scenarios/live_24sat.json")


def _replan_24(dead: int, t: float, *, current: bool = True):
    sc = load_scenario(LIVE_24)
    alt = sc.chief.altitude_km * 1000.0
    n = mean_motion(alt)
    grid = target_grid(sc.sensor.grid_step_km * 1000.0, sc.sensor.grid_extent_km * 1000.0)
    r_f = footprint_radius(alt, math.radians(sc.sensor.fov_half_angle_deg))
    slots = build_slots(sc, n)
    alive = [i for i in range(sc.n_sats) if i != dead]
    return replan(
        [propagate(slots[i], t, n) for i in alive],
        [sc.roles[i] for i in alive],
        [sc.allocation.dv_budget_mps] * len(alive),
        [propagate(slots[dead], t, n)],
        sc.roles,
        sc.allocation,
        sc.formation.radial_amp_km * 1000.0,
        r_f, grid, n, sc.a_max_mps2, t,
        current_slots=[slots[i] for i in alive] if current else None,
    )


def test_replan_24sat_one_dead_holds_current_seats():
    plan, pairs, _cost, method, max_transfer, _c = _replan_24(21, 4256.0)
    assert method == "do_no_harm_hold"
    assert pairs == [(i, i) for i in range(23)]
    assert max_transfer == 0.0
    assert plan.coverage > 0.0


def test_replan_24sat_without_current_slots_still_raises_typed():
    """No current layout to fall back on -> the typed, loud error (RuntimeError
    subclass, same message: pareto.py's string match keeps working)."""
    with pytest.raises(InfeasibleFormation, match="no feasible survivor formation"):
        _replan_24(23, 100.0, current=False)


@pytest.mark.slow
@pytest.mark.parametrize("frac", [0.25, 0.5, 0.75])
@pytest.mark.parametrize("sat", [21, 22, 23])  # SAT-22/23/24, the 9 audit attempts
def test_live_24sat_inject_cut_points_run(sat, frac):
    sc = load_scenario(LIVE_24)
    t = round(frac * sc.duration_s / sc.dt_s) * sc.dt_s
    lines = run_scenario(
        sc.model_copy(update={"failures": [Failure(t=t, sat_id=sat, mode=FailureMode.DEAD)]})
    )
    assert lines[-1]["state"] == "SUMMARY"
    events = [ln["event"] for ln in lines if ln.get("event")]
    assert [e["payload"]["method"] for e in events if e["type"] == "ASSIGNMENT"] == [
        "do_no_harm_hold"
    ]
    assert {"from": "RECONFIGURING", "to": "RECOVERED"} in [
        e["payload"] for e in events if e["type"] == "STATE"
    ]
    assert min(ln["min_sep"] for ln in lines if "min_sep" in ln) >= 2000.0


# -- API: infeasibility that can still legitimately happen is a loud 409 -------

client = TestClient(app)
# 2 sats, SAT-1 dies; the only sweep seat sits at phase 90 deg, 2449 m from the
# dead sat (separation fine) and 2449 m from the survivor at 180 deg: bang-bang
# 9.9 m/s against a 1 cm/s budget -> reachability-infeasible, a measured outcome
# (pareto.py), not a grid artefact, so it must stay an error -- a loud 409.
_STARVED = dict(TINY_SCENARIO, allocation={"phase_sweep_deg": [90.0], "dv_budget_mps": 0.01})


@pytest.fixture
def api_dirs(tmp_path, monkeypatch):
    import cubesat.api

    cubesat.api._state = None
    monkeypatch.setattr(cubesat.api, "scenarios_dir", lambda: tmp_path / "scenarios")
    monkeypatch.setattr(cubesat.api, "log_dir", lambda: tmp_path / "logs")
    (tmp_path / "logs").mkdir()
    yield tmp_path
    state = cubesat.api._state
    if state is not None and state.session._driver is not None:
        state.session._driver.cancel()
    cubesat.api._state = None


def test_api_start_infeasible_is_409(api_dirs):
    write_tiny_scenario(api_dirs / "scenarios", _STARVED)
    r = client.post("/simulation/start", json={"speed": 40.0})
    assert r.status_code == 409, r.text
    assert "no feasible survivor formation" in r.json()["detail"]
    assert client.get("/health").json()["mode"] == "stopped"


def test_api_inject_infeasible_is_409(api_dirs):
    write_tiny_scenario(api_dirs / "scenarios", dict(_STARVED, failures=[]))
    assert client.post("/simulation/start", json={"speed": 1.0}).status_code == 200
    r = client.post("/failure/inject", json={"sat_id": "SAT-1", "mode": "DEAD"})
    assert r.status_code == 409, r.text
    assert "no feasible survivor formation" in r.json()["detail"]
    assert client.get("/health").json()["mode"] == "live"  # the old run plays on
