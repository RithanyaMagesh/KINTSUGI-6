"""Replay log loading (BACKEND_SPEC v1.1 section 5.2). No sim dependency.

Per-line defensive parse: a bad line is skipped and counted, never a crash
(section 7.1 "corrupt replay file") -- that includes lines that parse as JSON
but carry a schema-malformed payload, judged by wire.tick_frame_ok (the
wire-format authority decides what is renderable). `frames` holds tick lines
only -- the INIT header and the SUMMARY line are stored separately, mirroring
cubesat.sim's [INIT, tick..., SUMMARY] layout.
"""

from __future__ import annotations

import json
from bisect import bisect_left
from dataclasses import dataclass, field
from pathlib import Path

from cubesat.wire import tick_frame_ok


@dataclass
class ReplayLog:
    frames: list[dict] = field(default_factory=list)  # tick lines only
    times: list[float] = field(default_factory=list)  # parallel array, for bisect
    header: dict | None = None  # the INIT line (scenario, seed, n_sats)
    summary: dict | None = None  # the SUMMARY line (coverage_mean_last_orbit)
    skipped: int = 0  # count of unparseable lines


def load_jsonl(path: Path) -> ReplayLog:
    log = ReplayLog()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                log.skipped += 1
                continue
            if not isinstance(parsed, dict):
                log.skipped += 1
                continue
            state = parsed.get("state")
            if state == "INIT":
                log.header = parsed
            elif state == "SUMMARY":
                log.summary = parsed
            elif isinstance(parsed.get("t"), (int, float)) and tick_frame_ok(parsed):
                log.frames.append(parsed)
                log.times.append(float(parsed["t"]))
            else:
                log.skipped += 1
    return log


def index_at(log: ReplayLog, t: float) -> int:
    """Cursor for seek: first frame with times[i] >= t; before the start -> 0,
    past the end -> hold the last frame (bisect, instant per section 10)."""
    if not log.times:
        return 0
    return min(bisect_left(log.times, t), len(log.times) - 1)


def list_logs(log_dir: Path) -> list[str]:
    """Sorted *.jsonl basenames; empty/missing dir -> [] (never an exception)."""
    if not log_dir.is_dir():
        return []
    return sorted(p.name for p in log_dir.iterdir() if p.is_file() and p.suffix == ".jsonl")
