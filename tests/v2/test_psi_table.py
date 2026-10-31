"""Phase 5b: separation metric, coverage and the committed trade table."""

from __future__ import annotations

import math

import numpy as np
import pytest

from cubesat.allocate_v2 import candidate_slots
from cubesat.hcw import mean_motion
from cubesat.psi_table import (
    imager_seat_roles,
    mean_coverage,
    pair_min_distance,
    worst_separation,
)

N = mean_motion(500e3)
A = 8000.0
BRIEF = {  # docs/superpowers/specs/2026-10-31-physics-v2-brief.md section 4 Phase 5 item 3
    0: (0.371, 11.8), 30: (0.364, 2929.0), 45: (0.355, 4330.0), 60: (0.345, 5657.0),
    90: (0.326, 8000.0),
}


def _sep(psi, **kw):
    kw.setdefault("samples_per_orbit", 720)
    return worst_separation(candidate_slots(A, 0.0, psi, 6, N), N, **kw)


def test_psi0_worst_separation_is_tiny():
    assert _sep(0) < 50.0


def test_psi90_matches_analytic_bound():
    bound = 2.0 * math.sin(math.radians(60.0) / 2.0) * A  # dphi = 360/6, min(A, B) = A
    assert _sep(90) == pytest.approx(bound, rel=0.01)


def test_psi90_is_bounded_below_by_chord_for_other_amplitude():
    sl = candidate_slots(2000.0, 0.0, 90.0, 6, N)
    got = worst_separation(sl, N, samples_per_orbit=720)
    assert got >= 2.0 * math.sin(math.radians(30.0)) * 2000.0 * (1 - 1e-6)


def test_separation_restricted_to_s0_misses_the_drift_hazard():
    # slots j and 6-j meet in the (x, z) plane; they only collide once one is
    # displaced along track, so s = 0 hides it.
    assert _sep(0, s_max=0.0) > 1000.0
    assert _sep(0) < 1.0


def test_s_grid_quantisation_converges_to_exact():
    exact = _sep(0)
    coarse = _sep(0, s_step=24.0)
    fine = _sep(0, s_step=3.0)
    assert exact <= fine <= 1.5 + 1e-9 and fine <= coarse <= 12.0 + 1e-9


def test_pair_min_distance_matches_brute_force_over_t_and_s():
    sl = candidate_slots(A, 0.0, 30.0, 6, N)
    period = 2.0 * math.pi / N
    t = np.linspace(0.0, period, 241)
    got = pair_min_distance(sl[0], sl[2], N, t, s_max=40000.0)
    from cubesat.hcw import propagate

    a, b = propagate(sl[0], t, N)[:, :3], propagate(sl[2], t, N)[:, :3]
    best = 1e18
    for s in np.linspace(-40000.0, 40000.0, 1601):
        d = a - (b + np.array([0.0, s, 0.0]))
        best = min(best, float(np.linalg.norm(d, axis=1).min()))
    assert got <= best + 1e-9 and got == pytest.approx(best, abs=60.0)


def test_time_grid_halving_converges():
    for psi in (30, 45):
        assert abs(_sep(psi, samples_per_orbit=1441) - _sep(psi, samples_per_orbit=2881)) < 0.5


def test_roles_put_four_imagers_on_even_seats():
    assert imager_seat_roles(6, 4) == ["imager", "leader", "imager", "downlink", "imager", "imager"]
    assert imager_seat_roles(6, 4, "scenario") == [
        "imager", "imager", "imager", "imager", "leader", "downlink"]


@pytest.fixture(scope="module")
def cov8():
    return {
        lay: {
            psi: mean_coverage(
                candidate_slots(A, 0.0, psi, 6, N), N, fov_half_deg=1.5, layout=lay)
            for psi in (0, 30, 45, 60, 90)
        }
        for lay in ("even", "scenario")
    }


@pytest.mark.parametrize("lay", ["even", "scenario"])
def test_coverage_monotone_non_increasing_in_psi(cov8, lay):
    vals = list(cov8[lay].values())
    assert all(b <= a + 1e-12 for a, b in zip(vals, vals[1:], strict=False)), vals


@pytest.mark.parametrize("psi", [0, 30, 45, 60, 90])
def test_coverage_matches_brief_with_scenario_role_order(cov8, psi):
    # the brief's coverage column is the scenario role order (imagers on seats 0-3)
    assert cov8["scenario"][psi] == pytest.approx(BRIEF[psi][0], abs=0.003)


def test_even_layout_is_not_the_briefs_layout(cov8):
    # recorded disagreement: seats 0,2,4,5 cover 0.013-0.029 more than seats 0-3
    gaps = [cov8["even"][p] - cov8["scenario"][p] for p in (0, 30, 45, 60, 90)]
    assert all(0.01 < g < 0.035 for g in gaps), gaps


@pytest.mark.parametrize("psi", [30, 45, 60, 90])
def test_separation_matches_brief_for_psi_ge_30(psi):
    assert _sep(psi, samples_per_orbit=2881) == pytest.approx(BRIEF[psi][1], rel=0.01)
