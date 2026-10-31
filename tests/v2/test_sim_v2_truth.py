"""Task 1.5: EngineV2 stepper-native truth loop (no resources yet)."""

import json
import math
import threading
from pathlib import Path

import numpy as np
import pytest

from cubesat import cw_curve, hcw, truth
from cubesat.scenario import Failure, Formation, Scenario
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


def _passive(radial_km, orbits, *, j2, drag) -> Scenario:
    """No effective control (a_max 1e-12): the v1 path is then pure CW (hcw.propagate)."""
    return _scn(
        duration_s=orbits * PERIOD_500KM,
        a_max_mps2=1e-12,
        formation={"n_slots": 6, "radial_amp_km": radial_km, "phase_offset_deg": 0.0},
        truth={"j2_enabled": j2, "density_factor": 1.0 if drag else 0.0},
    )


def _max_diff_vs_cw(s: Scenario, start: np.ndarray | None = None) -> float:
    """Max |r_v2 - r_CW| over all sats and ticks; CW = hcw.propagate (the v1 passive path)."""
    eng = EngineV2(s, initial_lvlh=start)
    start = np.array(build_slots(s, eng.n)) if start is None else start
    worst = 0.0
    for _ in range(eng.n_ticks):
        t = eng.k * eng.dt
        line = eng.step()
        cw = start @ hcw.stm(t, eng.n).T
        r = np.array([sat["r"] for sat in line["sats"]])
        worst = max(worst, float(np.linalg.norm(r - cw[:, :3], axis=1).max()))
    return worst


def _g1_scenario(orbits, *, j2, drag) -> tuple[Scenario, np.ndarray]:
    """Two sats on the G1 evidence state (1 km radial, 500 m cross-track) and its negative."""
    g1 = cw_curve.state_1km_passive_ellipse()
    s = _passive(1.0, orbits, j2=j2, drag=drag).model_copy(
        update={
            "roles": ["leader", "imager"],
            "formation": Formation(n_slots=2, radial_amp_km=1.0, phase_offset_deg=0.0),
        }
    )
    return s, np.array([g1, -g1])


def test_v2_no_drag_1km_matches_cw_within_3p1_m_1orbit():
    """Fast version of the 3-orbit test below (same scenario, 1 orbit)."""
    s, start = _g1_scenario(1, j2=False, drag=False)
    d = _max_diff_vs_cw(s, start)
    print(f"G1 1 km state, J2 off, drag off, 1 orbit: max |v2 - CW| = {d:.4f} m")
    assert d <= CW_VS_KEPLER_1KM_M * 1.10


@pytest.mark.slow
def test_v2_no_drag_1km_matches_cw_within_3p1_m():
    s, start = _g1_scenario(3, j2=False, drag=False)
    d = _max_diff_vs_cw(s, start)
    print(f"G1 1 km state, J2 off, drag off, 3 orbits: max |v2 - CW| = {d:.4f} m")
    assert d <= CW_VS_KEPLER_1KM_M * 1.10


def test_v2_j2_on_difference_is_reported():
    s, start = _g1_scenario(1, j2=True, drag=False)
    d = _max_diff_vs_cw(s, start)
    print(f"G1 1 km state, J2 on, drag off, 1 orbit: max |v2 - CW| = {d:.4f} m")
    assert math.isfinite(d) and d > CW_VS_KEPLER_1KM_M * 0.0


def test_slot_formation_cw_error_matches_independent_kepler_reference():
    """The planar 1 km ring slots have a larger CW-vs-Kepler error than the G1 state (it is the
    state, not the engine): v2 equals the independent two-body RK45 reference of cw_curve."""
    s = _passive(1.0, 1, j2=False, drag=False)
    d = _max_diff_vs_cw(s)
    t1 = cw_curve.T_GRID[cw_curve.T_GRID <= cw_curve.PERIOD]
    ref = max(
        cw_curve.cw_vs_kepler_errors(
            hcw.slot_initial_state(1000.0, 1000.0, 2 * math.pi * p / 6, cw_curve.N),
            t_grid=t1,
            n=cw_curve.N,
            chief_y=cw_curve.chief_states(t1),
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
