"""CLI: run a scenario and write a JSONL log.

G0 skeleton: validates the scenario and writes the log header line.
The simulation loop lands in G3.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from cubesat.scenario import load_scenario


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
    args.out.parent.mkdir(parents=True, exist_ok=True)
    header = {
        "v": 1,
        "t": 0.0,
        "state": "INIT",
        "scenario": scenario.name,
        "seed": scenario.seed,
        "n_sats": scenario.n_sats,
    }
    with args.out.open("w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(header, sort_keys=True) + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
