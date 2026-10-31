"""Measured fuel demonstration (a measurement, not a planner claim): data/scenarios/two_failure.json
as engine v2 with the illustrative 0.2 kg / Isp 40 s / F_max 0.04 N spacecraft block and
a_max 0.01 m/s^2. The controller is still the v1 PD seat-holder (no recovery): sats 1 and 2 die
at t = 1200 / 1500 s, the rest hold their seats against drag and J2.

Command: uv run python -m pytest tests/v2/test_fuel_demo_two_failure.py -s
"""

import json
import math
from pathlib import Path

import pytest

from cubesat.scenario import Scenario
from cubesat.sim_v2 import EngineV2
from cubesat.spacecraft import G0

ROOT = Path(__file__).resolve().parents[2]
M0, MP, ISP = 4.0, 0.2, 40.0


def test_two_failure_fuel_use_v2_measured():
    payload = json.loads((ROOT / "data" / "scenarios" / "two_failure.json").read_text())
    payload.update(
        engine="v2",
        a_max_mps2=0.01,
        spacecraft={"m_prop_kg": MP, "isp_s": ISP, "f_max_n": 0.04},
    )
    lines = [x for x in EngineV2(Scenario.model_validate(payload)).run() if "sats" in x]
    last = lines[-1]["sats"]
    dry = {}
    for x in lines:
        for e in x.get("events", []):
            if e["type"] == "FUEL_DEPLETED":
                dry[e["payload"]["sat_id"]] = x["t"]
    print(f"\n{'sat':>3} {'role':>9} {'status':>14} {'dv_used m/s':>12} {'fuel_used kg':>13}"
          f" {'left m/s':>9} {'dry at t [s]':>13}")
    for s in last:
        used = MP - s["fuel_kg"]
        print(f"{s['id']:>3} {s['role']:>9} {s['status']:>14} {s['dv_used']:>12.4f} {used:>13.6f}"
              f" {s['fuel_mps_left']:>9.4f} {dry.get(s['id'], float('nan')):>13.1f}")
        assert s["fuel_kg"] >= 0.0
        # dv_used (sum of a dt) agrees with the rocket equation on the propellant burned
        want = ISP * G0 * math.log(M0 / (M0 - used)) if used > 0 else 0.0
        assert s["dv_used"] == pytest.approx(want, rel=1e-3, abs=1e-6)
    print(f"tank {ISP * G0 * math.log(M0 / (M0 - MP)):.4f} m/s; dry sats: {sorted(dry)}")
