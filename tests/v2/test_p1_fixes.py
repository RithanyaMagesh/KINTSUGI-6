"""Review fixes for Phase 1 (each test was red before its fix): inject/replay contract, draw
order, schema bounds, re-entry guard, snapshot format, inject-after-end, duplicate events."""

import copy
import json
import math
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from cubesat import sim_v2, truth
from cubesat.scenario import Failure, Scenario
from cubesat.sim_v2 import EngineV2

ROOT = Path(__file__).resolve().parents[2]
NOMINAL = json.loads((ROOT / "data" / "scenarios" / "nominal.json").read_text())
SMALL_SENSOR = {"fov_half_angle_deg": 1.5, "grid_step_km": 5.0, "grid_extent_km": 5.0}


def _scn(**kw) -> Scenario:
    return Scenario.model_validate({**NOMINAL, "engine": "v2", "sensor": SMALL_SENSOR, **kw})


def _bytes(lines) -> bytes:
    return json.dumps(lines, sort_keys=True).encode()


# --- A1: live inject == replay of the recorded (resolved) injections -------------------------
@pytest.mark.parametrize(
    "failure, onset_expected",
    [
        (Failure(t=10.0, sat_id=1, mode="EPS_DEGRADE", degrade_s=50.0), None),  # fully past
        (Failure(t=200.0, sat_id=1, mode="EPS_DEGRADE", degrade_s=150.0), 120.0),  # onset past
        (Failure(t=200.0, sat_id=1, mode="EPS_DEGRADE", degrade_s=30.0), 170.0),  # future
        (Failure(t=200.0, sat_id=1, mode="DEAD"), None),
    ],
)
def test_live_inject_equals_replay_of_recorded_injections(failure, onset_expected):
    s = _scn(duration_s=300.0)
    eng = EngineV2(s)
    head = [eng.header()] + [eng.step() for _ in range(60)]  # now = 120 s
    eng.inject(failure)
    live = head + list(eng.run())
    replay = list(EngineV2(s, eng.injections).run())
    assert _bytes(live) == _bytes(replay)
    onsets = [
        line["t"]
        for line in live
        if any(e["type"] == "DEGRADE_START" for e in line.get("events", []))
    ]
    assert onsets == ([] if onset_expected is None else [onset_expected])
    assert any(e["type"] == "FAILURE_DETECTED" for line in live for e in line.get("events", []))


# --- A2: every draw-order row is drawn unconditionally ---------------------------------------
def test_all_seven_rows_drawn_per_sat_per_tick():
    rng, ref = sim_v2.make_rng(_scn(seed=3)), sim_v2.make_rng(_scn(seed=3))
    out = sim_v2.draw_tick(rng, 3)
    for i in range(3):
        assert ref.random() == out["heartbeat_u"][i]
        assert np.array_equal(ref.standard_normal(6), out["noise"][i])
        assert ref.random() == out["seu_u"][i]
        assert ref.uniform(30.0, 120.0) == out["seu_duration"][i]
        assert ref.random() == out["impact_u"][i]
        assert ref.random() == out["impact_component"][i]
        assert ref.uniform(0.2, 0.6) == out["impact_fraction"][i]
    assert rng.bit_generator.state == ref.bit_generator.state


def _manual_tick_heartbeats(rng, n):
    """The documented per-sat call sequence (rows 1-7), written out independently of draw_tick."""
    hb = []
    for _ in range(n):
        hb.append(rng.random())
        rng.standard_normal(6)
        rng.random()
        rng.uniform(30.0, 120.0)
        rng.random()
        rng.random()
        rng.uniform(0.2, 0.6)
    return hb


def test_tick1_heartbeat_independent_of_a_hit_at_tick0():
    """Rows 4, 6, 7 are drawn whether or not the hit happens, so a tick-0 SEU/impact hit cannot
    move tick 1's draws. Seeds are chosen so both 'hit' and 'no hit' (rate 0.5) occur."""
    seen = set()
    for seed in range(40):
        rng = sim_v2.make_rng(_scn(seed=seed))
        t0 = sim_v2.draw_tick(rng, 2)
        t1 = sim_v2.draw_tick(rng, 2)
        ref = sim_v2.make_rng(_scn(seed=seed))
        _manual_tick_heartbeats(ref, 2)  # tick 0, consumed identically for hit and no hit
        assert list(t1["heartbeat_u"]) == _manual_tick_heartbeats(ref, 2)
        assert t0["seu_duration"].shape == (2,)
        seen.add(bool(t0["seu_u"][0] < 0.5))
    assert seen == {True, False}


