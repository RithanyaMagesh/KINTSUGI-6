import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Canonical golden SHA-256 of the short-run JSONL (nominal.json with duration_s = 600.0,
# seed 42), pinned per docs/MASTER_PROMPT.md section 3.8.
# Cross-platform canonicalization: all floats rounded to 9 significant digits before
# json.dumps(sort_keys=True).
GOLDEN_NOMINAL_SHORT_CANONICAL_SHA256 = (
    "ce1a8075f2fd828ca036decd81a5aa3f99afee1a2dd135b8eee8bfa51e22ea52"
)


def _round_floats(obj, sig: int = 9):
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj) or obj == 0.0:
            return obj
        return float(f"{obj:.{sig}g}")
    if isinstance(obj, dict):
        return {k: _round_floats(v, sig) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_floats(v, sig) for v in obj]
    return obj


def canonical_log_hash(raw_bytes: bytes, sig: int = 9) -> str:
    lines = raw_bytes.decode("utf-8").splitlines()
    normalized = []
    for line in lines:
        if not line.strip():
            continue
        obj = json.loads(line)
        r_obj = _round_floats(obj, sig=sig)
        normalized.append(json.dumps(r_obj, sort_keys=True))
    payload = ("\n".join(normalized) + "\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _short_nominal_scenario(path: Path) -> Path:
    """nominal.json trimmed to a 600 s run (301 ticks at dt = 2 s): fast, still
    exercises the full sim loop, and regression-pins the committed scenario file."""
    payload = json.loads(
        (ROOT / "data" / "scenarios" / "nominal.json").read_text(encoding="utf-8")
    )
    payload["duration_s"] = 600.0
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path


def _run_cli(scenario: Path, out: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "cubesat.run",
            "--scenario",
            str(scenario),
            "--seed",
            "42",
            "--out",
            str(out),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_run_writes_valid_jsonl(tmp_path):
    out = tmp_path / "log.jsonl"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "cubesat.run",
            "--scenario",
            str(ROOT / "data" / "scenarios" / "nominal.json"),
            "--seed",
            "42",
            "--out",
            str(out),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 1
    header = json.loads(lines[0])
    assert header["v"] == 1
    assert header["n_sats"] == 6
    assert header["seed"] == 42


def test_run_is_byte_deterministic(tmp_path):
    """Two runs of a short nominal scenario produce byte-identical JSONL on the same
    machine (AGENTS.md invariant 2: same scenario + seed => byte-identical log)."""
    scenario = _short_nominal_scenario(tmp_path / "nominal_short.json")
    outs = []
    for name in ("run1.jsonl", "run2.jsonl"):
        out = tmp_path / name
        result = _run_cli(scenario, out)
        assert result.returncode == 0, result.stderr
        outs.append(out)
    first = outs[0].read_bytes()
    second = outs[1].read_bytes()
    assert first == second, "two runs of the same scenario + seed differ byte-wise"


def test_run_matches_canonical_golden_hash(tmp_path):
    """The short nominal scenario log matches the platform-independent canonical golden
    hash (floats rounded to 9 significant digits before json.dumps(sort_keys=True))."""
    scenario = _short_nominal_scenario(tmp_path / "nominal_short.json")
    out = tmp_path / "run.jsonl"
    result = _run_cli(scenario, out)
    assert result.returncode == 0, result.stderr
    raw_bytes = out.read_bytes()
    digest = canonical_log_hash(raw_bytes, sig=9)
    assert digest == GOLDEN_NOMINAL_SHORT_CANONICAL_SHA256, (
        f"canonical golden hash mismatch: got {digest}"
    )


def test_run_rejects_invalid_scenario(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"name": "bad"}', encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "cubesat.run",
            "--scenario",
            str(bad),
            "--out",
            str(tmp_path / "log.jsonl"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 2
    assert "invalid scenario" in result.stderr
