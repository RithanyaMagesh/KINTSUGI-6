"""Engine-level behaviour pins (each test kills a mutant found by the Phase 1 review; the
mutant-to-test table is in docs/PHYSICS_V2.md "Mutation check")."""

import json
import math
from pathlib import Path

import numpy as np

from cubesat import hcw, rng_v2, truth
from cubesat.coverage import coverage_fraction, footprint_radius, target_grid
from cubesat.pd import PDController
from cubesat.scenario import Scenario
from cubesat.sim import build_slots
from cubesat.sim_v2 import EngineV2

ROOT = Path(__file__).resolve().parents[2]
NOMINAL = json.loads((ROOT / "data" / "scenarios" / "nominal.json").read_text())
SMALL_SENSOR = {"fov_half_angle_deg": 1.5, "grid_step_km": 5.0, "grid_extent_km": 5.0}
PERIOD = 2.0 * math.pi * math.sqrt((truth.RE + 500e3) ** 3 / truth.MU)


def _scn(small_sensor=True, **kw) -> Scenario:
    extra = {"sensor": SMALL_SENSOR} if small_sensor else {}
    return Scenario.model_validate({**NOMINAL, "engine": "v2", **extra, **kw})


def _sma(x) -> float:
    return -truth.MU / (2.0 * (x[3:] @ x[3:] / 2.0 - truth.MU / np.linalg.norm(x[:3])))


def _events(lines, kind):
    return [(x["t"], e) for x in lines for e in x.get("events", []) if e["type"] == kind]


def _failing_scn(duration=300.0) -> Scenario:
    return _scn(
        duration_s=duration,
        failures=[
            {"t": 100.0, "sat_id": 0, "mode": "DEAD"},
            {"t": 200.0, "sat_id": 3, "mode": "THRUSTER_OUT"},
        ],
    )


# --- drag area per status, drag on deputies only ---
def test_decay_dead_vs_active_vs_thruster_out_and_chief_has_no_drag():
    """M3 (dead area switch), M26 (THRUSTER_OUT uses the active area), M6 (chief gets drag)."""
    s = _scn(
        roles=["leader", "imager", "imager"],
        formation={"n_slots": 3, "radial_amp_km": 1.0, "phase_offset_deg": 0.0},
        duration_s=PERIOD,
        a_max_mps2=1e-12,
        truth={"j2_enabled": False},
        failures=[
            {"t": 0.0, "sat_id": 0, "mode": "DEAD"},
            {"t": 0.0, "sat_id": 1, "mode": "THRUSTER_OUT"},
        ],
    )
    eng = EngineV2(s)
    a0 = [_sma(row) for row in eng.X]
    for _ in range(round(PERIOD / eng.dt)):
        eng.step()
    d = [_sma(row) - a for row, a in zip(eng.X, a0, strict=True)]
    chief, dead, thr, active = d
    print(
        f"decay over 1 rev: chief {chief:.2e} dead {dead:.4f} thr_out {thr:.4f} active {active:.4f}"
    )
    assert abs(chief) < 0.01  # virtual chief: no drag, two-body energy conserved
    assert active < -1.0
    assert 3.3 < dead / active < 3.7  # area ratio 0.035/0.010
    assert 0.97 < thr / active < 1.03  # THRUSTER_OUT keeps the active area


# --- chief J2 ---
def test_chief_nodal_precession_matches_j2_secular_rate():
    """M20: the chief has J2. Secular RAAN rate = -1.5 n J2 (Re/a)^2 cos i."""
    s = _scn(dt_s=10.0, duration_s=6 * PERIOD, truth={"density_factor": 0.0})
    eng = EngineV2(s)

    def raan(row):
        h = np.cross(row[:3], row[3:])
        return math.atan2(h[0], -h[1])

    w0 = raan(eng.X[0])
    steps = round(6 * PERIOD / eng.dt)
    for _ in range(steps):
        eng.step()
    a = truth.RE + 500e3
    n = math.sqrt(truth.MU / a**3)
    rate = -1.5 * n * truth.J2 * (truth.RE / a) ** 2 * math.cos(math.radians(97.4))
    got, want = raan(eng.X[0]) - w0, rate * steps * eng.dt
    print(f"chief RAAN drift over 6 orbits: {got:.6e} rad vs secular {want:.6e} rad")
    assert abs(got - want) / abs(want) < 0.05


# --- PD thrust: direction, magnitude, dv accounting ---
def test_pd_thrust_direction_and_dv_used_after_one_step():
    """M9/M14 (DCM transpose/sign), M12 (dv_used += |u| dt): sat 0 starts displaced from its slot,
    so the saturated PD command pushes it back; compare with CW + the same zero-order-hold u."""
    s = _scn(
        formation={"n_slots": 2, "radial_amp_km": 1.0, "phase_offset_deg": 0.0},
        roles=["leader", "imager"],
        duration_s=10.0,
        truth={"j2_enabled": False, "density_factor": 0.0},
    )
    probe = EngineV2(s)
    slots = np.array(build_slots(s, probe.n))
    start = slots.copy()
    start[0, :3] += [-500.0, 300.0, -200.0]
    eng = EngineV2(s, initial_lvlh=start)
    eng.step()
    line = eng.step()
    pd = PDController(s.gains.wn, s.gains.zeta, s.a_max_mps2)
    u = pd.command(start[0, :3], start[0, 3:], slots[0, :3], slots[0, 3:])
    assert math.isclose(float(np.linalg.norm(u)), s.a_max_mps2)  # saturated
    assert u[0] > 0 and u[1] < 0 and u[2] > 0  # pushes back toward the slot
    want = hcw.propagate_controlled(start[0], u, eng.dt, eng.n)
    sat = line["sats"][0]
    assert np.allclose(sat["r"], want[:3], atol=1e-3)
    # 1e-4 m/s: thrust is held fixed in ECI over the step (the frame turns 2.2e-3 rad), CW holds it
    # in LVLH; a transposed/negated DCM would be off by ~1e-2 m/s
    assert np.allclose(sat["v"], want[3:], atol=1e-4)
    assert math.isclose(sat["dv_used"], s.a_max_mps2 * eng.dt, rel_tol=1e-12)