# --- A3: schema rejects values that produce NaN/inf logs --------------------------------------
@pytest.mark.parametrize(
    "path, value",
    [
        (("chief", "raan_deg"), float("nan")),
        (("chief", "raan_deg"), float("inf")),
        (("chief", "raan_deg"), 1e12),
        (("chief", "inclination_deg"), float("nan")),
        (("chief", "inclination_deg"), 181.0),
        (("chief", "epoch_utc"), "garbage"),
        (("truth", "mass_kg"), 1e-300),
        (("truth", "mass_kg"), float("nan")),
        (("truth", "area_active_m2"), 1e300),
        (("truth", "area_dead_m2"), float("inf")),
        (("truth", "cd"), float("nan")),
        (("truth", "cd"), 1e9),
        (("truth", "density_factor"), float("nan")),
        (("truth", "density_factor"), 1e300),
    ],
)
def test_schema_rejects_non_finite_or_absurd_values(path, value):
    payload = copy.deepcopy(NOMINAL)
    payload.setdefault(path[0], {})
    payload[path[0]][path[1]] = value
    with pytest.raises(ValidationError):
        Scenario.model_validate(payload)


def test_schema_accepts_documented_ranges():
    payload = copy.deepcopy(NOMINAL)
    payload["chief"].update(
        raan_deg=-360.0, inclination_deg=180.0, epoch_utc="2026-03-20T12:00:00+00:00"
    )
    payload["truth"] = {"density_factor": 2000.0, "mass_kg": 1e-3}
    Scenario.model_validate(payload)


# --- A4: re-entry guard -----------------------------------------------------------------------
def test_density_never_extrapolates_below_the_150km_row():
    top = truth.density(150e3)
    for h in (149e3, 100e3, 0.0, -1e6):
        assert truth.density(h) == top
    assert np.all(np.isfinite(truth.density(np.array([-1e7, 0.0, 120e3]))))


def _reentry_events(lines):
    return [e for line in lines for e in line.get("events", []) if e["type"] == "REENTRY"]


def test_dead_sat_at_161km_reenters_once_and_stays_finite():
    s = _scn(
        chief={"altitude_km": 161.0},
        dt_s=10.0,
        duration_s=30000.0,
        a_max_mps2=1e-12,
        failures=[{"t": 0.0, "sat_id": 0, "mode": "DEAD"}],
    )
    lines = list(EngineV2(s).run())
    ev = _reentry_events(lines)
    assert [e["payload"]["sat_id"] for e in ev] == [0]
    assert ev[0]["payload"]["altitude_m"] < 100e3
    ticks = [x for x in lines if "sats" in x]
    assert all(np.isfinite(np.array([c for x in ticks for c in x["sats"][0]["r"]])))
    t_re = next(x["t"] for x in ticks if x["sats"][0]["status"] == "REENTERED")
    frozen = [x["sats"][0]["r"] for x in ticks if x["t"] >= t_re]
    assert all(r == frozen[0] for r in frozen)
    assert max(abs(c) for c in frozen[0]) < 1e7  # nowhere near the old 1.7e12 km blow-up


def test_extreme_density_factor_stays_finite_one_reentry_per_sat():
    s = _scn(
        chief={"altitude_km": 300.0},
        dt_s=10.0,
        duration_s=20000.0,
        a_max_mps2=1e-12,
        truth={"density_factor": 2000.0},
        failures=[{"t": 0.0, "sat_id": i, "mode": "DEAD"} for i in range(6)],
    )
    lines = list(EngineV2(s).run())
    ids = [e["payload"]["sat_id"] for e in _reentry_events(lines)]
    assert sorted(ids) == list(range(6))  # every sat re-enters, exactly once
    for x in lines:
        for sat in x.get("sats", []):
            assert all(math.isfinite(c) for c in sat["r"] + sat["v"])


# --- A8 / B7 / B6 -----------------------------------------------------------------------------
def test_no_duplicate_failure_detected_for_repeated_thruster_out():
    s = _scn(
        duration_s=40.0,
        failures=[{"t": 10.0, "sat_id": 2, "mode": "THRUSTER_OUT"}] * 2,
    )
    lines = list(EngineV2(s).run())
    detected = [e for x in lines for e in x.get("events", []) if e["type"] == "FAILURE_DETECTED"]
    assert [e["payload"]["sat_id"] for e in detected] == [2]


def test_inject_after_run_finished_raises():
    eng = EngineV2(_scn(duration_s=10.0))
    list(eng.run())
    with pytest.raises(RuntimeError, match="finished"):
        eng.inject(Failure(t=0.0, sat_id=0, mode="DEAD"))


def test_snapshot_is_json_data_not_pickle():
    eng = EngineV2(_scn(duration_s=40.0))
    for _ in range(5):
        eng.step()
    blob = eng.snapshot()
    doc = json.loads(blob)  # plain JSON
    assert {"fingerprint", "state"} <= set(doc)
    assert b"pickle" not in blob and not blob.startswith(b"\x80")


def test_restore_rejects_a_different_scenario_and_garbage():
    a = EngineV2(_scn(duration_s=40.0))
    a.step()
    blob = a.snapshot()
    with pytest.raises(ValueError, match="fingerprint"):
        EngineV2(_scn(duration_s=40.0, seed=99)).restore(blob)
    with pytest.raises(ValueError, match="fingerprint"):
        EngineV2(_scn(duration_s=60.0)).restore(blob)
    with pytest.raises(ValueError):
        EngineV2(_scn(duration_s=40.0)).restore(b"not a snapshot")
    EngineV2(_scn(duration_s=40.0)).restore(blob)  # same scenario restores
