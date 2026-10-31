"""Engine v2 (truth dynamics): seeded stream, draw order, EngineV2 (Tasks 1.2-1.5)."""

from __future__ import annotations

import threading

import numpy as np

from cubesat.scenario import Scenario

# Draw-order table (docs/PHYSICS_V2.md). Row positions are fixed: new draws are APPENDED,
# never inserted; conditional rows (4, 6, 7) come after the tick's unconditional ones.
DRAW_ORDER: tuple[str, ...] = (
    "heartbeat_loss",  # 1 rng.random()            Phase 4, every sat every tick
    "measurement_noise",  # 2 rng.standard_normal(6) Phase 4, every sat every tick
    "seu",  # 3 rng.random()                        Phase 3, every sat every tick
    "seu_duration",  # 4 rng.uniform(30, 120)        Phase 3, only on an SEU hit
    "impact",  # 5 rng.random()                      Phase 3, every sat every tick
    "impact_component",  # 6 rng.random()            Phase 3, only on an impact hit
    "impact_fraction",  # 7 rng.uniform(0.2, 0.6)    Phase 3, only on an impact hit
)


def make_rng(scenario: Scenario) -> np.random.Generator:
    """The one sim-owned Generator (v1 never touches it; the seed stays write-only there)."""
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence(scenario.seed)))


def draw_tick(rng: np.random.Generator, n_sats: int) -> dict[str, np.ndarray]:
    """One tick's unconditional rows (1, 2, 3, 5) per sat in ascending id.

    Phases 3-4 are not implemented yet: the values are drawn and ignored so a later phase
    changes no stream position (tests/v2/test_draw_order.py)."""
    hb, seu, imp = np.empty(n_sats), np.empty(n_sats), np.empty(n_sats)
    noise = np.empty((n_sats, 6))
    for i in range(n_sats):
        hb[i] = rng.random()
        noise[i] = rng.standard_normal(6)
        seu[i] = rng.random()
        imp[i] = rng.random()
    return {"heartbeat_u": hb, "noise": noise, "seu_u": seu, "impact_u": imp}


def consume_reserved(rng: np.random.Generator, n_sats: int) -> None:
    """No-op consumer of the reserved rows; Phases 3-4 replace it with real effects."""
    draw_tick(rng, n_sats)


def run_scenario_v2(scenario: Scenario, cancel_event: threading.Event | None = None) -> list[dict]:
    raise NotImplementedError("engine v2 lands in Task 1.5")
