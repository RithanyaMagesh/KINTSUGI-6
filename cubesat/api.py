"""FastAPI app. H2 (BACKEND_SPEC v1.1 sections 5.4, 7.2, 7.3): enriched /health,
/scenarios, /replay/files, /replay/file/{filename} with the section 7.2 traversal
guard and the CUBESAT_LOG_DIR override -- zero sim calls in this layer. The WS
endpoint and /simulation/* + /failure/* routes arrive in H3/H4 (sections 5.3-5.4).
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from cubesat import __version__
from cubesat.replay import list_logs

app = FastAPI(title="cubesat-swarm", version=__version__)

_REPO_ROOT = Path(__file__).resolve().parents[1]


def log_dir() -> Path:
    """Resolved log directory; CUBESAT_LOG_DIR overrides (section 7.3 -- the G6
    container needs this because data/logs is gitignored)."""
    override = os.environ.get("CUBESAT_LOG_DIR")
    return Path(override) if override else _REPO_ROOT / "data" / "logs"


def scenarios_dir() -> Path:
    return _REPO_ROOT / "data" / "scenarios"


@app.get("/health")
def health() -> dict:
    # Enriched per section 5.4. H2 has no Session yet (H3 wires it), so the
    # stopped defaults are reported; INTENTIONAL CONTRACT CHANGE vs the G0
    # {"status": "ok"} -- tests/test_smoke.py updated in the same commit.
    return {
        "status": "ok",
        "mode": "stopped",
        "sim_time": None,
        "scenario": None,
        "paused": False,
    }


@app.get("/scenarios")
def scenarios() -> dict:
    directory = scenarios_dir()
    listing: list[str] = []
    if directory.is_dir():
        listing = sorted(p.name for p in directory.iterdir() if p.is_file() and p.suffix == ".json")
    return {"scenarios": listing}  # [] never 500 (section 7.1)


@app.get("/replay/files")
def replay_files() -> dict:
    return {"files": list_logs(log_dir())}


@app.get("/replay/file/{filename}")
def replay_file(filename: str) -> FileResponse:
    """Section 7.2 traversal guard: strip to the basename, resolve inside the
    log dir, else 404."""
    base = log_dir().resolve()
    candidate = (base / Path(filename).name).resolve()
    if base not in candidate.parents or not candidate.is_file():
        raise HTTPException(status_code=404, detail="replay file not found")
    return FileResponse(candidate)
