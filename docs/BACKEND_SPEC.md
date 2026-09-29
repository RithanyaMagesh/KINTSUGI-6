# CubeSat Self-Healing Swarm — Backend Specification (G5)

**Project:** CubeSat Swarm Self-Healing Formation Control After Partial Failure  
**Document Type:** Backend Requirements, Architecture Blueprint, and Acceptance Criteria  
**Version:** 1.0  
**Status:** Approved — build against this  
**Primary Audience:** The G5 implementer (backend + integration)  
**Primary Goal:** Ship the FastAPI backend that streams the sim live and from replay, serves the built React frontend, and passes gate G5: **runs locally live AND from replay**.

---

## 0. Authority and reading order

This document details **gate G5 only**. Precedence if rules conflict:

1. Repo invariants — `AGENTS.md` (determinism, SI units, no fabricated numbers, no new deps without asking)
2. `docs/MASTER_PROMPT.md` — locked decisions (§2), log schema (§5), gates (§6), research patches (final section)
3. `docs/FRONTEND_SPEC.md` v2.0 — **§15–§18 are the normative wire contract.** This spec implements it; if the two documents ever disagree on the wire format, stop and fix both — never fork silently
4. This document

**The sim core is DONE (G1–G4 all PASS) and you must not modify it.** G5 wraps it. Touching `cubesat/sim.py`, `hcw.py`, `pd.py`, `coverage.py`, or `allocate.py` risks the golden-hash determinism test and is out of scope for G5. If you believe a sim change is unavoidable: stop, report, wait.

**Reading order:** §1 (what G5 must prove) → §6 (wire contract) → §5 (architecture) → §4 (what exists) → the rest.

---

## 1. What G5 must prove (gate pass criteria)

| # | Criterion | Proof |
|---|---|---|
| 1 | Runs **live**: scenario starts over REST, WS streams the sim in the frontend contract schema | WS integration test + manual run |
| 2 | Runs **from replay**: committed JSONL logs stream over the same WS path, with play/pause/seek/speed | WS integration test + manual run |
| 3 | Live and replay are the **same pipeline** (one wire path — no schema drift) | `test_live_equals_replay_frames` |
| 4 | Determinism is untouched by the server: same scenario + seed ⇒ byte-identical log; failure injection recomputes a **byte-identical prefix** | existing golden-hash test still green + `test_inject_prefix_byte_identical` |
| 5 | The FastAPI service serves API + WS + the built frontend (`frontend/dist`) from one process | static-mount test + local run |
| 6 | `/health` works as Docker healthcheck and demo warm-up | container run (daemon permitting) + curl |
| 7 | `uv run ruff check .` and `uv run pytest -q` fully green, small diffs, one commit series | repo protocol |
| 8 | GATES.md G5 row updated with evidence + measured numbers | gate protocol |

Out of G5 scope (later gates): real deployment (G6), README/pitch numbers (G7). G5 proves everything on `localhost:8000`.

---

## 2. Division of labor and operating rules

- **You own G5**: everything in this spec + integration with the frontend (which follows `docs/FRONTEND_SPEC.md` v2.0).
- **G6 (deploy: Render/Fly + static mirror) and G7 (README/pitch) are handled separately** — design so they stay easy: `CUBESAT_LOG_DIR` env override, static files from `frontend/dist`, healthcheck on `/health`.
- **Gate protocol** (AGENTS.md): tests first, one gate per session, update `GATES.md`, tag `gate-5-pass` only when everything is green. If a test cannot pass in the time-box: stop, report failure + 2 options with tradeoffs.
- **No new runtime dependencies.** Locked stack: `fastapi`, `uvicorn`, `pydantic` (v2), `numpy`, `scipy` — all already in `pyproject.toml`. Dev: `httpx` (TestClient). If you think you need something else, ask first.
- **Invariant #1 (no fabricated numbers):** any metric the backend cannot measure ships as `null`; the frontend renders `unmeasured`. Never invent a latency.
- **Invariant #3 (SI at the wire):** WS messages carry meters, seconds, m/s. The frontend converts for display.

---

## 3. Current state (the terrain, verified 2026-09-28)

**Exists and is green (do not touch):**

