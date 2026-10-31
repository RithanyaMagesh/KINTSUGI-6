"""v2 formation candidates (physics Phase 5b). SI, LVLH (AGENTS.md invariants 3-4).

Not wired into the engine: the sim keeps using `sim.build_slots`; this module is the
candidate generator the psi trade table (cubesat/psi_table.py) and later phases use.
"""

from __future__ import annotations

import math

import numpy as np

from cubesat.hcw import slot_initial_state


def candidate_slots(
    amp_m: float, phase0_rad: float, psi_deg: float, n_slots: int, n: float
) -> list[np.ndarray]:
    """6-D slot states at t = 0 (SI, LVLH) on the passive relative orbit:
    x = A cos(th), y = -2A sin(th), z = B cos(th + psi), B = A, th = phase0 + 2 pi j/k.

    In-plane part (x, y, vx, vy) is hcw.slot_initial_state at th; the cross-track part
    (z, vz) is the same function at th + psi, so z = B cos(nt + th + psi) and
    vz = -B n sin(nt + th + psi): still passive (closes each period, zero hold fuel).
    psi = 0 returns hcw.slot_initial_state(A, A, th, n) bit for bit (v1 slots)."""
    if not math.isfinite(psi_deg):
        raise ValueError(f"psi_deg must be finite, got {psi_deg!r}")
    psi = math.radians(psi_deg)
    out = []
    for j in range(n_slots):
        th = phase0_rad + 2.0 * math.pi * j / n_slots
        s = slot_initial_state(amp_m, amp_m, th, n)
        s[[2, 5]] = slot_initial_state(amp_m, amp_m, th + psi, n)[[2, 5]]
        out.append(s)
    return out
