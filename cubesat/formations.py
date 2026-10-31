"""Selectable drift-free formation shapes (HCW, LVLH: x radial, y along-track, z cross-track).

Pure functions, SI units, no RNG. Wired in by `sim.build_slots` via `scenario.formation.shape`
(track C step C3); the default `cartwheel` is byte-identical to the v1 slots, so every golden pin
is untouched. Only engine v2 accepts the other shapes (the v1 allocator sweeps the cartwheel).

Every slot lies on x = A cos u, y = y0 - 2A sin u, z = B cos(u + psi), u = n t + theta. That is
drift-free because vy0 = -2 n x0 (HCW), so each shape repeats exactly once per orbit.

shape      B          psi   y0          property
cartwheel  A          0     0           v1 shape (= hcw.slot_initial_state(A, A, ...))
pco        2A         0     0           projected circle of radius 2A in the (y, z) plane
gco        sqrt(3) A  0     0           true 3-D circle: range to the chief is always 2A
helix      A          pi/2  0           x and z never both zero (e/i separation, TanDEM-X)
string     A = 0      -     (j - c) A   along-track train, static in HCW; A = spacing

Tetrahedron (MMS) is left out on purpose: it is regular at one point per orbit only and needs
exactly 4 sats.
"""

from __future__ import annotations

import math

import numpy as np

SHAPES = ("cartwheel", "pco", "gco", "helix", "string")


def slot_state(a: float, b: float, theta: float, n: float, psi: float = 0.0, y0: float = 0.0):
    """6-D LVLH state [x, y, z, vx, vy, vz] at t = 0 on the drift-free relative orbit above."""
    c, s = math.cos(theta), math.sin(theta)
    cz, sz = math.cos(theta + psi), math.sin(theta + psi)
    y = y0 - 2.0 * a * s if y0 else -2.0 * a * s  # y0 = 0: keep -0.0 bytes (= hcw slot, v1 log)
    return np.array([a * c, y, b * cz, -a * n * s, -2.0 * a * n * c, -b * n * sz])


def formation_slots(
    shape: str, n_slots: int, radial_amp_m: float, n: float, phase_offset_rad: float = 0.0
) -> list[np.ndarray]:
    """Slot states for `n_slots` sats, slot j at phase offset + 2*pi*j/n_slots (string: position).

    radial_amp_m is the radial amplitude A for the elliptic shapes and the along-track spacing for
    `string`. Raises ValueError for an unknown shape, n_slots < 1 or a non-positive amplitude."""
    if shape not in SHAPES:
        raise ValueError(f"unknown formation shape {shape!r}; known: {list(SHAPES)}")
    if n_slots < 1 or radial_amp_m <= 0.0:
        raise ValueError("need n_slots >= 1 and radial_amp_m > 0")
    a = radial_amp_m
    if shape == "string":
        centre = (n_slots - 1) / 2.0
        return [slot_state(0.0, 0.0, 0.0, n, y0=(j - centre) * a) for j in range(n_slots)]
    b, psi = {
        "cartwheel": (a, 0.0),
        "pco": (2.0 * a, 0.0),
        "gco": (math.sqrt(3.0) * a, 0.0),
        "helix": (a, math.pi / 2.0),
    }[shape]
    return [
        slot_state(a, b, phase_offset_rad + 2.0 * math.pi * j / n_slots, n, psi)
        for j in range(n_slots)
    ]


def positions_over_orbit(slots: list[np.ndarray], n: float, samples: int = 72) -> np.ndarray:
    """(samples, n_sats, 3) LVLH positions over one orbit from the analytic HCW solution.

    Valid only for the drift-free family above (closed form, no STM needed)."""
    u = np.linspace(0.0, 2.0 * math.pi, samples, endpoint=False)[:, None]  # n*t
    out = np.empty((samples, len(slots), 3))
    for i, s in enumerate(slots):
        x0, y0, z0, vx0, vy0, vz0 = s
        # x = x0 cos u + (vx0/n) sin u; y = y_c - 2 x0 sin u + (2 vx0/n)(cos u - 1) (drift-free)
        out[:, i, 0] = (x0 * np.cos(u) + vx0 / n * np.sin(u))[:, 0]
        out[:, i, 1] = (y0 - 2.0 * x0 * np.sin(u) + 2.0 * vx0 / n * (np.cos(u) - 1.0))[:, 0]
        out[:, i, 2] = (z0 * np.cos(u) + vz0 / n * np.sin(u))[:, 0]
    return out


def min_separation(slots: list[np.ndarray], n: float, samples: int = 72) -> float:
    """Smallest pairwise distance between any two slots over one orbit, m (inf for one sat)."""
    p = positions_over_orbit(slots, n, samples)
    if p.shape[1] < 2:
        return math.inf
    d = np.linalg.norm(p[:, :, None, :] - p[:, None, :, :], axis=-1)
    iu = np.triu_indices(p.shape[1], k=1)
    return float(d[:, iu[0], iu[1]].min())
