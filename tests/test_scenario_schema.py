from pathlib import Path

import pytest
from pydantic import ValidationError

from cubesat.scenario import MAX_SATS, Scenario, load_scenario

ROOT = Path(__file__).resolve().parents[1]
NOMINAL = ROOT / "data" / "scenarios" / "nominal.json"


def test_nominal_loads_with_6_sats():
    scenario = load_scenario(NOMINAL)
    assert scenario.n_sats == 6
    assert scenario.roles.count("leader") == 1
    assert scenario.failures == []


def test_rejects_bad_altitude():
    payload = load_scenario(NOMINAL).model_dump()
    payload["chief"]["altitude_km"] = 5.0
    with pytest.raises(ValidationError):
        Scenario.model_validate(payload)


def test_rejects_bad_failure_mode():
    payload = load_scenario(NOMINAL).model_dump()
    payload["failures"] = [{"t": 100.0, "sat_id": 0, "mode": "EXPLODED"}]
    with pytest.raises(ValidationError):
        Scenario.model_validate(payload)


def test_rejects_unknown_failure_sat():
    payload = load_scenario(NOMINAL).model_dump()
    payload["failures"] = [{"t": 100.0, "sat_id": 9, "mode": "DEAD"}]
    with pytest.raises(ValidationError):
        Scenario.model_validate(payload)


def test_rejects_nonpositive_dt():
    payload = load_scenario(NOMINAL).model_dump()
    payload["dt_s"] = 0.0
    with pytest.raises(ValidationError):
        Scenario.model_validate(payload)


def test_rejects_slot_role_mismatch():
    payload = load_scenario(NOMINAL).model_dump()
    payload["formation"]["n_slots"] = 5  # roles stays 6: would log phantom sats
    with pytest.raises(ValidationError):
        Scenario.model_validate(payload)


# --- resource bounds (audit, medium: uploaded scenario resource parameters
#     were unbounded -- grid blowup, sweep blowup, runaway tick counts) --------


def test_rejects_grid_point_blowup():
    """coverage.target_grid materializes (2*extent/step+1)^2 points per tick;
    only gt=0 bounds used to stand between an upload and unbounded memory."""
    payload = load_scenario(NOMINAL).model_dump()
    payload["sensor"]["grid_step_km"] = 0.001  # (2*30/0.001+1)^2 points
    with pytest.raises(ValidationError, match="point budget"):
        Scenario.model_validate(payload)


def test_grid_point_budget_boundary():
    """100x100 = 10000 points is exactly the budget (accepted); 101x101 is
    one point over (rejected). Extents chosen for exact binary floats."""
    payload = load_scenario(NOMINAL).model_dump()
    payload["sensor"]["grid_extent_km"] = 24.75  # int(round(2*24.75/0.5))+1 = 100
    payload["sensor"]["grid_step_km"] = 0.5
    Scenario.model_validate(payload)  # accepted at the budget
    payload["sensor"]["grid_extent_km"] = 25.0  # 101 per axis -> 10201
    with pytest.raises(ValidationError, match="point budget"):
        Scenario.model_validate(payload)


def test_rejects_oversized_sweeps():
    """amp_sweep x phase_sweep_deg multiply into the replan's candidate
    count; 64 entries each is the cap (~5x the committed 1x12)."""
    payload = load_scenario(NOMINAL).model_dump()
    payload["allocation"]["amp_sweep"] = [1.0] * 65
    with pytest.raises(ValidationError):
        Scenario.model_validate(payload)
    payload["allocation"]["amp_sweep"] = [1.0] * 64
    payload["allocation"]["phase_sweep_deg"] = [0.0] * 65
    with pytest.raises(ValidationError):
        Scenario.model_validate(payload)


def test_rejects_too_many_satellites():
    """roles/n_slots drive O(n^2) per-tick loops (min_sep, evasion scan)."""
    payload = load_scenario(NOMINAL).model_dump()
    payload["roles"] = ["imager"] * (MAX_SATS + 1)
    payload["formation"]["n_slots"] = MAX_SATS + 1
    with pytest.raises(ValidationError):
        Scenario.model_validate(payload)


def test_rejects_overlong_duration():
    payload = load_scenario(NOMINAL).model_dump()
    payload["duration_s"] = 86_401.0
    with pytest.raises(ValidationError):
        Scenario.model_validate(payload)


def test_rejects_unbounded_tick_count():
    """The run length is duration_s/dt_s ticks; dt_s alone has no useful
    lower bound, so the pair is capped (audit: duration_s=1e9 reached the
    server's compute timeout and left an orphan thread)."""
    payload = load_scenario(NOMINAL).model_dump()
    payload["duration_s"], payload["dt_s"] = 1000.0, 1e-6  # ~1e9 ticks
    with pytest.raises(ValidationError, match="tick budget"):
        Scenario.model_validate(payload)


def test_rejects_too_many_failures():
    payload = load_scenario(NOMINAL).model_dump()
    payload["failures"] = [
        {"t": 10.0 + i, "sat_id": i % 6, "mode": "DEAD"} for i in range(65)
    ]
    with pytest.raises(ValidationError):
        Scenario.model_validate(payload)
