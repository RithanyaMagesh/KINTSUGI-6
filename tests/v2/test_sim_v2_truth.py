"""Task 1.5: EngineV2 stepper-native truth loop (no resources yet)."""

import json
import math
import threading
from pathlib import Path

import numpy as np
import pytest

from cubesat import cw_curve, cw_truth, hcw, truth
from cubesat.scenario import Failure, Scenario
from cubesat.sim import RunCancelled, build_slots, run_scenario
from cubesat.sim_v2 import EngineV2, run_scenario_v2

ROOT = Path(__file__).resolve().parents[2]
PERIOD_500KM = 2.0 * math.pi * math.sqrt((truth.RE + 500e3) ** 3 / truth.MU)  # 5677.0 s
CW_VS_KEPLER_1KM_M = 3.101  # GATES.md G1 row (tests/test_hcw.py, cubesat/cw_curve.py)


def _scn(**kw) -> Scenario:
    """Small v2 scenario: 6 sats, tiny coverage grid (coverage is irrelevant here)."""
    base = json.loads((ROOT / "data" / "scenarios" / "nominal.json").read_text())
    base.update(
        engine="v2", sensor={"fov_half_angle_deg": 1.5, "grid_step_km": 5.0, "grid_extent_km": 5.0}
    )
    base.update(kw)
    return Scenario.model_validate(base)


def test_v2_no_drag_1km_matches_cw_within_3p1_m_1orbit():
    """Fast version of the 3-orbit test below (same scenario, 1 orbit)."""
    s, start = cw_truth.g1_case(1, j2=False, drag=False)
    d = cw_truth.max_diff_vs_cw(s, start)
    print(f"G1 1 km state, J2 off, drag off, 1 orbit: max |v2 - CW| = {d:.4f} m")
    assert d <= CW_VS_KEPLER_1KM_M * 1.10


@pytest.mark.slow
def test_v2_no_drag_1km_matches_cw_within_3p1_m():
    s, start = cw_truth.g1_case(3, j2=False, drag=False)
    d = cw_truth.max_diff_vs_cw(s, start)
    print(f"G1 1 km state, J2 off, drag off, 3 orbits: max |v2 - CW| = {d:.4f} m")
    assert d <= CW_VS_KEPLER_1KM_M * 1.10


def test_v2_j2_on_difference_is_reported():
    s, start = cw_truth.g1_case(1, j2=True, drag=False)
    d = cw_truth.max_diff_vs_cw(s, start)
    print(f"G1 1 km state, J2 on, drag off, 1 orbit: max |v2 - CW| = {d:.4f} m")
    assert math.isfinite(d) and d > CW_VS_KEPLER_1KM_M


def test_slot_formation_cw_error_matches_independent_kepler_reference():
    """The planar 1 km ring slots have a larger CW-vs-Kepler error than the G1 state (it is the
    state, not the engine): v2 equals the independent two-body RK45 reference of cw_curve."""
    d = cw_truth.max_diff_vs_cw(cw_truth.passive_scenario(1.0, PERIOD_500KM, j2=False, drag=False))
    t1 = cw_curve.T_GRID[cw_curve.T_GRID <= cw_curve.PERIOD]
    chief_y = cw_curve.chief_states(t1)
    ref = max(
        cw_curve.cw_vs_kepler_errors(
            hcw.slot_initial_state(1000.0, 1000.0, 2 * math.pi * p / 6, cw_curve.N),
            t_grid=t1,
            n=cw_curve.N,
            chief_y=chief_y,
        ).max()
        for p in range(6)
    )
    print(f"ring slots 1 km, 1 orbit: engine {d:.3f} m vs cw_curve RK45 reference {ref:.3f} m")
    assert abs(d - ref) / ref < 0.02


def test_cached_phi_slot_reference_matches_direct_stm():
    s = _scn(duration_s=PERIOD_500KM)
    eng = EngineV2(s)
    slots = np.array(build_slots(s, eng.n))
    for _ in range(eng.n_ticks - 1):
        eng.step()
    direct = np.array([hcw.propagate(sl, eng.k * eng.dt, eng.n) for sl in slots])
    err = np.max(np.abs(eng.refs[:, :3] - direct[:, :3]))
    print(f"cached-Phi(dt) slot reference vs direct Phi(t) after 1 orbit: {err:.3e} m")
    assert err < 1e-6


def _fail_scn(duration=600.0) -> Scenario:
    return _scn(
        duration_s=duration,
        failures=[
            {"t": 100.0, "sat_id": 0, "mode": "DEAD"},
            {"t": 200.0, "sat_id": 3, "mode": "THRUSTER_OUT"},
        ],
    )


def _bytes(lines) -> bytes:
    return json.dumps(lines, sort_keys=True).encode()


def test_v2_log_schema_same_keys():
    s = _fail_scn()
    v1 = run_scenario(s.model_copy(update={"engine": "v1"}))
    v2 = run_scenario_v2(s)
    assert [x["state"] for x in v1[:1]] == [x["state"] for x in v2[:1]] == ["INIT"]
    assert v2[-1]["state"] == "SUMMARY"
    for key_set in (lambda x: set(x), lambda x: set(x["sats"][0]) if "sats" in x else set()):
        k1 = set().union(*(key_set(x) for x in v1 if x["state"] not in ("INIT", "SUMMARY")))
        k2 = set().union(*(key_set(x) for x in v2 if x["state"] not in ("INIT", "SUMMARY")))
        assert k1 <= k2
    assert set(v1[0]) <= set(v2[0]) and set(v1[-1]) <= set(v2[-1])
    assert any("event" in x for x in v2)


