"""FastAPI app (BACKEND_SPEC v1.1 sections 5.4, 6.3, 7.1, 7.2, 7.3).

H2: enriched /health, /scenarios, /replay/files, /replay/file/{filename} with
the traversal guard and the CUBESAT_LOG_DIR override. H3/H4: the per-process
Session + Hub (lifespan), WS /ws/state (hello -> snapshot -> reader/writer),
/simulation/*, /failure/inject and the /replay/* control routes. The session
layer holds all state; routes only map SessionError -> HTTP (section 7.1).
G5 console addition: POST /scenarios/upload saves a user-authored scenario
(sanitized name, no overwrites, validated with the real Scenario loader) so
/simulation/start can run it by file name.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from cubesat import __version__
from cubesat.replay import list_logs
from cubesat.scenario import Scenario
from cubesat.session import Hub, Session, SessionError
from cubesat.wire import (
    InjectRequest,
    ReplayLoadRequest,
    SeekRequest,
    SpeedRequest,
    StartRequest,
)

# WS emit-cadence cap (section 10); tests monkeypatch this to 0 to neutralize
# decimation deterministically.
_MIN_EMIT_INTERVAL = 1.0 / 30.0

_state: AppState | None = None


def get_state() -> AppState:
    """The one per-process Session + Hub (section 9.1). Created by the lifespan
    under uvicorn; lazily under bare TestClient (which never runs lifespan)."""
    global _state
    if _state is None:
        hub = Hub()
        _state = AppState(
            hub=hub,
            session=Session(
                scenarios_dir(), log_dir(), hub, min_emit_interval=_MIN_EMIT_INTERVAL
            ),
        )
    return _state


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_state()  # one Session + Hub per process (section 5.4)
    yield
    global _state
    _state = None


app = FastAPI(title="cubesat-swarm", version=__version__, lifespan=lifespan)


@dataclass
class AppState:
    hub: Hub
    session: Session


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
    # Enriched per section 5.4. INTENTIONAL CONTRACT CHANGE vs the G0
    # {"status": "ok"} -- tests/test_smoke.py updated in the same commit.
    # NOTE: the active recovery policy is deliberately NOT exposed here --
    # tests/test_smoke.py:19 pins the exact /health key set (and that file is
    # outside this change's ownership); the policy is carried by
    # POST /simulation/start, the WS hello and (on deviation) sim_state.
    state = _state
    if state is None:
        return {"status": "ok", "mode": "stopped", "sim_time": None,
                "scenario": None, "paused": False}
    session = state.session
    return {
        "status": "ok",
        "mode": session.mode,
        "sim_time": session.sim_time,
        "scenario": session.enrich.scenario,
        "paused": session.paused,
    }


def _scenario_listing(directory: Path) -> list[str]:
    """Sorted .json names in a scenarios dir; [] never 500 (section 7.1)."""
    if not directory.is_dir():
        return []
    return sorted(p.name for p in directory.iterdir() if p.is_file() and p.suffix == ".json")


@app.get("/scenarios")
def scenarios() -> dict:
    return {"scenarios": _scenario_listing(scenarios_dir())}  # [] never 500 (section 7.1)


# ---- G5 console addition: scenario upload --------------------------------
# Not in BACKEND_SPEC v1.1: lets the console save a user-authored scenario so
# POST /simulation/start can run it by file name. The request model lives here
# rather than wire.py because the session layer never sees it -- the scenarios
# directory is the contract.


class UploadRequest(BaseModel):
    name: str | None = None  # sanitized to [A-Za-z0-9_-]; absent -> "custom"
    scenario: dict


def _sanitize_scenario_name(name: str | None) -> str:
    """Keep [A-Za-z0-9_-] only -- no path separators survive, so the upload is
    traversal-safe by construction. Absent -> "custom"; a name that sanitizes
    to empty (or exceeds 64 chars, keeping filenames well under OS limits) -> 422."""
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "", name) if name is not None else ""
    if not cleaned:
        if name is None:
            return "custom"
        raise HTTPException(
            status_code=422, detail="scenario name is empty after sanitizing to [A-Za-z0-9_-]"
        )
    if len(cleaned) > 64:
        raise HTTPException(status_code=422, detail="scenario name exceeds 64 characters")
    return cleaned


@app.post("/scenarios/upload")
def scenarios_upload(req: UploadRequest) -> dict:
    """Save a console-authored scenario into the scenarios dir. Overwrites are
    refused (the committed scenarios are protected) and the payload goes through
    the same parse path as load_scenario, so an accepted file always starts."""
    name = _sanitize_scenario_name(req.name)
    directory = scenarios_dir()
    base = directory.resolve()
    candidate = (base / f"{name}.json").resolve()
    # Unreachable while the name is sanitized -- kept as the explicit guard.
    if base not in candidate.parents:
        raise HTTPException(
            status_code=422, detail="scenario name escapes the scenarios directory"
        )
    if candidate.exists():
        raise HTTPException(
            status_code=409,
            detail=f"scenario already exists: {candidate.name}; pick another name",
        )
    try:
        # model_validate_json on exactly the bytes we are about to write, so
        # what was validated is what load_scenario will parse at start time.
        Scenario.model_validate_json(json.dumps(req.scenario))
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=f"invalid scenario: {exc}") from None
    directory.mkdir(parents=True, exist_ok=True)  # only after every check passed
    candidate.write_text(
        json.dumps(req.scenario, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {"status": "saved", "filename": candidate.name,
            "scenarios": _scenario_listing(directory)}


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


def _run(coro):  # noqa: ANN001 -- tiny route-helper, keeps error mapping in one place
    """Await a session coroutine, mapping SessionError -> HTTP (section 7.1)."""

    async def call():
        try:
            return await coro
        except SessionError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None

    return call


@app.post("/simulation/start")
async def simulation_start(req: StartRequest) -> dict:
    session = get_state().session
    await _run(session.start_live(req.scenario, req.seed, req.speed, req.policy, req.predictor))()
    # "predictor" echoes the RESOLVED state (display-only risk map installed?),
    # not the requested flag: requested-but-failed -> False + the warning event.
    return {"status": "started", "mode": session.mode, "scenario": session.enrich.scenario,
            "seed": session.enrich.seed, "speed": session.speed,
            "policy": session.enrich.policy, "predictor": session.predictor_active}


@app.post("/simulation/pause")
async def simulation_pause() -> dict:
    session = get_state().session
    await _run(session.pause())()
    return {"status": "paused", "mode": session.mode, "paused": session.paused}


@app.post("/simulation/resume")
async def simulation_resume() -> dict:
    session = get_state().session
    await _run(session.resume())()
    return {"status": "resumed", "mode": session.mode, "paused": session.paused}


@app.post("/simulation/speed")
async def simulation_speed(req: SpeedRequest) -> dict:
    session = get_state().session
    await _run(session.set_speed(req.speed))()
    return {"status": "ok", "mode": session.mode, "speed": session.speed}


@app.post("/simulation/reset")
async def simulation_reset() -> dict:
    session = get_state().session
    await session.reset()
    return {"status": "reset", "mode": session.mode}


@app.post("/failure/inject")
async def failure_inject(req: InjectRequest) -> dict:
    session = get_state().session
    await _run(session.inject_failure(req.sat_id, req.mode, req.degrade_s))()
    return {"status": "injected", "mode": session.mode, "sim_time": session.sim_time,
            "injected": {"sat_id": req.sat_id, "mode": req.mode}}


@app.post("/replay/load")
async def replay_load(req: ReplayLoadRequest) -> dict:
    session = get_state().session
    skipped = await _run(session.load_replay(req.filename, req.speed, req.predictor))()
    return {"status": "loaded", "filename": req.filename, "skipped": skipped,
            "mode": session.mode, "predictor": session.predictor_active}


@app.post("/replay/pause")
async def replay_pause() -> dict:
    session = get_state().session
    await _run(session.pause())()
    return {"status": "paused", "mode": session.mode, "paused": session.paused}


@app.post("/replay/resume")
async def replay_resume() -> dict:
    session = get_state().session
    await _run(session.resume())()
    return {"status": "resumed", "mode": session.mode, "paused": session.paused}


@app.post("/replay/seek")
async def replay_seek(req: SeekRequest) -> dict:
    session = get_state().session
    await _run(session.seek(req.t))()
    return {"status": "ok", "mode": session.mode, "sim_time": session.sim_time}


@app.post("/replay/speed")
async def replay_speed(req: SpeedRequest) -> dict:
    session = get_state().session
    await _run(session.set_speed(req.speed))()
    return {"status": "ok", "mode": session.mode, "speed": session.speed}


@app.post("/replay/stop")
async def replay_stop() -> dict:
    session = get_state().session
    await session.reset()
    return {"status": "stopped", "mode": session.mode}


@app.websocket("/ws/state")
async def ws_state(ws: WebSocket) -> None:
    """Section 6.3: accept -> hello -> snapshot -> reader/writer tasks; ping ->
    pong; disconnect cancels both tasks and unsubscribes -- the driver and the
    other clients never notice."""
    await ws.accept()
    state = get_state()
    queue = state.hub.subscribe()
    reader: asyncio.Task | None = None
    writer: asyncio.Task | None = None
    try:
        await ws.send_json(state.session.hello())
        await ws.send_json(state.session.snapshot())

        async def read_loop() -> None:
            while True:
                msg = await ws.receive_json()
                if isinstance(msg, dict) and msg.get("type") == "ping":
                    await ws.send_json({"type": "pong"})
                # anything else ignored (section 6.3)

        async def write_loop() -> None:
            while True:
                msg = await queue.get()
                await ws.send_json(msg)

        reader = asyncio.create_task(read_loop())
        writer = asyncio.create_task(write_loop())
        done, _ = await asyncio.wait({reader, writer}, return_when=asyncio.FIRST_COMPLETED)
        for task in done:  # surface the real failure (disconnect, send error, ...)
            exc = task.exception()
            if exc is not None:
                raise exc
    except (WebSocketDisconnect, RuntimeError):
        pass  # quiet disconnect (section 13)
    finally:
        for task in (reader, writer):
            if task is not None and not task.done():
                task.cancel()
        state.hub.unsubscribe(queue)


# ---- LAST: static frontend (section 8.1) --------------------------------
# Registered after every API + WS route above, so the API keeps precedence.

DIST_DIR = _REPO_ROOT / "frontend" / "dist"


def mount_static(target: FastAPI, dist_dir: Path) -> bool:
    """Section 8.1: if frontend/dist exists, serve it at / with html=True (one
    process serves API + WS + UI -- the locked deploy shape). Otherwise / is a
    JSON placeholder: the backend never requires the frontend and API-only
    mode never crashes. Returns whether the mount happened."""
    if dist_dir.is_dir():
        target.mount("/", StaticFiles(directory=dist_dir, html=True), name="frontend")
        return True

    @target.get("/", include_in_schema=False)
    def frontend_placeholder() -> dict:
        return {"error": "frontend not built"}

    return False


mount_static(app, DIST_DIR)
