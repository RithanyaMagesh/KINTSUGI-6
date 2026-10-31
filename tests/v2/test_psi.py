"""Phase 5b: cross-track phase psi (docs/PHYSICS_V2.md "Cross-track phase psi")."""

from __future__ import annotations

import math

import numpy as np
import pytest

from cubesat import sim
from cubesat.allocate_v2 import candidate_slots
from cubesat.hcw import mean_motion, propagate, slot_initial_state
from cubesat.scenario import Formation, load_scenario

N = mean_motion(500e3)
PERIOD = 2.0 * math.pi / N
PSIS = (0, 30, 45, 60, 90)


def test_psi0_equals_v1_slots():
    amp, phase0, k = 8000.0, 0.3, 6
    got = candidate_slots(amp, phase0, 0.0, k, N)
    assert len(got) == k
    for j, s in enumerate(got):
        want = slot_initial_state(amp, amp, phase0 + 2.0 * math.pi * j / k, N)
        assert np.array_equal(s, want)


def test_psi0_equals_sim_build_slots_for_v1_scenario():
    sc = load_scenario("data/scenarios/two_failure.json")
    amp = sc.formation.radial_amp_km * 1000.0
    off = math.radians(sc.formation.phase_offset_deg)
    got = candidate_slots(amp, off, 0.0, sc.formation.n_slots, N)
    for a, b in zip(got, sim.build_slots(sc, N), strict=True):
        assert np.array_equal(a, b)


@pytest.mark.parametrize("psi", PSIS)
def test_slots_passive_and_closed(psi):
    for s in candidate_slots(8000.0, 0.0, psi, 6, N):
        end = propagate(s, PERIOD, N)
        assert np.abs(end[:3] - s[:3]).max() <= 1e-6
        assert np.abs(end[3:] - s[3:]).max() <= 1e-9  # m/s


@pytest.mark.parametrize("psi", PSIS)
def test_slots_distinct_shape_deterministic(psi):
    a = candidate_slots(8000.0, 0.1, psi, 6, N)
    b = candidate_slots(8000.0, 0.1, psi, 6, N)
    assert all(np.array_equal(x, y) for x, y in zip(a, b, strict=True))
    assert all(s.shape == (6,) for s in a)
    pos = np.array([s[:3] for s in a])
    d = np.linalg.norm(pos[:, None] - pos[None], axis=2) + np.eye(6) * 1e9
    assert d.min() > 0.0


def test_psi_shifts_only_cross_track_phase():
    base = candidate_slots(8000.0, 0.0, 0.0, 6, N)
    for psi in (30.0, 90.0):
        for j, s in enumerate(candidate_slots(8000.0, 0.0, psi, 6, N)):
            th = 2.0 * math.pi * j / 6
            ps = math.radians(psi)
            assert np.array_equal(s[[0, 1, 3, 4]], base[j][[0, 1, 3, 4]])
            assert s[2] == pytest.approx(8000.0 * math.cos(th + ps), abs=1e-9)
            assert s[5] == pytest.approx(-8000.0 * N * math.sin(th + ps), abs=1e-12)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_psi_rejected(bad):
    with pytest.raises(ValueError):
        candidate_slots(8000.0, 0.0, bad, 6, N)


def test_formation_field_default_and_guard():
    assert Formation(n_slots=6, radial_amp_km=2.0).cross_track_phase_deg == 0.0
    f = Formation(n_slots=6, radial_amp_km=2.0, cross_track_phase_deg=30)
    assert f.cross_track_phase_deg == 30.0
    with pytest.raises(ValueError):
        Formation(n_slots=6, radial_amp_km=2.0, cross_track_phase_deg=float("nan"))
