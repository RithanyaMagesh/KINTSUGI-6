"""Coverage metric (docs/MASTER_PROMPT.md section 3.4, gate G3).

A fixed grid of ground targets in the (y, z) along/cross-track plane; each healthy
imager covers the grid points within footprint radius r_f = h*tan(FOV/2) of its own
(y, z) position (nadir-pointing imager onto a flat ground plane h below the chief;
formation |x| << h, so r_f uses the chief altitude exactly as the master prompt's
formula). Coverage is the fraction of grid points inside the UNION of the healthy
imagers' footprints -- the definition is fixed here and is never retuned
(research patch #2: tune slot spacing / FOV instead).

SI units (AGENTS.md invariant 3): positions and radii in m, angles in rad.
Deterministic (AGENTS.md invariant 2): fixed grid construction order; coverage is
a boolean OR of per-center point-in-disc masks, so removing a center can only
shrink the covered set (asserted by tests/test_coverage.py).
"""

from __future__ import annotations

import math

import numpy as np


def footprint_radius(altitude_m: float, fov_half_angle_rad: float) -> float:
    """r_f = h*tan(FOV/2) (MASTER_PROMPT 3.4). The scenario stores FOV/2 directly
    (Sensor.fov_half_angle_deg), so the argument is the half angle."""
    return altitude_m * math.tan(fov_half_angle_rad)


def target_grid(step_m: float, extent_m: float) -> np.ndarray:
    """Square target grid in the (y, z) plane: -extent..+extent on both axes with
    spacing step_m, rows (y, z), y fastest. Shape (N, 2), SI m."""
    n_per_axis = int(round(2.0 * extent_m / step_m)) + 1
    axis = np.linspace(-extent_m, extent_m, n_per_axis)
    return np.array([(y, z) for z in axis for y in axis])


def coverage_fraction(centers_yz, grid: np.ndarray, radius_m: float) -> float:
    """Fraction of grid points within radius_m of ANY center: the union of the
    footprint discs. centers_yz: array-like (C, 2) of (y, z) positions in m;
    C = 0 -> 0.0. Exact subset-monotone under center removal (boolean OR)."""
    centers = np.asarray(centers_yz, dtype=float).reshape(-1, 2)
    if centers.shape[0] == 0:
        return 0.0
    d2 = (grid[:, None, 0] - centers[None, :, 0]) ** 2 + (
        grid[:, None, 1] - centers[None, :, 1]
    ) ** 2
    covered = (d2 <= radius_m * radius_m).any(axis=1)
    return float(covered.sum()) / float(grid.shape[0])
