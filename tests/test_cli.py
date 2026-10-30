import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Golden SHA-256 of the short-run JSONL (nominal.json with duration_s = 600.0,
# seed 42), pinned per docs/MASTER_PROMPT.md section 3.8 ("nominal.json short run
# compares against a committed golden hash"). Any change to the sim, the log
# schema, or nominal.json itself changes this hash and must be acknowledged here.
GOLDEN_NOMINAL_SHORT_SHA256_MAP = {
    "win32": "c95f31b872b9134db57c43763d3bc67bb1e42c056beb7378c5177172758696f6",
    "linux": "5eb0614ddfdf2df252033bc87e7421cb8eb84988e404b9c9f0b1a03978a3c5d6",  # Linux glibc pin
}
GOLDEN_NOMINAL_SHORT_SHA256 = GOLDEN_NOMINAL_SHORT_SHA256_MAP.get(
    sys.platform, GOLDEN_NOMINAL_SHORT_SHA256_MAP["win32"]
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
    """Two runs of a short nominal scenario produce byte-identical JSONL, matching the
    committed golden SHA-256 (docs/MASTER_PROMPT.md sections 3.5 and 3.8: same scenario +
    seed => byte-identical log; regression vs golden hash)."""
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
    digest = hashlib.sha256(first).hexdigest()
    assert digest == GOLDEN_NOMINAL_SHORT_SHA256, (
        f"golden hash mismatch: got {digest}"
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