- `cubesat/sim.py` — the pure core: `run_scenario(scenario: Scenario) -> list[dict]` returns **all** log lines in one call (INIT header → tick lines → SUMMARY). A full `two_failure` run computes in ~1–2 s. Log schema v1: `{"v", "t", "state", "sats": [{"id", "role", "status", "r", "v", "dv_used"}], "coverage", "min_sep", "event?"}`. State constants: `INIT, NOMINAL, FAILURE_DETECTED, REPLANNING, RECONFIGURING, RECOVERED, SUMMARY`. Sat statuses: `NOMINAL, DEAD, THRUSTER_OUT`. Events include `FAILURE_DETECTED` and `ASSIGNMENT` payloads. SUMMARY carries `coverage_mean_last_orbit`.
- `cubesat/scenario.py` — pydantic v2 `Scenario` (+ `Failure(t, sat_id, mode)`, `FailureMode {DEAD, THRUSTER_OUT}`), `load_scenario(path)`.
- `cubesat/allocate.py` — `replan(...)` already computes the cost matrix internally; `solve_assignment` (Hungarian + greedy fallback).
- `cubesat/run.py` — CLI; JSONL convention `json.dumps(line, sort_keys=True)`.
- `cubesat/api.py` — **G0 skeleton only**: `app = FastAPI(...)` with one route, `GET /health -> {"status": "ok"}`.
- `tests/` — 30 tests across 8 files, including the golden-hash `test_run_is_byte_deterministic` and `tests/test_smoke.py::test_health_endpoint` (asserts `TestClient(app).get("/health") == {"status": "ok"}` — you will extend this response, so **update this test in the same commit**, see §8.1).
- `data/scenarios/nominal.json` (5676 s, dt 2 s, 6 sats, 11 km slots, FOV 1.5°) and `two_failure.jsonl`-producing `two_failure.json` (failures: SAT-1 DEAD @1200 s, SAT-2 DEAD @1500 s).
- `data/logs/*.jsonl` exist locally (e.g. `two_failure.jsonl`, 8517 lines) but **`data/logs` is gitignored**.

