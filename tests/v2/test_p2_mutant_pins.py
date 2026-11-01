"""Mutation pins for Phase 2 (each kills a mutant the review found alive): frozen ECI stuck
vector, status rank, k floor, fail_mode/t_fail on raise, failures on an empty tank."""

import json
from pathlib import Path

import numpy as np
import pytest

from cubesat import truth
from cubesat.scenario import Scenario
from cubesat.sim_v2 import EngineV2

ROOT = Path(__file__).resolve().parents[2]
NOMINAL = json.loads((ROOT / "data" / "scenarios" / "nominal.json").read_text())
SMALL_SENSOR = {"fov_half_angle_deg": 1.5, "grid_step_km": 5.0, "grid_extent_km": 5.0}


def _scn(**kw) -> Scenario:
    return Scenario.model_validate({**NOMINAL, "engine": "v2", "sensor": SMALL_SENSOR, **kw})


# --- C: stuck vector is a FIXED ECI vector along the sat's velocity at failure ----------------
def test_stuck_open_thrust_is_a_frozen_eci_vector_along_the_failure_velocity():
    """A trajectory check against an independent RK4 with a constant ECI acceleration: a stuck
    direction recomputed each step (M07) or applied in LVLH (M08) would diverge by km."""
    s = _scn(duration_s=300.0, truth={"j2_enabled": False, "density_factor": 0.0},
             failures=[{"t": 0.0, "sat_id": 1, "mode": "THRUSTER_STUCK_OPEN"}])
    eng = EngineV2(s)
    row = 2  # X row of sat 1 (row 0 is the chief)
    ref = eng.X[row].copy()
    u0 = ref[3:] / np.linalg.norm(ref[3:])  # velocity direction at failure
    for k in range(120):
        m = eng.faults.sats[1].m_kg  # mass at the start of the step
        a_vec = u0 * 0.04 / m

        def accel(r, v, a_vec=a_vec):
            return truth.accel_gravity(r) + a_vec

        ref = truth.rk4_step(ref, eng.dt, accel)
        eng.step()
        if k == 0:
            got = eng.faults.sats[1].stuck_vec
            assert np.arccos(np.clip(got @ u0, -1, 1)) < 1e-6  # along the failure velocity
    assert np.linalg.norm(eng.X[row, :3] - ref[:3]) < 1e-6
    v_now = eng.X[row, 3:] / np.linalg.norm(eng.X[row, 3:])
    assert np.arccos(v_now @ u0) > 0.2  # the LVLH frame turned 0.26 rad: the vector did not follow


# --- C: same-tick / sequential failure matrix (status rank, k, fail_mode, t_fail) -------------
P, T, S, A, R, D = ("PARTIAL_THRUST", "THRUSTER_OUT", "THRUSTER_STUCK_OPEN", "PAYLOAD_FAIL",
                    "RADIO_FAIL", "DEAD")
MATRIX = [
    # failures [(t, mode)], expected (status, k, fail_mode, t_fail)
    ([(10, P), (20, T)], ("THRUSTER_OUT", 0.0, T, 20.0)),
    ([(10, T), (20, P)], ("THRUSTER_OUT", 0.0, T, 10.0)),  # PARTIAL never raises k above 0
    ([(10, S), (20, A)], ("PAYLOAD_FAILED", 1.0, A, 20.0)),
    ([(10, A), (20, P)], ("PAYLOAD_FAILED", 0.5, A, 10.0)),  # lower rank keeps the label
    ([(10, A), (20, T)], ("THRUSTER_OUT", 0.0, T, 20.0)),
    ([(10, T), (20, A)], ("THRUSTER_OUT", 0.0, T, 10.0)),
    ([(10, R), (20, T)], ("RADIO_SILENT", 0.0, R, 10.0)),
    ([(10, T), (20, R)], ("RADIO_SILENT", 0.0, R, 20.0)),
    ([(10, R), (20, A)], ("RADIO_SILENT", 1.0, R, 10.0)),
    ([(10, D), (20, P)], ("DEAD", 0.0, D, 10.0)),  # nothing acts on a dead sat
    ([(10, D), (20, S)], ("DEAD", 0.0, D, 10.0)),
    ([(10, P), (10, T), (10, R)], ("RADIO_SILENT", 0.0, R, 10.0)),  # same tick, fixed order
    ([(10, R), (10, T), (10, P)], ("RADIO_SILENT", 0.0, R, 10.0)),
]


@pytest.mark.parametrize("fails, want", MATRIX)
def test_failure_matrix_status_rank_k_fail_mode_and_t_fail(fails, want):
    s = _scn(duration_s=60.0,
             failures=[{"t": float(t), "sat_id": 1, "mode": m} for t, m in fails])
    eng = EngineV2(s)
    for _ in range(16):  # past t = 30
        eng.step()
    f = eng.faults
    got = (f.status[1], f.sats[1].k, f.fail_mode[1], f.t_fail[1])
    assert got == want
    if any(m == D for _, m in fails):
        assert f.sats[1].stuck_vec is None and not f.sats[1].payload_ok
    if any(m == S for _, m in fails) and not any(m == D for _, m in fails):
        assert f.sats[1].stuck_vec is not None


@pytest.mark.parametrize("mode, want_status", [(P, "FUEL_DEPLETED"), (T, "FUEL_DEPLETED"),
                                               (A, "FUEL_DEPLETED"), (S, "FUEL_DEPLETED"),
                                               (R, "RADIO_SILENT")])
def test_failures_on_an_empty_tank(mode, want_status):
    """An empty sat keeps the FUEL_DEPLETED label (rank 4) against lower-rank damage; a stuck
    thruster on an empty tank produces no thrust and no mass change; radio loss still wins."""
    s = _scn(duration_s=60.0, spacecraft={"m_prop_kg": 0.0},
             failures=[{"t": 10.0, "sat_id": 1, "mode": mode}])
    eng = EngineV2(s)
    lines = [eng.step() for _ in range(16)]
    sat = lines[-1]["sats"][1]
    assert sat["status"] == want_status and sat["k"] == 0.0
    assert sat["dv_used"] == 0.0 and sat["fuel_kg"] == 0.0
    assert eng.faults.sats[1].m_kg == 4.0
