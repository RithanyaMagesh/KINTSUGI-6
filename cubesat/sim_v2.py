"""Engine v2 (truth dynamics). Task 1.1 stub; filled in by Tasks 1.2-1.5."""

from __future__ import annotations

import threading

from cubesat.scenario import Scenario


def run_scenario_v2(scenario: Scenario, cancel_event: threading.Event | None = None) -> list[dict]:
    raise NotImplementedError("engine v2 lands in Task 1.5")