**Missing (this is G5):** every REST route beyond `/health`; all WebSocket code; replay loading/seek; the session/driver; static mounting; a Dockerfile (only `.dockerignore` exists — G0's Dockerfile was never committed); `frontend/dist` (the frontend build arrives separately — everything must work without it).

**Pre-flight chores (first 15 min):**
1. `uv sync --locked`, `uv run pytest -q` — confirm 30 green before touching anything.
2. `pyproject.toml` dev group pins `httpx2>=2.13.1` alongside `httpx` — verify that is intentional; TestClient needs only `httpx`. If `httpx2` is junk, propose removing it (ask, don't silently drop).
3. Note: no CI config exists in the repo. Out of G5 scope; flag as an open risk in GATES.md, don't build it.

---

## 4. Architecture — one streaming pipeline, two frame sources

The decisive fact: `run_scenario` is pure and returns the whole run at once. So the server **does not wrap an incremental step loop** — it runs the scenario once, then streams frames through a cursor. Live and replay become the same cursor-over-frames pipeline:

```
  LIVE                               REPLAY
  Scenario JSON                      data/logs/*.jsonl  (committed)
      |                                      |
      v                                      v
  asyncio.to_thread(                    ReplaySource
    run_scenario(scenario))             ReplayLog.frames[] + times[]
      |  all lines (~3-9k dicts)                |
      v                                         |
  LiveSource  (lines[], cursor,                 |
   assignment_map, last event payloads)         |
      |                                         |
      +-------------------+---------------------+
                          v
                 Session._driver  (asyncio task — the ONLY pacing loop)
                 wall_emit = anchor + (t_frame - t_anchor)/speed
                 emit if wall >= 1/30 s  OR  the line carries an event
                          |
                  wire.to_messages(line, enrich)     <- the ONLY wire-format code
                          |
                   Hub.publish(msg)   (sync, never blocks; drop-oldest sim_state)
                          |
        +-----------------+------------------+
        v                 v                  v
   client queue      client queue      late joiner:
   (asyncio.Q,128)   (asyncio.Q,128)   hello + snapshot() first
        |                 |
   writer task       writer task      reader task: recv {"type":"ping"}
   -> ws.send_json   -> ws.send_json    -> send {"type":"pong"}

  REST /simulation/*, /replay/*, /failure/inject  ->  Session methods
  (pause/resume/speed/seek/inject mutate cursor/anchor/source only)
```

Consequences (all four are load-bearing):

1. **Determinism is structurally safe.** The sim runs in a worker thread touching no shared state; the server never writes logs; sim time in every message comes from the frame's `t`, never from wall-clock.
2. **Failure injection = recompute.** `inject` stops the driver, builds an augmented scenario (`scenario.model_copy(update={"failures": sorted(failures + [Failure(t=t_now, sat_id=..., mode=...)])})`), reruns `run_scenario`, and re-anchors the cursor at `t_now`. Because the core is pure and the only change is a failure scheduled at `t_now`, **the recomputed prefix is byte-identical** to what already streamed — provable by test, zero sim.py diff. Cost ≈ one full run (~1–2 s): broadcast an `event` ("Recomputing trajectory with new failure…") before the gap.
3. **Replay reuses the entire driver** — only the frame source differs. Live-vs-replay schema drift is structurally impossible.
4. **Slow clients can never stall the demo.** `Hub.publish` is a synchronous O(1) queue append; a full queue drops oldest `sim_state` frames but never drops `event` / `role_reassignment` / `hello` messages (the story must survive).

---

## 5. Module blueprint

Four pieces. Three new modules, one rewritten. No other files change. Keep every file ≤ ~300 lines (repo style rule).

### 5.1 `cubesat/wire.py` (new, ~150 lines) — the single wire-format authority

Every log-line → WS-message decision lives here and nowhere else.

```python
def display_sat_id(i: int) -> str                     # 0-based log id -> "SAT-{i+1}"
def to_sim_state(frame: dict, enrich: SessionEnrich) -> dict
    # -> {"type": "sim_state", "sim_time", "state", "scenario", "seed",
    #     "sats": [{"id","role","status","r","v","dv_used","target_slot?","failure_type?"}],
    #     "coverage", "min_sep", "metrics": {"detection_latency_s": ..., "replanning_latency_ms": ...}}
def to_messages(frame: dict, enrich: SessionEnrich) -> list[dict]
    # one log line -> [sim_state, (event?), (role_reassignment?), (cost_matrix? — flag-gated, see §7.3)]
def to_event(level: str, sim_time: float, message: str) -> dict
class StartRequest(BaseModel):    scenario: str | None; seed: int | None; speed: float = 100.0
class InjectRequest(BaseModel):   sat_id: str; mode: Literal["DEAD", "THRUSTER_OUT"] = "DEAD"
class SeekRequest(BaseModel):     t: float
class SpeedRequest(BaseModel):    speed: float
```

`SessionEnrich` carries per-session context the log lines lack: `scenario` name, `seed`, the `assignment_map` (sat id → `"slot_{i}"`, rebuilt from `ASSIGNMENT` events), and the latest `detection_latency_s` / `replanning_latency_ms`.

### 5.2 `cubesat/replay.py` (new, ~110 lines) — no sim dependency; build FIRST

```python
@dataclass
class ReplayLog:
    frames: list[dict]      # tick lines only (INIT header and SUMMARY stored separately)
    times: list[float]      # parallel array of t values (for bisect)
    header: dict | None     # the INIT line (scenario, seed, n_sats)
    summary: dict | None    # the SUMMARY line (coverage_mean_last_orbit)
    skipped: int            # count of unparseable lines

def load_jsonl(path: Path) -> ReplayLog     # per-line defensive parse: bad line -> skip + count
def index_at(log: ReplayLog, t: float) -> int   # bisect on times -> cursor for seek
def list_logs(log_dir: Path) -> list[str]       # sorted *.jsonl basenames
```

### 5.3 `cubesat/session.py` (new, ~290 lines) — all state and concurrency, **zero FastAPI imports** (unit-testable without HTTP)

```python
class Hub:
    def subscribe(self) -> asyncio.Queue          # maxsize=128
    def unsubscribe(self, q: asyncio.Queue) -> None
    def publish(self, msg: dict) -> None          # sync, O(1); full queue drops oldest sim_state only

class LiveSource:
    def __init__(self, scenario: Scenario, lines: list[dict]) -> None
    @classmethod
    def with_failure(cls, base: Scenario, sat_display_id: str, mode: str, t_now: float) -> "LiveSource"
    # builds scenario.model_copy(update={"failures": sorted(...)}), reruns the core in a thread

class ReplaySource:
    def __init__(self, log: ReplayLog) -> None    # cursor + times; seek/speed handled by Session

class Session:
    mode: Literal["stopped", "live", "replay"]
    paused: bool
    speed: float                                  # default 100.0 (master prompt: ~100x)
    async def start_live(self, scenario_name: str | None, seed: int | None, speed: float) -> None
    async def load_replay(self, filename: str, speed: float) -> None
    async def pause(self) -> None; async def resume(self) -> None
    async def reset(self) -> None                 # -> mode "stopped", driver cancelled
    async def set_speed(self, x: float) -> None
    async def seek(self, t: float) -> None        # replay only
    async def inject_failure(self, sat_display_id: str, mode: str) -> None   # live only
    def snapshot(self) -> dict                    # current sim_state, for WS hello / late joiners
```

### 5.4 `cubesat/api.py` (rewrite of the G0 skeleton, ~250 lines)

```python
app = FastAPI(lifespan=lifespan)      # lifespan creates Session + Hub (one per process)

GET  /health                  -> {"status": "ok", "mode": ..., "sim_time": ..., "scenario": ..., "paused": ...}
GET  /scenarios               -> {"scenarios": ["nominal.json", "two_failure.json"]}   # directory listing; [] never 500
POST /api/scenario/from-cluster  # OPTIONAL / bonus — NOT in the G5 cut list; see the dated note below this table
POST /simulation/start        # StartRequest; default = first sorted scenario, its own seed; 409 if none
POST /simulation/pause        # 409 when stopped
POST /simulation/resume       # 409 when stopped
POST /simulation/speed        # SpeedRequest; 409 when stopped
POST /simulation/reset        # always allowed; -> stopped
POST /failure/inject          # InjectRequest; 409: not live / run finished / unknown sat / already failed
GET  /replay/files            -> {"files": [...]}                                      # [] when none
GET  /replay/file/{filename}  -> FileResponse        # traversal guard: Path(name).name, resolve() inside log dir
POST /replay/load             # {filename, speed?}; 404 unknown; 200 with skipped==N + warning event for bad lines
POST /replay/pause | /replay/resume | /replay/seek | /replay/speed | /replay/stop
WS   /ws/state                # §7.4
# LAST route: if frontend/dist exists -> app.mount("/", StaticFiles(html=True)); else "/" returns
# a JSON placeholder {"error": "frontend not built"} — API-only mode must never crash
```

**`POST /api/scenario/from-cluster` — OPTIONAL / bonus, not in the G5 cut list (2026-09-28, cluster-import feature).** Build it only after every mandatory route above is green. Body: `{"omm": <one OMM JSON record>, "n_sats": ..., "n_failures": ...}` or a chief object `{name, norad_cat_id, mean_motion_rad_s, altitude_km, eccentricity}`; the route wraps `cubesat.cluster_import.build_swarm_scenario` and returns the generated scenario JSON. **No network fetch in-process.** A live CelesTrak fetch stays a separate user-approval decision: python-sgp4 would be a NEW dependency, and the fetch itself must be host-validated and SSRF-guarded (http/https only; reject localhost, loopback, private and reserved hosts) with a cache and the committed snapshot as fallback — `data/celestrak/firefly_omm.json` is that fallback. State plainly: the demo is the CLI (`uv run python -m cubesat.cluster_import ...`) plus the committed `data/scenarios/firefly_swarm.json` — not this route.

Run exactly as AGENTS.md says: `uv run uvicorn cubesat.api:app --port 8000`. **Single worker, always** (`Session` is per-process; never `--workers N`).

---

## 6. Wire contract (normative implementation of FRONTEND_SPEC §16)

### 6.1 Log-line → message normalization

The log schema and the frontend contract differ in three places. The mapping below is the contract — implement it once in `wire.py`, pin it with a golden test against a real `two_failure.jsonl` line, and never special-case anywhere else:

| Log field | WS field | Rule |
|---|---|---|
| `id: 0` (int) | `id: "SAT-1"` | `display_sat_id`: 0-based int → 1-based string |
| `status: "NOMINAL"` | `status: "healthy"` | healthy |
| `status: "DEAD"` / `"THRUSTER_OUT"` | `status: "failed"` + `failure_type` preserved | dead sats coast; frontend draws them red+label |
| `state: "INIT"` (header) | first `sim_state` with `state: "NOMINAL"`, empty `sats` | drives frontend §24.3 empty state |
| `state: "SUMMARY"` | final `event` ("Run complete") + hold last frame | SUMMARY is never sent as a sim_state |
| `sats[].r`, `sats[].v` | same names, same SI units | no conversion at this boundary |
| `coverage`, `min_sep` | same names, top level | 0–1 fraction, meters |
| `event: {type: "FAILURE_DETECTED", ...}` | `event` message + `metrics.detection_latency_s` | latency = t_detect − t_fail **only if the payload carries both timestamps** (verify the actual payload keys in `sim.py` when wiring; otherwise ship `null` → frontend renders "unmeasured") |
| `event: {type: "ASSIGNMENT", ...}` | `role_reassignment` (§16.3 of FRONTEND_SPEC) + updates `assignment_map` | map the payload fields that exist; omit what doesn't — do not invent costs |

**Deliberate cuts (record in the PR, don't "fix" them):**

- **`cost_matrix` message: OFF.** `allocate.replan` computes the matrix internally but `run_scenario` does not expose it. Exposing it means touching sim.py (forbidden for G5). Ship `role_reassignment` only; the frontend's cost-matrix viewer stays a should-have fed by that message, or is cut with the frontend's cut order.
- **`replanning_latency_ms`: `null`** unless a future sim hook provides it out-of-band without touching the byte stream. Frontend renders "unmeasured".
- **Satellite-level `reconfiguring` / `recovered` statuses are frontend-derived** (from mission state + `target_slot` + position). The backend only reports the three statuses the log actually carries. This keeps the backend honest to the log.

### 6.2 Message set (see FRONTEND_SPEC §16 for exact shapes)

`hello` (server→client, on connect: mode, scenario, seed, sim_time, skipped) · `sim_state` · `event` · `role_reassignment` · `ping` (client→server) · `pong` (server→client). `cost_matrix`: defined in the frontend spec, disabled in G5.

### 6.3 WS lifecycle (`/ws/state`)

1. Accept → send `hello` → send `snapshot()` (a current `sim_state`, or the empty-state `sim_state` from the INIT mapping when nothing has run).
2. Spawn two tasks per connection: **reader** (`receive_json`; `{"type":"ping"}` → send `{"type":"pong"}`; anything else ignored) and **writer** (drains its Hub queue → `send_json`).
3. Disconnect (exception or send failure) → cancel both tasks, `hub.unsubscribe(q)`. The driver never notices; other clients unaffected.
4. Run end (SUMMARY): final event, driver idles holding the last frame; the connection stays open for pings.

The client-side 30 s ping (FRONTEND_SPEC §16.5) keeps Render's free tier alive — the server's only job is to answer `pong` and never close idle connections.

---

## 7. REST contract details

### 7.1 Error semantics (maps to FRONTEND_SPEC §20/§24 — the frontend's UX depends on exactly these)

| Frontend state | Backend behavior |
|---|---|
| "Waiting for simulation data" (§20.3) | WS connected, nothing run: `hello` + empty-state `sim_state` |
| No scenario available (§24.1) | `GET /scenarios` → `{"scenarios": []}` (200, never 500); `POST /simulation/start` → 409 |
| Simulation stopped (§24.2) | any `/simulation/*` except start/reset → 409 `{"detail": "no simulation running"}` |
| Replay not loaded (§24.5) | `GET /replay/files` → `{"files": []}`; unknown file → 404 |
| Corrupt replay file | `POST /replay/load` → 200 with `skipped: N`; if zero good frames, broadcast a critical `event` |
| Bad inject | 409 with reason: not live / run finished / unknown sat / sat already failed |
| Sim compute timeout | `asyncio.wait_for(..., timeout=60)` → 504 on start + critical `event` on WS; session → stopped |

### 7.2 Path safety

`GET /replay/file/{filename}` serves only files inside the resolved log directory: strip to `Path(filename).name`, `resolve()`, verify the result is inside the dir, else 404. Test it (`../` traversal, absolute paths).

### 7.3 Log directory and committed logs

- Resolve `data/logs` relative to the repo root; allow `CUBESAT_LOG_DIR` env override (G6's container needs this — `data/logs` is gitignored).
- **Commit the canonical demo logs** so a fresh clone can replay immediately (master prompt §3.7 requires committed replays): add `.gitignore` exceptions for `data/logs/nominal.jsonl` and `data/logs/two_failure.jsonl`, regenerate them with the exact run commands from AGENTS.md, and commit them in the G5 series. Verify the golden-hash test still passes after regeneration.

### 7.4 Replay: server driver AND raw file, with clear roles

- **Server replay driver (canonical demo path):** `POST /replay/load` → frames stream over WS through the same pipeline as live. This is what proves gate criterion "runs from replay" and what the frontend uses whenever the backend is reachable.
- **Raw file endpoint (`GET /replay/file/{filename}`):** exists for the **G6 static mirror** (frontend replays client-side with no backend) and as frontend dev/test fixtures. Both paths parse the same schema (FRONTEND_SPEC §18), so drift is impossible.

---

## 8. Static serving, Docker, dev proxy

### 8.1 Static frontend

- If `frontend/dist` exists at startup: `app.mount("/", StaticFiles(directory="frontend/dist", html=True))` — added **after** all API routes. One service serves API + WS + UI (locked deploy shape).
- If it doesn't: `/` returns the JSON placeholder; everything else works. The backend must never require the frontend to be present.
- `tests/test_smoke.py::test_health_endpoint` asserts `== {"status": "ok"}`. You are enriching `/health` (§5.4), so **update that assertion in the same commit** (assert `status == "ok"` plus the new keys). Say so in the PR — it's an intentional contract change, not a regression.

### 8.2 Dockerfile (new — it does not exist yet despite G0's deliverable)

Multi-stage, in the G5 series (G6 verifies the actual deploy):

```txt
STAGE 1 (node:22-slim):  copy frontend/, npm ci, npm run build  -> dist/
STAGE 2 (pinned uv image — copy the exact base + digest from the G0 research
         patches / .dockerignore assumptions): uv sync --locked --no-dev,
         copy cubesat/ + data/scenarios/ + committed logs + dist/ from stage 1,
         non-root user, ENV CUBESAT_LOG_DIR=/app/data/logs, EXPOSE ${PORT},
         HEALTHCHECK: python -c "import urllib.request; urllib.request.urlopen(
           'http://127.0.0.1:' + __import__('os').environ.get('PORT','8000') + '/health')"
         (no curl in the image), CMD uvicorn cubesat.api:app --host 0.0.0.0 --port ${PORT}
```

`.dockerignore` already excludes `data/logs` — the committed canonical logs therefore need a force-add or an ignore exception for the Docker build context too. Verify with `docker build` if the daemon is running (it was not at G0 — if unavailable, say so in the G5 report instead of claiming it works).

### 8.3 Dev proxy (no CORS anywhere)

The frontend's `vite.config.ts` (their side, but coordinate): proxy `/ws` → `ws://localhost:8000` (ws: true) and `/health`, `/scenarios`, `/simulation`, `/failure`, `/replay` → `http://localhost:8000`. Same-origin in production via the static mount. No `CORSMiddleware` needed.

---

## 9. Concurrency and determinism law

1. **One event loop, one worker process.** Sim compute runs in `asyncio.to_thread(run_scenario, scenario)` — it touches no shared state, so invariant #2 (determinism) is untouched.
2. **The driver task is the only pacing loop.** Each frame's emit instant = `wall_anchor + (t_frame − t_anchor) / speed`. Pause / seek / speed change / inject = cancel driver → re-anchor → respawn. Wall-clock is used **only** here, for the compute timeout, and for ping/rate decisions — never inside message content (invariant #2; FRONTEND_SPEC §19).
3. **Replanner timeout guard lives at the server, not in sim.py** — a wall-clock timeout inside the sim would break byte-identical logs. `asyncio.wait_for(to_thread(...), timeout=60)`. The in-sim graceful degradation (`allocation.method: "greedy"` in the scenario) remains the demo-visible fallback.
4. **Backpressure:** Hub queue maxsize 128; on overflow drop the oldest queued `sim_state` only. Events and `hello` are never dropped.
5. **Two clients are just two queues** off one Hub; a late joiner gets `hello` + `snapshot()` then joins the stream. No per-client sim state exists anywhere.
6. **The server never writes logs.** Replay writes nothing; live runs produce the same JSONL via `cubesat.run` (the CLI), not via the server. This keeps the golden-hash test meaningful.

---

## 10. Performance targets (local machine, demo-realistic)

| Metric | Target | How measured |
|---|---|---|
| WS emission cadence | ≤ 30 Hz wall (decimate; always emit event lines immediately) | driver logic; verified in test |
| Full `run_scenario` (two_failure) | ≤ ~2 s (already true) | H4 spike; if slower, precompute at `/simulation/start` and only recompute on inject |
| Inject recompute → first new frame | ≤ ~2 s stall, with a warning event before the gap | measured in H4, recorded in GATES.md |
| Replay load (8517-line file) | < 1 s | `load_jsonl` test timing |
| Memory (frames in RAM) | trivially small (< ~50 MB) | — |
| Replay seek | instant (bisect) | `index_at` test |

---

## 11. Test plan (test-first; names follow the repo's master-prompt-3.8 style)

New files: `tests/test_wire.py`, `tests/test_replay.py`, `tests/test_session.py`, `tests/test_api.py` (+ extend `test_smoke.py` for the enriched `/health`).

- `test_wire_sim_state_matches_spec_example` — a real tick line from `data/logs/two_failure.jsonl` → exact FRONTEND_SPEC §16.1 shape (golden fixture committed).
- `test_wire_status_and_id_normalization` — NOMINAL/DEAD/THRUSTER_OUT → healthy/failed+failure_type; int ids → "SAT-n".
- `test_wire_event_and_role_reassignment` — FAILURE_DETECTED / ASSIGNMENT payloads map per §6.1; unknown payload keys don't crash.
- `test_replay_load_bad_lines_skipped` — corrupt lines counted, good frames kept.
- `test_replay_seek_index` — `index_at` bisect correctness incl. boundaries.
- `test_replay_list_empty_dir` — `[]`, never an exception.
- `test_hub_slow_consumer_drops_state_keeps_events` — overflow drops sim_state, keeps event/role_reassignment.
- `test_session_replay_stream_and_seek` — load → frames in order → seek backwards/forwards → frames correct.
- `test_session_pause_resume_speed` — pacing re-anchors; no duplicate/missing frames.
- `test_live_equals_replay_frames` — run a scenario live, and stream its committed log: the message sequences are identical. **This is the one-pipeline proof (gate criterion 3).**
- `test_inject_prefix_byte_identical` — frames before the injected failure time are byte-identical to the pre-inject stream (gate criterion 4).
- `test_api_health_enriched`, `test_api_scenarios_listing_and_start_409`, `test_api_replay_file_traversal_guard`, `test_api_failure_inject_conflicts`, `test_ws_hello_snapshot_ping_pong`, `test_ws_two_clients`, `test_static_mount_guard`.

Existing suite must stay green — especially `test_run_is_byte_deterministic` (golden hash) and all of `test_fault.py`.

---

## 12. Build order (~6 h) and cut order

| Block | Time | Work | Proves |
|---|---|---|---|
| H1 | 0:00–1:00 | `wire.py` + golden tests vs the §16.1 example; `replay.py` + bad-line tests | wire contract pinned before anything streams |
| H2 | 1:00–2:00 | enriched `/health`, `/scenarios`, `/replay/files`, `/replay/file/{f}` + traversal guard; empty-dir cases; commit canonical logs + .gitignore exceptions | REST layer green with zero sim calls |
| H3 | 2:00–3:30 | Hub + ReplaySource + driver + `WS /ws/state` (hello/ping/pong/stream) | replay streams over WS in spec schema |
| H4 | 3:30–5:00 | LiveSource + `/simulation/*` + `/failure/inject`; `test_live_equals_replay_frames`, `test_inject_prefix_byte_identical` | gate criteria 1–4 |
| H5 | 5:00–5:45 | static mount + dist guard, Dockerfile, §7.1 error sweep, `uv run ruff check .`, full `uv run pytest -q` | gate criteria 5–7 |
| H6 | 5:45–6:00 | GATES.md G5 row: evidence + measured numbers (inject stall, replay load time); tag `gate-5-pass` if all green | gate protocol |

**Cut order (drop first):** cost_matrix broadcast (already off) → server-side replay seek (keep load+play; raw file endpoint remains) → adjustable speed (freeze 100×) → `/failure/inject` (scenario-scheduled failures at t=1200/1500 still demo the full arc) → WS replay driver (fall back to raw-file client replay for the demo; keep `/replay/file`).

**Never cut:** `/health`, `/scenarios`, the `sim_state` stream, ping/pong, `/replay/file/{f}`, `test_live_equals_replay_frames`, `test_inject_prefix_byte_identical`, the determinism suite.

**If you get blocked:** stop and report failure + 2 options with tradeoffs (gate protocol). Do not silently simplify, and do not touch the sim core to unblock G5.

---

## 13. Acceptance criteria

Functional: [ ] scenario list from directory · [ ] start/pause/resume/speed/reset over REST · [ ] live WS stream in contract schema · [ ] failure inject recompute, prefix byte-identical · [ ] replay load/play/pause/seek/speed · [ ] raw replay file served (mirror-ready) · [ ] static frontend served when built, API-only mode otherwise · [ ] ping→pong.

Reliability: [ ] slow client never stalls the stream · [ ] client disconnect is quiet · [ ] two clients work · [ ] corrupt log → skip + warn, never crash · [ ] no scenario → 200 `[]` + 409 on start · [ ] compute timeout → 504 + critical event · [ ] full `uv run pytest -q` green.

Determinism: [ ] golden-hash test green · [ ] `test_inject_prefix_byte_identical` green · [ ] no wall-clock in any message content.

Gate: [ ] GATES.md G5 row filled with commands + measured numbers, anything unmeasured written "unmeasured" · [ ] `gate-5-pass` only when everything above is checked.

---

## 14. Risks and mitigations

1. **Inject recompute stall** (~1–2 s) — mitigation designed in (warning event + seamless re-anchor). Measure early in H4; if >2 s, precompute at start and only recompute on inject.
2. **Wire drift** (int ids, uppercase statuses, INIT/SUMMARY states) — the single normalizer + golden test is the entire defense. Do not let a second mapping appear anywhere.
3. **Windows TestClient + threads flakiness** — keep driver frame-building logic pure/sync so tests drive frames deterministically; explicit timeouts on the two WS integration tests.
4. **Frontend lands after (or with) the backend** — the contract lock is `wire.py` + its tests, committed first; the frontend can develop against `/replay/file` + a recorded WS fixture immediately.
5. **`data/logs` gitignored** — canonical logs get whitelisted in G5 (§7.3) so replay-from-fresh-clone and the G6 mirror both work; `CUBESAT_LOG_DIR` covers container paths.
6. **Docker daemon unavailable** (it was down at G0) — if it's down during H5 too, ship the Dockerfile untested and write that honestly in GATES.md; G6 verifies.
7. **`httpx2` odd dev pin** — verify/remove in pre-flight (§3), with user approval.

---

## 15. What NOT to build

No authentication, no database, no rate limiting beyond the drop-oldest policy, no message queue, no Redis, no Celery, no server-side chart aggregation, no CORS config, no CI pipeline (G5 scope), no multi-worker support, no per-client sessions, no admin endpoints, no metric storage. The frontend computes mission-health and derived display metrics — the backend streams measured frames, nothing else.

---

## Appendix A — quick reference

```bash
uv sync --locked                                    # env (locked, per research patch #4)
uv run ruff check .                                 # lint
uv run pytest -q                                    # full suite (golden hash included)
uv run pytest -m "not slow" -x -q                   # fast loop
uv run pytest tests/test_api.py tests/test_wire.py -q   # G5 layers

uv run python -m cubesat.run --scenario data/scenarios/two_failure.json --seed 42 \
    --out data/logs/two_failure.jsonl               # regenerate canonical demo log (deterministic)
uv run uvicorn cubesat.api:app --port 8000          # the service (single worker, always)

curl localhost:8000/health                          # warm-up / healthcheck
curl localhost:8000/scenarios                       # directory listing
# ws://localhost:8000/ws/state                      # send {"type":"ping"} -> {"type":"pong"}
```

Wire contract source of truth: `docs/FRONTEND_SPEC.md` §15–§18 + §6 of this document. If they disagree: stop, fix both, note it in the PR.
