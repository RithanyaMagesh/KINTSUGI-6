"""Platform-independent log hash for golden pins (tests/test_canon.py explains why).

Same scenario + seed is byte-identical on ONE machine (asserted separately by
running twice and comparing bytes); across OS/libm only the last float bits move,
so goldens pin this canonical form instead: every float zeroed below `floor`
(noise-floor magnitudes), otherwise rounded to `sig` significant digits, then
json.dumps(sort_keys=True), one line per record.

sig=5 is measured, not chosen by taste: a two_failure log holds ~357k floats and dead
sats drift to ~1.25e6 m, so noise of 1e-13 relative is already 1e-7 m there. Perturbing
every float of that log (rel 1e-13, abs 1e-10, 20 seeds) flipped the hash 0/20 times at
sig=5 but 12/20 at sig=6 and 20/20 at sig=9. A real behaviour change moves values by
far more than 1e-5 relative, so the pin still catches it. CI confirmed the pins on
ubuntu-latest and windows-latest (GitHub Actions run 41190818716, 2026-10-31) as well as
macOS arm64.
"""

from __future__ import annotations

import hashlib
import json
import math


def _canon(obj, sig: int, floor: float):
    if isinstance(obj, float):
        if not math.isfinite(obj):
            return obj
        return 0.0 if abs(obj) < floor else float(f"{obj:.{sig}g}")
    if isinstance(obj, dict):
        return {k: _canon(v, sig, floor) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_canon(v, sig, floor) for v in obj]
    return obj


def canonical_log_hash(lines: list[dict] | bytes, sig: int = 5, floor: float = 1e-6) -> str:
    """sha256 of the canonicalised log; accepts run_scenario lines or written JSONL bytes."""
    if isinstance(lines, bytes):
        lines = [json.loads(line) for line in lines.decode("utf-8").splitlines() if line.strip()]
    payload = "".join(json.dumps(_canon(line, sig, floor), sort_keys=True) + "\n" for line in lines)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
