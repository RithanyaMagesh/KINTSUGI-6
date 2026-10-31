"""Shared builders for the certificate tests (Phase 5d-1). Not a test module."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from cubesat.allocate_v2 import candidate_slots
from cubesat.hcw import mean_motion
from cubesat.scenario import Scenario
from cubesat.sim_v2 import EngineV2

ROOT = Path(__file__).resolve().parents[2]
NOMINAL = json.loads((ROOT / "data" / "scenarios" / "nominal.json").read_text())
ALT_M = 500e3
N_MM = mean_motion(ALT_M)
PERIOD = 2.0 * math.pi / N_MM
SENSOR = {"fov_half_angle_deg": 1.5, "grid_step_km": 2.0, "grid_extent_km": 20.0}


def scn(amp_km: float = 2.0, **over) -> Scenario:
    """A v2 scenario, 6 sats, 2 orbits + margin, a_max 0.01, min_sep 500 m."""
    d = {
        **NOMINAL,
        "engine": "v2",
        "duration_s": 2.0 * PERIOD + 200.0,
        "sensor": SENSOR,
        "formation": {"n_slots": 6, "radial_amp_km": amp_km, "phase_offset_deg": 0.0},
        "a_max_mps2": 0.01,
        "failures": [],
        "allocation": {"min_sep_km": 0.5},
    }
    return Scenario.model_validate({**d, **over})


def slots(amp_km: float, psi_deg: float = 0.0, n_slots: int = 6) -> list[np.ndarray]:
    return candidate_slots(amp_km * 1000.0, 0.0, psi_deg, n_slots, N_MM)


def engine_at(scenario: Scenario, ticks: int = 0, psi_deg: float | None = None) -> EngineV2:
    """EngineV2 stepped `ticks` ticks; psi_deg starts the sats on psi-slots AND points the
    seat references at them (public attributes only), so holding holds those slots."""
    if psi_deg is None:
        eng = EngineV2(scenario)
    else:
        seats = np.array(slots(scenario.formation.radial_amp_km, psi_deg, scenario.n_sats))
        eng = EngineV2(scenario, initial_lvlh=seats)
        eng.refs = seats.copy()
    for _ in range(ticks):
        eng.step()
    return eng
