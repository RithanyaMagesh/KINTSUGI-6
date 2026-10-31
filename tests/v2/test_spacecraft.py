"""Spacecraft resource model (Phase 2, fuel-first): propulsion, mass, failure modes as resource
damage. Defaults are illustrative: 3U, 4.0 kg wet, 0.2 kg propellant, Isp 40 s, F_max 0.04 N."""

import json
import math
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from cubesat.scenario import Scenario
from cubesat.spacecraft import G0, SatState, thrust_limited

DT = 2.0
BIG = np.array([1.0, 0.0, 0.0])  # a command far above any cap, m/s^2


def _sat(**kw) -> SatState:
    return SatState(**kw)


def test_accel_saturates_at_k_fmax_over_m():
    a, _ = thrust_limited(_sat(), BIG, DT)
    assert np.linalg.norm(a) == pytest.approx(0.04 / 4.0, rel=1e-12)  # 0.01 m/s^2
    assert a[0] > 0 and a[1] == 0 and a[2] == 0  # direction kept
    a, _ = thrust_limited(_sat(k=0.5), BIG, DT)
    assert np.linalg.norm(a) == pytest.approx(0.005, rel=1e-12)


def test_command_below_cap_passes_through_unchanged():
    cmd = np.array([0.001, -0.002, 0.003])
    a, dm = thrust_limited(_sat(), cmd, DT)
    assert np.array_equal(a, cmd)  # not even an ulp of drift (keeps Phase-1 bytes)
    assert dm == pytest.approx(np.linalg.norm(cmd) * 4.0 * DT / (40.0 * G0), rel=1e-12)


def test_mass_flow_isp():
    sat = _sat()
    a, dm = thrust_limited(sat, BIG, DT)
    assert dm == pytest.approx(0.04 * DT / (40.0 * G0), rel=1e-12)  # |F| dt / (Isp g0)
    assert sat.m_prop_kg == pytest.approx(0.2 - dm, rel=1e-12)
    assert sat.m_kg == pytest.approx(4.0 - dm, rel=1e-12)


def test_delta_v_budget_20p1():
    sat = _sat()
    got = 40.0 * G0 * math.log(4.0 / 3.8)
    print(f"tank delta-v = {sat.fuel_mps_left:.4f} m/s (formula {got:.4f})")
    assert sat.fuel_mps_left == pytest.approx(got, abs=1e-12)
    assert abs(sat.fuel_mps_left - 20.12) < 0.05


@pytest.mark.parametrize("kw", [{"m_prop_kg": 0.0}, {"k": 0.0}])
def test_zero_prop_means_fuel_depleted_and_zero_thrust(kw):
    """Empty tank (FUEL_DEPLETED) or k = 0: zero thrust, no mass change; an empty tank sets k=0."""
    sat = _sat(**kw)
    assert sat.depleted is ("m_prop_kg" in kw)
    a, dm = thrust_limited(sat, BIG, DT)
    assert not a.any() and dm == 0.0 and sat.m_kg == 4.0 and sat.k == 0.0
    assert ("m_prop_kg" in kw) == (sat.fuel_mps_left == 0.0)


def test_propellant_never_negative_over_a_long_saturated_burn():
    sat = _sat()
    dv = 0.0
    for _ in range(5000):  # 10000 s of demand, tank lasts ~1960 s
        a, dm = thrust_limited(sat, BIG, DT)
        dv += np.linalg.norm(a) * DT
        assert sat.m_prop_kg >= 0.0 and dm >= 0.0
    assert sat.m_prop_kg == 0.0 and sat.depleted
    assert sat.m_kg == pytest.approx(3.8, abs=1e-12)  # dry mass
    # Sum of a dt equals the rocket-equation tank delta-v up to the start-of-step-mass
    # discretisation (measured 5.3e-4 m/s of 20.12 at dt = 2 s, relative 2.6e-5).
    assert dv == pytest.approx(40.0 * G0 * math.log(4.0 / 3.8), abs=2e-3)
    assert dv < 40.0 * G0 * math.log(4.0 / 3.8)


def test_burn_truncated_on_the_step_that_exhausts_the_tank():
    sat = _sat(m_prop_kg=1e-4)  # full step needs 0.04*2/(40 g0) = 2.04e-4 kg
    a, dm = thrust_limited(sat, BIG, DT)
    assert dm == 1e-4 and sat.m_prop_kg == 0.0  # exactly exhausted
    full = 0.04 / 4.0
    frac = 1e-4 / (0.04 * DT / (40.0 * G0))
    assert 0.0 < frac < 1.0
    assert np.linalg.norm(a) == pytest.approx(full * frac, rel=1e-12)  # clipped dv this step
    dv = np.linalg.norm(a) * DT
    assert dv == pytest.approx(40.0 * G0 * math.log(4.0 / (4.0 - 1e-4)), rel=1e-4)
    assert not thrust_limited(sat, BIG, DT)[0].any()  # and nothing afterwards


# --- scenario block and v1 rejection ---------------------------------------------------------
def _scn_dict(**kw):
    root = Path(__file__).resolve().parents[2]
    return {**json.loads((root / "data/scenarios/nominal.json").read_text()), **kw}


def test_spacecraft_block_defaults_and_bounds():
    s = Scenario.model_validate(_scn_dict(engine="v2"))
    assert (s.spacecraft.m_prop_kg, s.spacecraft.isp_s, s.spacecraft.f_max_n) == (0.2, 40.0, 0.04)
    assert s.truth.mass_kg == 4.0  # wet mass lives in truth
    for bad in ({"m_prop_kg": -0.1}, {"isp_s": 0}, {"f_max_n": 0}, {"m_prop_kg": float("nan")}):
        with pytest.raises(ValidationError):
            Scenario.model_validate(_scn_dict(engine="v2", spacecraft=bad))
    with pytest.raises(ValidationError, match="wet mass"):  # propellant must fit in the wet mass
        Scenario.model_validate(_scn_dict(engine="v2", spacecraft={"m_prop_kg": 4.0}))
