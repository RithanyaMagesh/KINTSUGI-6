"""canonical_log_hash: platform-independent log pin (replaces the per-OS hash maps).

Why an absolute floor as well as significant digits: a 600 s nominal log carries
~1.8k floats that are pure rounding noise (idle sats' velocities and dv_used,
7e-16 .. 3e-12); rounding those to 9 SIGNIFICANT digits keeps the noise, so the
hash differed per platform. Magnitudes below `floor` are therefore zeroed. sig=5 is the
measured robust setting (see cubesat/canon.py docstring).
"""

import json

from cubesat.canon import canonical_log_hash

LINE = {"t": 2.0, "r": [1.2345678912345, -9876.54321098765, 4.0e-12], "dv_used": 3.0e-13,
        "event": {"type": "X", "payload": {"cost": 3.7726621102252285}}}


def _h(**changes):
    line = json.loads(json.dumps(LINE))
    for k, v in changes.items():
        line[k] = v
    return canonical_log_hash([line])


def test_relative_noise_is_invisible():
    assert _h(r=[1.2345678912345 * (1 + 1e-9), -9876.54321098765 * (1 - 1e-9), 4.0e-12]) == _h()


def test_noise_floor_values_are_invisible():
    assert _h(dv_used=7.4e-16, r=[1.2345678912345, -9876.54321098765, -2.7e-12]) == _h()


def test_real_change_is_visible():
    assert _h(r=[1.2345678912345 * (1 + 1e-3), -9876.54321098765, 4.0e-12]) != _h()


def test_bytes_and_lines_agree():
    raw = (json.dumps(LINE, sort_keys=True) + "\n").encode()
    assert canonical_log_hash(raw) == canonical_log_hash([LINE])


def test_negative_zero_equals_zero():
    assert _h(dv_used=-0.0) == _h(dv_used=0.0)


def test_stable_under_platform_scale_noise_on_a_real_log():
    """Perturb every float of a real run (rel 1e-13, abs 1e-10: 10-1000x the recorded
    cross-platform divergence) and the hash must not move."""
    import random
    from pathlib import Path

    from cubesat.scenario import load_scenario
    from cubesat.sim import run_scenario

    two = Path(__file__).resolve().parents[1] / "data" / "scenarios" / "two_failure.json"
    lines = run_scenario(load_scenario(two).model_copy(update={"duration_s": 1800.0}))

    def jig(o, rng):
        if isinstance(o, float):
            return o * (1 + rng.uniform(-1e-13, 1e-13)) + rng.uniform(-1e-10, 1e-10)
        if isinstance(o, dict):
            return {k: jig(v, rng) for k, v in o.items()}
        if isinstance(o, list):
            return [jig(v, rng) for v in o]
        return o

    base = canonical_log_hash(lines)
    for seed in range(5):
        rng = random.Random(seed)
        assert canonical_log_hash([jig(line, rng) for line in lines]) == base
