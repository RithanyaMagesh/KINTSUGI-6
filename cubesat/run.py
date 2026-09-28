"""CLI: run a scenario and write the versioned JSONL log (gate G3).

I/O edge only: the simulation is cubesat.sim.run_scenario (pure; no wall clock,
no RNG -- AGENTS.md invariant 2), so the log bytes depend only on the scenario
and seed. Two runs of the same scenario are byte-identical; the short nominal
run is pinned to a golden SHA-256 by tests/test_cli.py::test_run_is_byte_deterministic.
The log is NOT committed (data/logs/ is gitignored); commit the hash, not the log.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from cubesat.scenario import load_scenario
from cubesat.sim import run_scenario


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="cubesat.run", description=__doc__)
    parser.add_argument("--scenario", required=True, type=Path, help="path to scenario JSON")
    parser.add_argument("--seed", type=int, default=None, help="override the scenario seed")
    parser.add_argument("--out", required=True, type=Path, help="path to the JSONL run log")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        scenario = load_scenario(args.scenario)
    except ValidationError as exc:
        print(f"invalid scenario {args.scenario}:\n{exc}", file=sys.stderr)
        return 2
    if args.seed is not None:
        scenario = scenario.model_copy(update={"seed": args.seed})
    lines = run_scenario(scenario)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as f:
        for line in lines:
            f.write(json.dumps(line, sort_keys=True) + "\n")
    print(f"wrote {args.out}")
    print(f"coverage_mean_last_orbit = {lines[-1]['coverage_mean_last_orbit']:.6f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
