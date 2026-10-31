"""The one sim-owned random stream of engine v2 and its fixed draw order (docs/PHYSICS_V2.md)."""

from __future__ import annotations

import numpy as np

from cubesat.scenario import Scenario

# Draw-order table (docs/PHYSICS_V2.md). Every row is drawn for every sat at every tick, in this
# order, whether or not its event fires, so a hit never shifts any later draw. New rows are
# appended, never inserted.
DRAW_ORDER: tuple[str, ...] = (
    "heartbeat_loss",  # 1 rng.random()               Phase 4
    "measurement_noise",  # 2 rng.standard_normal(6)   Phase 4
    "seu",  # 3 rng.random()                           Phase 3
    "seu_duration",  # 4 rng.uniform(30, 120)           Phase 3 (used only on an SEU hit)
    "impact",  # 5 rng.random()                         Phase 3
    "impact_component",  # 6 rng.random()               Phase 3 (used only on an impact hit)
    "impact_fraction",  # 7 rng.uniform(0.2, 0.6)       Phase 3 (used only on an impact hit)
)


def make_rng(scenario: Scenario) -> np.random.Generator:
    """The one sim-owned Generator (v1 never touches it; the seed stays write-only there)."""
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence(scenario.seed)))


def draw_tick(rng: np.random.Generator, n_sats: int) -> dict[str, np.ndarray]:
    """One tick's draws, rows 1-7 per sat in ascending id. Phases 3-4 are not implemented yet:
    the values are drawn and ignored, so a later phase changes no stream position."""
    out = {
        k: np.empty(n_sats)
        for k in ("heartbeat_u", "seu_u", "seu_duration", "impact_u")
        + ("impact_component", "impact_fraction")
    }
    out["noise"] = np.empty((n_sats, 6))
    for i in range(n_sats):
        out["heartbeat_u"][i] = rng.random()
        out["noise"][i] = rng.standard_normal(6)
        out["seu_u"][i] = rng.random()
        out["seu_duration"][i] = rng.uniform(30.0, 120.0)
        out["impact_u"][i] = rng.random()
        out["impact_component"][i] = rng.random()
        out["impact_fraction"][i] = rng.uniform(0.2, 0.6)
    return out
