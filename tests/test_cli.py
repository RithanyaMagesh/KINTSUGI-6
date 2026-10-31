import json
import subprocess
import sys
from pathlib import Path

from cubesat.canon import canonical_log_hash

ROOT = Path(__file__).resolve().parents[1]

# Canonical golden SHA-256 of the short-run JSONL (nominal.json with duration_s = 600.0,
# seed 42), pinned per docs/MASTER_PROMPT.md section 3.8.
# Cross-platform pin: cubesat.canon.canonical_log_hash (floats zeroed below 1e-6,
# else 5 significant digits); pinned on macOS arm64, 2026-10-31.
GOLDEN_NOMINAL_SHORT_CANONICAL_SHA256 = (
    "64b88c46843f99cdeaff654c4eccef1bf9e94e500d5171b236c17ce9d8def3a8"
)


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
    hash (cubesat.canon.canonical_log_hash)."""
    scenario = _short_nominal_scenario(tmp_path / "nominal_short.json")
    out = tmp_path / "run.jsonl"
    result = _run_cli(scenario, out)
    assert result.returncode == 0, result.stderr
    raw_bytes = out.read_bytes()
    digest = canonical_log_hash(raw_bytes)
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
