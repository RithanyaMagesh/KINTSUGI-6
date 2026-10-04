"""Gate 0 seal tests for the user-supplied predictor bundle (INTEGRATION_PROMPT Phase 0).

The pipeline source is FROZEN: out2/test_manifest.json pins its sha256 and the
pipeline's own `run` refuses to execute if the file changes ("DO NOT EDIT IT").
The model artifact is pinned by models/predictor_manifest.json. CI verifies
these hashes and never retrains (INTEGRATION_PROMPT rules / ENDGAME_PLAN 7).
"""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_pipeline_source_sealed():
    manifest = json.loads(
        (ROOT / "out2" / "test_manifest.json").read_text(encoding="utf-8")
    )
    assert _sha256(ROOT / "files" / "predictor_pipeline.py") == manifest["src_sha256"], (
        "files/predictor_pipeline.py no longer matches the sealed manifest -- the frozen "
        "bundle was modified, so `run` will refuse and the sealed-test claim is void"
    )


def test_model_artifact_sha_matches_manifest():
    manifest = json.loads(
        (ROOT / "models" / "predictor_manifest.json").read_text(encoding="utf-8")
    )
    assert _sha256(ROOT / "models" / "predictor.txt") == manifest["model_sha256"], (
        "models/predictor.txt does not match its manifest -- the shipped model is not "
        "the one the sealed run produced"
    )
