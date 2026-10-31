"""GC probe for the perf audit: are the 30-100 ms one-tick spikes in no-failure runs Python
garbage-collector pauses (the growing `lines` list), not sim work? Runs one scenario with the
collector on and off, interleaved, and compares total time and the tick-time tail. Analysis
layer only (wall clock lives here, never in the sim; the log is untouched).

    uv run python -m cubesat.perf_gc --base data/scenarios --scenario live_24sat \
        --report data/eval/perf_gc_probe.json --repeats 3
"""

from __future__ import annotations

import argparse
import gc
import json
import sys
from pathlib import Path

import numpy as np

from cubesat.perf_bench import TickTimer, _pc, loadavg, sha256_file
from cubesat.perf_ws import stats
from cubesat.scenario import load_scenario
from cubesat.sim import run_scenario


def run_gc_probe(
    sdir: Path, name: str, report: Path, *, repeats: int = 3, command: str = ""
) -> dict:
    path = Path(sdir) / f"{name}.json"
    scn, load0 = load_scenario(path), loadavg()
    rows: dict[str, list[tuple]] = {"gc_on": [], "gc_off": []}
    for _ in range(repeats):  # interleaved so drift hits both modes alike
        for mode in rows:
            gc.collect()
            if mode == "gc_off":
                gc.disable()
            try:
                tt, t0 = TickTimer(), _pc()
                run_scenario(scn, tt)
                total = _pc() - t0
            finally:
                gc.enable()
            d = np.diff(tt.stamps) * 1e3
            rows[mode].append((total, d.max(), np.percentile(d, 99), int((d > 5.0).sum())))
    out = {
        "schema": "perf_gc_probe/1", "command": command, "scenario": name, "repeats": repeats,
        "inputs": {path.name: sha256_file(path)},
        "n_ticks": int(round(scn.duration_s / scn.dt_s)) + 1,
        "load": {"start": load0, "end": loadavg()},
        "modes": {m: {"total_s": stats([r[0] for r in v]), "tick_ms_max": stats([r[1] for r in v]),
                      "tick_ms_p99": stats([r[2] for r in v]),
                      "n_ticks_over_5ms": stats([r[3] for r in v])} for m, v in rows.items()},
    }
    Path(report).parent.mkdir(parents=True, exist_ok=True)
    Path(report).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cubesat.perf_gc", description=__doc__.split("\n")[0])
    ap.add_argument("--base", type=Path, required=True, help="scenarios directory")
    ap.add_argument("--scenario", required=True, help="scenario stem, e.g. live_24sat")
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--repeats", type=int, default=3)
    a = ap.parse_args(argv)
    cmd = "uv run python -m cubesat.perf_gc " + " ".join(argv if argv is not None else sys.argv[1:])
    run_gc_probe(a.base, a.scenario, a.report, repeats=a.repeats, command=cmd)
    print(f"wrote {a.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