# --- randomness, detection, fades, status semantics ---
def test_engine_consumes_one_draw_tick_per_step():
    """M10: the engine draws rows 1-7 for every sat every tick (stream position is fixed)."""
    s = _scn(duration_s=40.0)
    eng, ref = EngineV2(s), rng_v2.make_rng(s)
    for _ in range(7):
        eng.step()
        rng_v2.draw_tick(ref, s.n_sats)
    assert eng.rng.bit_generator.state == ref.bit_generator.state


def test_dead_sat_declared_after_k_missed_heartbeats():
    """M11: K=3, dt=2: DEAD at t=100 is declared at t=104 (misses at 100, 102, 104)."""
    lines = list(EngineV2(_failing_scn()).run())
    detected = _events(lines, "FAILURE_DETECTED")
    t, e = detected[0]
    assert (t, e["payload"]["sat_id"], e["payload"]["t_fail"], e["payload"]["t_detect"]) == (
        104.0,
        0,
        100.0,
        104.0,
    )
    assert [x[1]["payload"].get("self_report") for x in detected] == [None, True]
    assert detected[1][0] == 200.0  # THRUSTER_OUT self-reports on the firing tick


def _sat(lines, i):
    return [(x["t"], x["sats"][i]) for x in lines if "sats" in x]


def test_eps_fade_starts_at_onset_and_sat_keeps_holding_its_seat():
    """M18 (DEGRADE_START at the onset), M28 (a DEGRADED sat is still PD-held)."""
    s = _scn(
        duration_s=300.0,
        failures=[{"t": 200.0, "sat_id": 2, "mode": "EPS_DEGRADE", "degrade_s": 100.0}],
    )
    lines = list(EngineV2(s).run())
    ((t_start, ev),) = _events(lines, "DEGRADE_START")
    assert t_start == 100.0 and ev["payload"] == {"sat_id": 2, "t_fail": 200.0, "degrade_s": 100.0}
    track = dict(_sat(lines, 2))
    assert track[98.0]["status"] == "NOMINAL"
    assert all(track[t]["status"] == "DEGRADED" for t in (100.0, 150.0, 198.0))
    assert track[200.0]["status"] == "DEAD"
    assert track[198.0]["dv_used"] > track[100.0]["dv_used"] > 0.0  # still thrusting in the fade
    assert track[250.0]["dv_used"] == track[200.0]["dv_used"]  # dead: no more thrust


def test_thruster_out_sat_does_not_thrust():
    """M27: after THRUSTER_OUT dv_used is frozen; before it the PD was working."""
    track = dict(_sat(list(EngineV2(_failing_scn()).run()), 3))
    assert track[198.0]["dv_used"] > track[100.0]["dv_used"] > 0.0
    after = [track[t]["dv_used"] for t in (202.0, 250.0, 300.0)]
    assert after == [track[200.0]["dv_used"]] * 3


def test_dead_imager_is_excluded_from_coverage():
    """M19: with nominal sensor, a DEAD imager no longer contributes footprint."""
    s = _scn(
        small_sensor=False,
        duration_s=10.0,
        failures=[{"t": 0.0, "sat_id": 1, "mode": "DEAD"}],
    )
    line = EngineV2(s).step()
    grid = target_grid(s.sensor.grid_step_km * 1e3, s.sensor.grid_extent_km * 1e3)
    r_f = footprint_radius(500e3, math.radians(s.sensor.fov_half_angle_deg))
    yz = {i: line["sats"][i]["r"][1:] for i in range(6)}
    alive = coverage_fraction([yz[i] for i in (2, 3, 4)], grid, r_f)
    with_dead = coverage_fraction([yz[i] for i in (1, 2, 3, 4)], grid, r_f)
    assert alive < with_dead  # the dead imager's footprint matters in this geometry
    assert line["coverage"] == alive


# --- snapshot completeness ---
def test_restore_recovers_every_state_field_and_reaches_summary():
    """M7 (`fired`), M8 (`cov` -> SUMMARY): restore mid-run, compare state and the whole tail."""
    s = _failing_scn()
    a = EngineV2(s)
    for _ in range(110):  # past both failures
        a.step()
    blob = a.snapshot()
    tail_a = list(a.run())
    b = EngineV2(s)
    b.restore(blob)
    assert (b.faults.fired, b.k, len(b.cov), b.faults.mission) == (2, 110, 110, "FAILURE_DETECTED")
    assert b.faults.status == ["DEAD", "NOMINAL", "NOMINAL", "THRUSTER_OUT", "NOMINAL", "NOMINAL"]
    tail_b = list(b.run())
    assert json.dumps(tail_a, sort_keys=True) == json.dumps(tail_b, sort_keys=True)
    assert tail_b[-1]["state"] == "SUMMARY"
    assert len(_events(tail_b, "FAILURE_DETECTED")) == 0  # nothing replayed after the restore
