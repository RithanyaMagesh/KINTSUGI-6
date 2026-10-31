"""Task 1.2: one sim-owned Generator and a fixed, documented draw order.

Every row is drawn for every sat at every tick (rows in table order, sats ascending), whether or
not its event fires: docs/PHYSICS_V2.md. The per-row consumption is pinned in
tests/v2/test_p1_fixes.py (test_all_seven_rows_drawn_per_sat_per_tick).
"""

import json
import re
from pathlib import Path

import numpy as np

from cubesat import rng_v2, sim_v2
from cubesat.scenario import Scenario

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_ORDER = (
    "heartbeat_loss",
    "measurement_noise",
    "seu",
    "seu_duration",
    "impact",
    "impact_component",
    "impact_fraction",
)


def _scenario(seed: int) -> Scenario:
    payload = json.loads((ROOT / "data" / "scenarios" / "nominal.json").read_text())
    return Scenario.model_validate({**payload, "seed": seed, "engine": "v2"})


def test_same_seed_same_stream():
    a, b = sim_v2.make_rng(_scenario(7)), sim_v2.make_rng(_scenario(7))
    assert [a.random() for _ in range(5)] == [b.random() for _ in range(5)]


def test_different_seed_differs():
    a, b = sim_v2.make_rng(_scenario(7)), sim_v2.make_rng(_scenario(8))
    assert [a.random() for _ in range(5)] != [b.random() for _ in range(5)]


def test_generator_is_pcg64_seedsequence():
    rng = sim_v2.make_rng(_scenario(7))
    ref = np.random.Generator(np.random.PCG64(np.random.SeedSequence(7)))
    assert rng.bit_generator.state == ref.bit_generator.state


def test_draw_order_constant():
    assert rng_v2.DRAW_ORDER == EXPECTED_ORDER


def test_doc_table_matches():
    """docs/PHYSICS_V2.md draw-order table rows (in order) equal DRAW_ORDER."""
    text = (ROOT / "docs" / "PHYSICS_V2.md").read_text(encoding="utf-8")
    names = re.findall(r"^\| (\d) \| `(\w+)` \|", text, flags=re.M)
    assert [int(n) for n, _ in names] == list(range(1, 8))
    assert tuple(name for _, name in names) == rng_v2.DRAW_ORDER
