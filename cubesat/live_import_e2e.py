"""Live CubeSat import and simulation determinism end-to-end verification.

Generates scenario from live/cached GRACE-FO cluster data, executes two consecutive
simulation runs, verifies byte-identical event logs (H1 == H2), and validates the
NOMINAL -> FAILURE_DETECTED -> REPLANNING -> RECOVERED state transition lifecycle.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from cubesat.live_import import main as live_import_main
from cubesat.scenario import Scenario
from cubesat.sim import run_scenario


def verify_live_import_e2e() -> bool:
    repo_root = Path(__file__).resolve().parents[1]
    scen_path = repo_root / "data" / "scenarios" / "live_e2e_swarm.json"
    meta_path = repo_root / "data" / "scenarios" / "live_e2e_swarm.meta.json"
    logs_dir = repo_root / "data" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    print("Step 1: Ingesting cluster data and generating live scenario...")
    # Attempt offline or cached import first, falling back gracefully
    cmd_args = [
        "--cluster", "GRACE-FO",
        "--fit-mode", "safe-envelope",
        "--out", str(scen_path.relative_to(repo_root)),
        "--meta-out", str(meta_path.relative_to(repo_root)),
        "--n-sats", "6",
        "--n-failures", "2",
        "--seed", "42",
        "--offline",
    ]
    ret = live_import_main(cmd_args)
    if ret != 0:
        print("Offline cache not found; attempting live network fetch...")
        cmd_args.remove("--offline")
        ret = live_import_main(cmd_args)
        if ret != 0:
            print(f"Error: live_import failed with exit code {ret}", file=sys.stderr)
            return False

    raw_scen = json.loads(scen_path.read_text(encoding="utf-8"))
    scenario = Scenario.model_validate(raw_scen)
    print(f"Scenario validated: {scenario.name} (slots={scenario.formation.n_slots})")

    print("Step 2: Executing simulation run 1...")
    run1 = run_scenario(scenario)
    log_p1 = logs_dir / "live_e2e_run1.jsonl"
    with open(log_p1, "w", encoding="utf-8") as f:
        for entry in run1:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
    h1 = hashlib.sha256(log_p1.read_bytes()).hexdigest()
    print(f"Run 1 SHA-256: {h1}")

    print("Step 3: Executing simulation run 2...")
    run2 = run_scenario(scenario)
    log_p2 = logs_dir / "live_e2e_run2.jsonl"
    with open(log_p2, "w", encoding="utf-8") as f:
        for entry in run2:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
    h2 = hashlib.sha256(log_p2.read_bytes()).hexdigest()
    print(f"Run 2 SHA-256: {h2}")

    print("Step 4: Cryptographic determinism assertion...")
    if h1 != h2:
        print(f"DETERMINISM FAILED: hash mismatch {h1} != {h2}", file=sys.stderr)
        return False
    print("Determinism PASSED: Run 1 and Run 2 logs are byte-identical.")

    print("Step 5: Verifying autonomous recovery state machine transitions...")
    states = [e.get("state") for e in run1 if "state" in e]
    required = ["NOMINAL", "FAILURE_DETECTED", "REPLANNING", "RECOVERED"]
    for req in required:
        if req not in states:
            print(f"Error: Required state {req} not observed in simulation log", file=sys.stderr)
            return False

    idx_nom = states.index("NOMINAL")
    idx_fail = states.index("FAILURE_DETECTED")
    idx_repl = states.index("REPLANNING")
    idx_rec = states.index("RECOVERED")

    if not (idx_nom < idx_fail < idx_repl < idx_rec):
        print(
            f"State transition order invalid: NOMINAL({idx_nom}) -> "
            f"FAILURE_DETECTED({idx_fail}) -> REPLANNING({idx_repl}) -> RECOVERED({idx_rec})",
            file=sys.stderr,
        )
        return False

    print("State transition sequence verified: "
          "NOMINAL -> FAILURE_DETECTED -> REPLANNING -> RECOVERED")
    print("ALL VERIFICATIONS PASSED.")
    return True


if __name__ == "__main__":
    success = verify_live_import_e2e()
    sys.exit(0 if success else 1)
