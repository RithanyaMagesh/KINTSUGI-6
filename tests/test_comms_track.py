"""Track C slice 1: formation shapes, laser ISL model, leader-function auction (pure modules)."""

import math

import numpy as np
import pytest

from cubesat import decentral as D
from cubesat import formations as F
from cubesat import isl
from cubesat.hcw import mean_motion, slot_initial_state, stm

N = mean_motion(500e3)
A = 8000.0
TERM = isl.Terminal()
ALL = [True] * 6
NO_LEADER = [False] + [True] * 5


def _ring_links():
    pos = np.array([s[:3] for s in F.formation_slots("cartwheel", 6, A, N)])
    return isl.plan_topology(pos, ALL, TERM)


# ---------- formations ----------
def test_cartwheel_matches_v1_slots():
    for j, s in enumerate(F.formation_slots("cartwheel", 6, A, N)):
        np.testing.assert_allclose(s, slot_initial_state(A, A, 2 * math.pi * j / 6, N), atol=1e-9)


@pytest.mark.parametrize("shape", F.SHAPES)
def test_every_shape_is_drift_free_and_periodic(shape):
    phi = stm(2 * math.pi / N, N)
    for s in F.formation_slots(shape, 6, A, N):
        assert s[4] == pytest.approx(-2 * N * s[0], abs=1e-12)
        np.testing.assert_allclose(phi @ s, s, atol=1e-6 * A)


@pytest.mark.parametrize("shape", F.SHAPES)
def test_closed_form_matches_stm(shape):
    slots = F.formation_slots(shape, 4, A, N)
    p = F.positions_over_orbit(slots, N, samples=8)
    for k in range(8):
        phi = stm(2 * math.pi * k / 8 / N, N)
        for i, s in enumerate(slots):
            np.testing.assert_allclose(p[k, i], (phi @ s)[:3], atol=1e-6 * A)


def test_gco_constant_range_and_pco_constant_projection():
    g = F.positions_over_orbit(F.formation_slots("gco", 6, A, N), N)
    np.testing.assert_allclose(np.linalg.norm(g, axis=-1), 2 * A, rtol=1e-9)
    p = F.positions_over_orbit(F.formation_slots("pco", 6, A, N), N)
    np.testing.assert_allclose(np.hypot(p[..., 1], p[..., 2]), 2 * A, rtol=1e-9)


def test_helix_never_crosses_the_along_track_axis():
    h = F.positions_over_orbit(F.formation_slots("helix", 6, A, N), N, samples=360)
    assert np.hypot(h[..., 0], h[..., 2]).min() >= A * (1 - 1e-9)


def test_string_is_static_with_spacing():
    s = F.formation_slots("string", 5, A, N)
    p = F.positions_over_orbit(s, N)
    np.testing.assert_allclose(p, np.broadcast_to(p[0], p.shape), atol=1e-9)
    np.testing.assert_allclose(np.diff(p[0, :, 1]), A)


@pytest.mark.parametrize("shape", F.SHAPES)
def test_min_separation_positive(shape):
    assert F.min_separation(F.formation_slots(shape, 6, A, N), N) > 0.5 * A


@pytest.mark.parametrize("bad", [("hexagon", 6, A), ("pco", 0, A), ("pco", 6, 0.0)])
def test_formation_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        F.formation_slots(*bad, N)


# ---------- laser link ----------
def test_budget_closes_at_click_range_and_formation_range():
    assert isl.data_rate_bps(580e3, TERM) == TERM.max_rate_bps  # CLICK-class: >20 Mbps @ 580 km
    assert isl.margin_db(16e3, TERM) > isl.margin_db(580e3, TERM) + 30.0


def test_inverse_square():
    assert isl.received_power_w(2e4, TERM) == pytest.approx(isl.received_power_w(1e4, TERM) / 4)


def test_pointing_not_power_is_the_limit():
    assert isl.data_rate_bps(16e3, TERM, pointing_error_rad=1.7e-3) < 1.0  # body pointing only
    assert isl.beam_halfwidth_rad(TERM) < 1e-4
    with pytest.raises(ValueError):
        isl.received_power_w(0.0, TERM)


def test_link_state_machine():
    state, timer, ticks = isl.DOWN, 0.0, 0
    while state != isl.LOCKED:
        state, timer = isl.step_link(state, timer, True, 2.0, TERM)
        ticks += 1
    assert ticks == math.ceil(TERM.acquire_s / 2.0)
    assert isl.step_link(isl.LOCKED, 0.0, False, 2.0, TERM) == (isl.DOWN, 0.0)
    assert isl.step_link(isl.ACQUIRING, 10.0, False, 2.0, TERM) == (isl.DOWN, 0.0)


def test_sun_exclusion():
    los = np.array([1.0, 0.0, 0.0])
    assert isl.sun_blinded(los, np.array([1.0, 0.01, 0.0]), TERM)
    assert not isl.sun_blinded(los, np.array([0.0, 1.0, 0.0]), TERM)


def test_topology_degree_cap_determinism_and_keep():
    links = _ring_links()
    assert links == _ring_links()
    deg = [sum(i in link for link in links) for i in range(6)]
    assert max(deg) <= TERM.terminals_per_sat
    pos = np.array([s[:3] for s in F.formation_slots("cartwheel", 6, A, N)])
    kept = isl.plan_topology(pos, ALL, TERM, keep={(0, 3)})
    assert (0, 3) in kept


def test_ring_survives_leader_loss_star_does_not():
    assert isl.components(6, _ring_links(), NO_LEADER) == [[1, 2, 3, 4, 5]]
    assert len(isl.components(6, isl.star_topology(0, 6), NO_LEADER)) == 5


# ---------- decentralised leader functions ----------
def _bids(radio=ALL, links=None):
    links = links if links is not None else _ring_links()
    deg = [sum(i in link for link in links) for i in range(6)]
    return D.default_bids(deg, [1, 0.9, 0.8, 0.7, 0.6, 0.5], [100, 200, 300, 400, 500, 600], radio)


def test_connected_mesh_fills_every_function_once_and_spreads_load():
    out = D.auction(_bids(), _ring_links(), ALL)
    assert not out["vacant"] and not out["split_brain"]
    assert all(len(v) == 1 for v in out["holders"].values())
    assert max(len(h) for h in out["held"]) <= 2
    assert out["rounds"] > 0


def test_leader_death_redistributes_without_vacancy():
    out = D.auction(_bids(), _ring_links(), NO_LEADER)
    assert not out["vacant"] and not out["split_brain"]
    assert out["held"][0] == []


def test_star_hub_death_is_split_brain():
    out = D.auction(_bids(links=isl.star_topology(0, 6)), isl.star_topology(0, 6), NO_LEADER)
    assert set(out["split_brain"]) == set(D.LEADER_FUNCTIONS)


def test_radio_dead_sat_wins_nothing_and_result_is_deterministic():
    radio = [True, True, False, True, True, True]
    a = D.auction(_bids(radio), _ring_links(), ALL)
    assert a["held"][2] == []
    assert a == D.auction(_bids(radio), _ring_links(), ALL)
    with pytest.raises(ValueError):
        D.auction(np.zeros((6, 2)), _ring_links(), ALL)
