"""Coverage-metric tests (docs/MASTER_PROMPT.md sections 3.4 and 3.8, gate G3).

Tests-first: cubesat.coverage and cubesat.sim do not exist yet, so this file fails
collection with ModuleNotFoundError until G3 implements them. Required contract:

    cubesat.coverage.footprint_radius(altitude_m, fov_half_angle_rad) -> float
    cubesat.coverage.target_grid(step_m, extent_m)  -> np.ndarray (N, 2), rows (y, z), m
    cubesat.coverage.coverage_fraction(centers_yz, grid, radius_m) -> float in [0, 1]
    cubesat.sim.build_slots(scenario, n) -> list[np.ndarray] of shape (6,), SI, LVLH

All quantities SI (AGENTS.md invariant 3): m, rad, m/s. LVLH frame (invariant 4).
No wall clock, no RNG (invariant 2). The master prompt's r_f = h*tan(FOV/2) stores
FOV/2 directly as Sensor.fov_half_angle_deg, so footprint_radius takes the half angle.
"""

import math
from pathlib import Path

import numpy as np

from cubesat.coverage import coverage_fraction, footprint_radius, target_grid
from cubesat.hcw import mean_motion, propagate
from cubesat.scenario import load_scenario
from cubesat.sim import build_slots

ROOT = Path(__file__).resolve().parents[1]
NOMINAL = ROOT / "data" / "scenarios" / "nominal.json"


def test_footprint_radius_formula():
    """r_f = h*tan(FOV/2) with the half angle (MASTER_PROMPT 3.4); literals pin the
    formula against whole-angle bugs (tan(FOV) instead of tan(FOV/2) doubles r_f)."""
    r_1deg = footprint_radius(500e3, math.radians(1.0))
    r_2deg = footprint_radius(500e3, math.radians(2.0))
    assert math.isclose(r_1deg, 8727.532464108792, rel_tol=1e-12)
    assert math.isclose(r_2deg, 17460.384745873864, rel_tol=1e-12)


def test_grid_layout_deterministic():
    """Grid spans [-extent, +extent] on both axes with the requested spacing, built in
    a fixed order (AGENTS.md invariant 2); nominal.json sensor gives 31x31 = 961 points."""
    grid = target_grid(2000.0, 30000.0)
    assert grid.shape == (961, 2)
    assert np.array_equal(grid[0], [-30000.0, -30000.0])
    assert np.array_equal(grid[-1], [30000.0, 30000.0])
    step = np.diff(grid[:31, 0])
    assert np.allclose(step, 2000.0)


def test_coverage_monotonic_in_sats():
    """Removing a satellite never raises coverage (MASTER_PROMPT 3.8).

    Metric level, against the committed nominal scenario: at 12 times across one
    orbit, coverage over every 3-of-4 imager subset is <= full coverage (exact --
    the covered set is a boolean OR, so a subset's mask is contained in the full
    mask), and full coverage strictly exceeds any single imager's (footprints do
    not fully overlap, else the metric would be meaningless per MASTER_PROMPT 3.4).

    Also measures research patch #2's design target with the metric as defined
    (never retuned): with 2 of the 4 imagers dead and NO recovery, the drop in
    time-averaged coverage over one orbit must be >= 15 percentage points for
    EVERY imager pair. Slot spacing / FOV are tuned to meet this; the metric is not.
    """
    scenario = load_scenario(NOMINAL)
    altitude_m = scenario.chief.altitude_km * 1000.0
    n = mean_motion(altitude_m)
    period = 2.0 * math.pi / n
    slots = build_slots(scenario, n)
    assert len(slots) == scenario.n_sats == scenario.formation.n_slots

    # Slot construction must be drift-free (vy0 = -2*n*x0): the slot state closes
    # after one period, else the formation walks and coverage drifts spuriously.
    for slot in (slots[0], slots[3]):
        closed = np.asarray(propagate(slot, period, n))
        assert np.allclose(closed, slot, rtol=1e-8, atol=1e-6)

    r_f = footprint_radius(altitude_m, math.radians(scenario.sensor.fov_half_angle_deg))
    # Research patch #2 band: half-angle 1-2 deg -> r_f ~9-17 km at 500 km.
    assert 1.0 <= scenario.sensor.fov_half_angle_deg <= 2.0
    assert 8.0e3 <= r_f <= 18.0e3

    grid = target_grid(
        scenario.sensor.grid_step_km * 1000.0, scenario.sensor.grid_extent_km * 1000.0
    )
    imager_ids = [i for i, role in enumerate(scenario.roles) if role == "imager"]
    assert len(imager_ids) == 4

    def centers_at(t):
        return np.array([np.asarray(propagate(slots[i], t, n))[1:3] for i in imager_ids])

    # Monotonicity under removal, sampled across one orbit.
    for k in range(12):
        centers = centers_at(k * period / 12.0)
        full = coverage_fraction(centers, grid, r_f)
        for j in range(len(imager_ids)):
            without_j = coverage_fraction(np.delete(centers, j, axis=0), grid, r_f)
            assert without_j <= full, (
                f"t={k * period / 12.0:.1f}s: removing imager {j} raised coverage "
                f"{full} -> {without_j}"
            )
        singles = [coverage_fraction(centers[i : i + 1], grid, r_f) for i in range(len(imager_ids))]
        assert full > max(singles), (
            f"t={k * period / 12.0:.1f}s: union of 4 imagers ({full}) does not strictly "
            f"exceed the best single imager ({max(singles)}) -- footprints overlap fully"
        )

    # Research patch #2 design target, time-averaged over one orbit (48 samples):
    # 2 imagers dead, no recovery, remaining imagers keep their slots.
    sample_t = [k * period / 48.0 for k in range(48)]

    def mean_coverage(kept_ids):
        total = 0.0
        for t in sample_t:
            centers = np.array(
                [np.asarray(propagate(slots[i], t, n))[1:3] for i in kept_ids]
            )
            total += coverage_fraction(centers, grid, r_f)
        return total / len(sample_t)

    full_mean = mean_coverage(imager_ids)
    pair_drops = []
    for a in range(4):
        for b in range(a + 1, 4):
            kept = [imager_ids[i] for i in range(4) if i not in (a, b)]
            pair_drops.append(full_mean - mean_coverage(kept))
    print(
        f"test_coverage_monotonic_in_sats: mean coverage over one orbit (4 imagers) = "
        f"{full_mean:.4f}; 2-imagery-death no-recovery drop min = {min(pair_drops):.4f}, "
        f"max = {max(pair_drops):.4f} (target >= 0.15, research patch #2)"
    )
    assert min(pair_drops) >= 0.15, (
        f"worst 2-imager no-recovery drop {min(pair_drops):.4f} < 15 points: "
        "retune slot spacing / FOV, never the metric"
    )
