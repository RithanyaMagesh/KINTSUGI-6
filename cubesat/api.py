"""FastAPI app (BACKEND_SPEC v1.1 sections 5.4, 6.3, 7.1, 7.2, 7.3).

H2: enriched /health, /scenarios, /replay/files, /replay/file/{filename} with
the traversal guard and the CUBESAT_LOG_DIR override. H3/H4: the per-process
Session + Hub (lifespan), WS /ws/state (hello -> snapshot -> reader/writer),
/simulation/*, /failure/inject and the /replay/* control routes. The session
layer holds all state; routes only map SessionError -> HTTP (section 7.1).
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from cubesat import __version__
from cubesat.replay import list_logs
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
    await _run(session.start_live(req.scenario, req.seed, req.speed))()
    return {"status": "started", "mode": session.mode, "scenario": session.enrich.scenario,
            "seed": session.enrich.seed, "speed": session.speed}


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
    await _run(session.inject_failure(req.sat_id, req.mode))()
    return {"status": "injected", "mode": session.mode, "sim_time": session.sim_time,
            "injected": {"sat_id": req.sat_id, "mode": req.mode}}


@app.post("/replay/load")
async def replay_load(req: ReplayLoadRequest) -> dict:
    session = get_state().session
    skipped = await _run(session.load_replay(req.filename, req.speed))()
    return {"status": "loaded", "filename": req.filename, "skipped": skipped,
            "mode": session.mode}


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