def test_v2_byte_identical_twice():
    s = _fail_scn()
    assert _bytes(run_scenario_v2(s)) == _bytes(run_scenario_v2(s))


def test_replay_with_injections_is_identical():
    s = _fail_scn(300.0)
    f = Failure(t=140.0, sat_id=1, mode="DEAD")
    eng = EngineV2(s)
    head = [eng.header()] + [eng.step() for _ in range(70)]  # 70 ticks -> now t = 140
    eng.inject(f)
    tail = list(eng.run())  # run() resumes at k = 70 (no second header)
    fresh = list(EngineV2(s, [f]).run())
    assert _bytes(head + tail) == _bytes(fresh)
    assert eng.injections == [f]


def test_inject_in_the_past_applies_at_current_tick():
    s = _fail_scn(300.0)
    eng = EngineV2(s)
    for _ in range(50):
        eng.step()
    eng.inject(Failure(t=0.0, sat_id=2, mode="DEAD"))
    assert eng.injections[0].t == 100.0  # clamped to the current tick so replay is exact
    line = eng.step()
    assert line["sats"][2]["status"] == "DEAD"


def test_snapshot_restore_continues_identically():
    s = _fail_scn(300.0)
    a = EngineV2(s)
    for _ in range(60):
        a.step()
    blob = a.snapshot()
    rest_a = [a.step() for _ in range(60)]
    b = EngineV2(s)
    b.restore(blob)
    rest_b = [b.step() for _ in range(60)]
    assert _bytes(rest_a) == _bytes(rest_b)
    assert a.rng.bit_generator.state == b.rng.bit_generator.state


def test_cancel_event_stops_run():
    s = _fail_scn()
    ev = threading.Event()
    gen = EngineV2(s).run(ev)
    next(gen)
    next(gen)
    ev.set()
    with pytest.raises(RunCancelled):
        next(gen)
    ev2 = threading.Event()
    ev2.set()
    with pytest.raises(RunCancelled):
        run_scenario_v2(s, ev2)


def test_events_list_allows_multiple_per_tick():
    s = _scn(
        duration_s=40.0,
        failures=[
            {"t": 10.0, "sat_id": 0, "mode": "THRUSTER_OUT"},
            {"t": 10.0, "sat_id": 4, "mode": "THRUSTER_OUT"},
        ],
    )
    line = next(x for x in EngineV2(s).run() if x["t"] == 10.0)
    assert [e["payload"]["sat_id"] for e in line["events"]] == [0, 4]
    assert line["event"] == line["events"][0]


def test_run_scenario_dispatches_v2_and_inject_validates_sat():
    s = _scn(duration_s=20.0)
    assert run_scenario(s)[-1]["state"] == "SUMMARY"
    with pytest.raises(ValueError):
        EngineV2(s).inject(Failure(t=0.0, sat_id=9, mode="DEAD"))


def _max_velocity_inconsistency(j2: bool) -> float:
    """max |logged LVLH v - central-difference d(r_logged)/dt| over sats and one orbit (8 km)."""
    s = cw_truth.passive_scenario(8.0, PERIOD_500KM, j2=j2, drag=False)
    lines = [x for x in EngineV2(s).run() if "sats" in x]
    r = np.array([[sat["r"] for sat in x["sats"]] for x in lines])
    v = np.array([[sat["v"] for sat in x["sats"]] for x in lines])
    fd = (r[2:] - r[:-2]) / (2.0 * s.dt_s)
    return float(np.abs(v[1:-1] - fd).max())


def test_logged_lvlh_velocity_vs_position_derivative_with_j2():
    """Known limit (docs/PHYSICS_V2.md): the logged velocity uses omega = (0,0,|h|/r^2) per the
    brief; with J2 the chief frame is not exactly that rotation, so v != d(rho)/dt."""
    off, on = _max_velocity_inconsistency(False), _max_velocity_inconsistency(True)
    print(f"8 km, 1 orbit: max |v - d(rho)/dt| J2 off {off:.3e} m/s, J2 on {on:.3e} m/s")
    assert off < 1e-3
    assert off < on < 5e-2


@pytest.mark.slow
def test_drag_shifts_every_deputy_along_track_against_the_undragged_chief():
    """The 'drag on' CW-vs-truth metric is the formation sinking relative to the UNDRAGGED
    virtual chief: the same ~49-50 m along-track shift at 1 km and 8 km after 3 orbits."""
    shifts = {}
    for km in (1.0, 8.0):
        end = {}
        for drag in (False, True):
            s = cw_truth.passive_scenario(km, 3 * PERIOD_500KM, j2=False, drag=drag)
            *_, line = (x for x in EngineV2(s).run() if "sats" in x)
            end[drag] = np.array([sat["r"] for sat in line["sats"]])
        shifts[km] = (end[True] - end[False])[:, 1]  # along-track shift per sat
    print(
        f"drag-induced along-track shift after 3 orbits: 1 km {shifts[1.0].round(1)} m, "
        f"8 km {shifts[8.0].round(1)} m"
    )
    for dy in shifts.values():
        assert np.all((dy > 45.0) & (dy < 55.0))
