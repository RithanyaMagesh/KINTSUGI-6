"""Where the two_failure survivor fuel goes (attribution by switches that already exist).

data/scenarios/two_failure.json as engine v2, a_max 0.01, 0.2 kg / Isp 40 s / F_max 0.04 N,
17028 s, v1 PD seat-holder (no recovery). Three configurations of the truth model:
  full      J2 on, drag on (the default truth)
  two-body  J2 off AND density_factor 0 (gravity only)
  drag only J2 off, drag on
Survivors = sats 0, 3, 4, 5 (sats 1 and 2 die). dv_used is the sum of |a| dt.

Command: uv run python -m pytest tests/v2/test_fuel_attribution.py -s
"""

import json
from pathlib import Path

import pytest

from cubesat.scenario import Scenario
from cubesat.sim_v2 import EngineV2

ROOT = Path(__file__).resolve().parents[2]
SURVIVORS = (0, 3, 4, 5)
CONFIGS = {
    "full": {},
    "two-body": {"j2_enabled": False, "density_factor": 0.0},
    "drag only": {"j2_enabled": False},
}


def _survivor_dv(truth: dict) -> list[float]:
    payload = json.loads((ROOT / "data" / "scenarios" / "two_failure.json").read_text())
    payload.update(engine="v2", a_max_mps2=0.01, truth=truth)
    last = [x for x in EngineV2(Scenario.model_validate(payload)).run() if "sats" in x][-1]
    return [last["sats"][i]["dv_used"] for i in SURVIVORS]


@pytest.mark.slow
def test_survivor_fuel_attribution_full_vs_two_body_vs_drag_only():
    dv = {name: _survivor_dv(truth) for name, truth in CONFIGS.items()}
    print(f"\n{'config':>10} " + " ".join(f"sat{i:>1} dv m/s" for i in SURVIVORS))
    for name, row in dv.items():
        print(f"{name:>10} " + " ".join(f"{x:>11.4f}" for x in row))
    drag_gap = max(abs(a - b) for a, b in zip(dv["drag only"], dv["two-body"], strict=True))
    j2_gap = min(a - b for a, b in zip(dv["full"], dv["two-body"], strict=True))
    print(f"drag-only minus two-body, worst |gap|: {drag_gap:.2e} m/s; "
          f"full minus two-body, smallest gap: {j2_gap:.4f} m/s")
    assert drag_gap < 1e-2  # drag does not move the survivor fuel by even 10 mm/s
    assert j2_gap > 0.0  # J2 adds to it
