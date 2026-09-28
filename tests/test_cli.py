import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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
