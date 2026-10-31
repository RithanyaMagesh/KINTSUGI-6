"""Task 1.2: one sim-owned Generator and a fixed, documented draw order.

Table (rows fixed so phases can land in any order; mirrored in docs/PHYSICS_V2.md,
checked by test_doc_table_matches once that file exists):
 1 heartbeat_loss  rng.random()            Phase 4  unconditional
 2 measurement_noise rng.standard_normal(6) Phase 4  unconditional
 3 seu             rng.random()            Phase 3  unconditional
 4 seu_duration    rng.uniform(30,120)     Phase 3  only on an SEU hit (after unconditional rows)
 5 impact          rng.random()            Phase 3  unconditional
 6 impact_component rng.random()           Phase 3  only on an impact hit
 7 impact_fraction rng.uniform(0.2,0.6)    Phase 3  only on an impact hit
"""

import json
from pathlib import Path

import numpy as np

from cubesat import sim_v2
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
    assert sim_v2.DRAW_ORDER == EXPECTED_ORDER


def test_reserved_rows_consumed_as_noops():
    """draw_tick consumes rows 1,2,3,5 per sat in ascending id; a later phase replaces
    consume_reserved with real effects but must keep this exact consumption."""
    a = sim_v2.make_rng(_scenario(3))
    out = sim_v2.draw_tick(a, 4)
    b = sim_v2.make_rng(_scenario(3))
    for i in range(4):
        assert b.random() == out["heartbeat_u"][i]
        assert np.array_equal(b.standard_normal(6), out["noise"][i])
        assert b.random() == out["seu_u"][i]
        assert b.random() == out["impact_u"][i]
    assert a.bit_generator.state == b.bit_generator.state
    c = sim_v2.make_rng(_scenario(3))
    sim_v2.consume_reserved(c, 4)
    assert c.bit_generator.state == a.bit_generator.state

