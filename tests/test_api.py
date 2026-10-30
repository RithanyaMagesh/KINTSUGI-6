"""H2 REST tests (BACKEND_SPEC v1.1 sections 5.4, 7.2, 7.3, 11) plus the H3/H4
/simulation/*, /failure/inject, /replay/load and WS /ws/state tests.

H2 scope: enriched /health, /scenarios, /replay/files, /replay/file/{filename}
(+ traversal guard, CUBESAT_LOG_DIR override).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import tiny_log_lines, write_log, write_tiny_scenario
from fastapi.testclient import TestClient

from cubesat.api import app, get_state
from cubesat.wire import SessionEnrich, to_messages

client = TestClient(app)


@pytest.fixture(autouse=True)
def _fresh_api_state():
    """One Session per process (section 9.1): each test starts from a fresh one,
    and no stale driver task survives into the next test/loop."""
    import cubesat.api

    cubesat.api._state = None
    yield
    state = cubesat.api._state
    if state is not None and state.session._driver is not None:
        state.session._driver.cancel()  # best effort: the loop is gone anyway
    cubesat.api._state = None


def _log_dir(tmp_path: Path, files: dict[str, str]) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (tmp_path / name).write_text(body, encoding="utf-8", newline="\n")
    return tmp_path


def test_api_health_enriched():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    # section 5.4 enriched shape; H2 has no session yet, so the stopped defaults
    assert body["mode"] == "stopped"
    assert body["sim_time"] is None
    assert body["scenario"] is None
    assert body["paused"] is False


def test_api_scenarios_listing(tmp_path, monkeypatch):
    import cubesat.api

    scenarios = tmp_path / "scenarios"
    scenarios.mkdir()
    (scenarios / "two_failure.json").write_text("{}", encoding="utf-8")
    (scenarios / "nominal.json").write_text("{}", encoding="utf-8")
    (scenarios / "not_a_scenario.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(cubesat.api, "scenarios_dir", lambda: scenarios)
    response = client.get("/scenarios")
    assert response.status_code == 200
    assert response.json() == {"scenarios": ["nominal.json", "two_failure.json"]}


def test_api_scenarios_listing_empty_dir_never_500(tmp_path, monkeypatch):
    import cubesat.api

    scenarios = tmp_path / "scenarios"
    scenarios.mkdir()
    monkeypatch.setattr(cubesat.api, "scenarios_dir", lambda: scenarios)
    assert client.get("/scenarios").json() == {"scenarios": []}
    missing = tmp_path / "missing"
    monkeypatch.setattr(cubesat.api, "scenarios_dir", lambda: missing)
    response = client.get("/scenarios")
    assert response.status_code == 200
    assert response.json() == {"scenarios": []}


def test_api_replay_files_listing(tmp_path, monkeypatch):
    import cubesat.api

    log_dir = _log_dir(tmp_path / "logs", {"b.jsonl": "{}\n", "a.jsonl": "{}\n",
                                           "skip.txt": "x\n"})
    monkeypatch.setattr(cubesat.api, "log_dir", lambda: log_dir)
    response = client.get("/replay/files")
    assert response.status_code == 200
    assert response.json() == {"files": ["a.jsonl", "b.jsonl"]}


def test_api_replay_files_empty_and_missing_dir(tmp_path, monkeypatch):
    import cubesat.api

    monkeypatch.setattr(cubesat.api, "log_dir", lambda: tmp_path / "empty")
    response = client.get("/replay/files")
    assert response.status_code == 200
    assert response.json() == {"files": []}


def test_api_log_dir_env_override(tmp_path, monkeypatch):
    log_dir = _log_dir(tmp_path / "custom", {"two_failure.jsonl": "{}\n"})
    monkeypatch.setenv("CUBESAT_LOG_DIR", str(log_dir))

    response = client.get("/replay/files")
    assert response.status_code == 200
    assert response.json() == {"files": ["two_failure.jsonl"]}


def test_api_replay_file_serves_named_log(tmp_path, monkeypatch):
    import cubesat.api

    log_dir = _log_dir(tmp_path / "logs", {"two_failure.jsonl": '{"t": 0.0}\n'})
    monkeypatch.setattr(cubesat.api, "log_dir", lambda: log_dir)
    response = client.get("/replay/file/two_failure.jsonl")
    assert response.status_code == 200
    assert response.text == '{"t": 0.0}\n'


def test_api_replay_file_traversal_guard(tmp_path, monkeypatch):
    import cubesat.api

    log_dir = _log_dir(tmp_path / "logs", {"two_failure.jsonl": "{}\n"})
    secret = tmp_path / "secret.jsonl"
    secret.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(cubesat.api, "log_dir", lambda: log_dir)
    # section 7.2: ../ traversal, absolute paths, plain misses -> 404, never a leak
    assert client.get("/replay/file/../secret.jsonl").status_code == 404
    assert client.get("/replay/file/..%2Fsecret.jsonl").status_code == 404
    assert client.get(f"/replay/file/{secret}").status_code == 404
    assert client.get("/replay/file/nope.jsonl").status_code == 404
    # the real file is still served
    assert client.get("/replay/file/two_failure.jsonl").status_code == 200


def test_api_replay_file_suffix_guard(tmp_path, monkeypatch):
    """Audit regression (low): /replay/file served ANY file in the log dir
    while /replay/files lists only .jsonl. The serve surface must equal the
    listing surface (matters when CUBESAT_LOG_DIR points at a broader dir)."""
    import cubesat.api

    log_dir = _log_dir(
        tmp_path / "logs",
        {"two_failure.jsonl": "{}\n", "notes.txt": "x\n", "two_failure.json": "{}\n"},
    )
    monkeypatch.setattr(cubesat.api, "log_dir", lambda: log_dir)
    assert client.get("/replay/file/two_failure.jsonl").status_code == 200
    for name in ("notes.txt", "two_failure.json"):
        assert client.get(f"/replay/file/{name}").status_code == 404, name


def test_host_header_allowlist():
    """Audit regression (low): no Host-header validation anywhere. The
    TrustedHost allowlist 400s a foreign Host (DNS-rebinding defense) while
    localhost and the TestClient default keep working."""
    assert client.get("/health").status_code == 200  # default Host: testserver
    r = client.get("/health", headers={"Host": "evil.example.com"})
    assert r.status_code == 400
    assert client.get("/health", headers={"Host": "localhost:8000"}).status_code == 200
    assert client.get("/health", headers={"Host": "127.0.0.1:8000"}).status_code == 200


# --------------------------------------------------------------------------
# H3/H4: /simulation/*, /failure/inject, /replay/load, WS /ws/state
# --------------------------------------------------------------------------


def test_api_scenarios_listing_and_start_409(tmp_path, monkeypatch):
    """Section 7.1: no scenario available -> GET /scenarios 200 [] and
    POST /simulation/start 409; /simulation/* while stopped -> 409."""
    import cubesat.api

    monkeypatch.setattr(cubesat.api, "scenarios_dir", lambda: tmp_path / "scenarios")
    monkeypatch.setattr(cubesat.api, "log_dir", lambda: tmp_path / "logs")
    (tmp_path / "scenarios").mkdir(parents=True, exist_ok=True)
    assert client.get("/scenarios").json() == {"scenarios": []}
    r = client.post("/simulation/start", json={})
    assert r.status_code == 409
    for route in ("/simulation/pause", "/simulation/resume", "/simulation/speed",
                  "/replay/seek", "/replay/speed"):
        r = client.post(route, json={"t": 0.0} if route.endswith("seek") else {"speed": 2.0})
        assert r.status_code == 409, route
        assert r.json()["detail"] == "no simulation running"

    # with a scenario present: start -> 200 live, /health reflects the session
    # (the session already binds scenarios_dir above, which now holds tiny.json)
    write_tiny_scenario(tmp_path / "scenarios")
    r = client.post("/simulation/start", json={})  # default: first sorted scenario
    assert r.status_code == 200
    assert r.json()["mode"] == "live"
    assert r.json()["scenario"] == "tiny"
    health = client.get("/health").json()
    assert health["status"] == "ok"
    assert health["mode"] == "live"
    assert health["scenario"] == "tiny"
    assert health["paused"] is False
    # reset always allowed -> stopped
    assert client.post("/simulation/reset").status_code == 200
    assert client.get("/health").json()["mode"] == "stopped"


def test_api_simulation_pause_resume_speed(tmp_path, monkeypatch):
    import cubesat.api

    write_tiny_scenario(tmp_path / "scenarios")
    write_log(tmp_path / "logs", "tiny.jsonl", tiny_log_lines())
    monkeypatch.setattr(cubesat.api, "scenarios_dir", lambda: tmp_path / "scenarios")
    assert client.post("/simulation/start", json={"speed": 1e6}).status_code == 200
    assert client.post("/simulation/pause").json()["paused"] is True
    assert client.post("/simulation/resume").json()["paused"] is False
    assert client.post("/simulation/speed", json={"speed": 10.0}).json()["speed"] == 10.0


def test_api_replay_load_seek_and_unknown_file(tmp_path, monkeypatch):
    import cubesat.api

    monkeypatch.setattr(cubesat.api, "log_dir", lambda: tmp_path / "logs")
    write_log(tmp_path / "logs", "tiny.jsonl", tiny_log_lines())
    r = client.post("/replay/load", json={"filename": "tiny.jsonl", "speed": 1e6})
    assert r.status_code == 200
    assert r.json()["skipped"] == 0
    assert client.get("/health").json()["mode"] == "replay"
    assert client.post("/replay/seek", json={"t": 3.0}).status_code == 200
    assert client.post("/replay/speed", json={"speed": 5.0}).status_code == 200
    assert client.post("/replay/pause").status_code == 200
    assert client.post("/replay/resume").status_code == 200
    assert client.post("/replay/stop").status_code == 200
    assert client.get("/health").json()["mode"] == "stopped"
    r = client.post("/replay/load", json={"filename": "nope.jsonl"})
    assert r.status_code == 404


def test_api_failure_inject_conflicts(tmp_path, monkeypatch):
    """Section 7.1 bad-inject row: 409 with a reason -- not live / unknown sat /
    already failed."""
    import cubesat.api

    monkeypatch.setattr(cubesat.api, "scenarios_dir", lambda: tmp_path / "scenarios")
    monkeypatch.setattr(cubesat.api, "log_dir", lambda: tmp_path / "logs")
    body = {"sat_id": "SAT-1", "mode": "DEAD"}
    # not live (stopped)
    r = client.post("/failure/inject", json=body)
    assert r.status_code == 409
    # not live (replay)
    write_log(tmp_path / "logs", "tiny.jsonl", tiny_log_lines())
    load = client.post("/replay/load", json={"filename": "tiny.jsonl", "speed": 1e6})
    assert load.status_code == 200
    assert client.post("/failure/inject", json=body).status_code == 409
    assert client.post("/simulation/reset").status_code == 200
    # live: unknown sat, then already failed (SAT-1 fails at t=6 in the scenario)
    # speed 40 (not 1e6): the 11-frame run must still be in flight when the
    # injects land -- at 1e6 it finishes before the first inject and the
    # "run finished" conflict (also correct) masks the ones under test here
    write_tiny_scenario(tmp_path / "scenarios")
    assert client.post("/simulation/start", json={"speed": 40.0}).status_code == 200
    r = client.post("/failure/inject", json={"sat_id": "SAT-9", "mode": "DEAD"})
    assert r.status_code == 409
    assert "unknown" in r.json()["detail"]
    r = client.post("/failure/inject", json=body)
    assert r.status_code == 409
    assert "already failed" in r.json()["detail"]
    # a healthy sat injects fine
    r = client.post("/failure/inject", json={"sat_id": "SAT-2", "mode": "THRUSTER_OUT"})
    assert r.status_code == 200
    assert r.json()["injected"] == {"sat_id": "SAT-2", "mode": "THRUSTER_OUT"}


def test_ws_hello_snapshot_ping_pong():
    """Section 6.3 lifecycle: accept -> hello -> snapshot (empty-state sim_state
    when nothing has run); ping -> pong; non-ping input ignored."""
    with client.websocket_connect("/ws/state") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"
        assert hello["mode"] == "stopped"
        assert hello["skipped"] == 0
        snap = ws.receive_json()
        assert snap["type"] == "sim_state"
        assert snap["state"] == "NOMINAL"  # INIT never appears on the wire
        assert snap["sats"] == []  # section 24.3 empty state
        ws.send_json({"type": "noise"})  # ignored, connection stays up
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_ws_malformed_frame_closes_1003():
    """Audit regression (low): a non-JSON frame used to escape read_loop as an
    unhandled json.JSONDecodeError per bad frame; now the server closes
    gracefully with 1003 (unsupported data), the finally-block unsubscribes,
    and a later client connects normally."""
    from starlette.websockets import WebSocketDisconnect

    with client.websocket_connect("/ws/state") as ws:
        assert ws.receive_json()["type"] == "hello"
        ws.send_text("this is not json")
        with pytest.raises(WebSocketDisconnect) as excinfo:
            while True:
                ws.receive_json()
        assert excinfo.value.code == 1003
    # the server process is unharmed: a fresh client gets a clean hello
    with client.websocket_connect("/ws/state") as ws:
        assert ws.receive_json()["type"] == "hello"


def test_ws_two_clients(tmp_path, monkeypatch):
    """Section 9.5: two clients are two queues off one Hub; both see the same
    replay stream, in the same order.

    Windows/TestClient flakiness guard (section 14.3): the stream is a bounded
    6-message fixture with pacing neutralized (speed 1e6, decimation off), so
    every receive terminates deterministically without a wall-clock timeout.
    """
    import cubesat.api

    monkeypatch.setattr(cubesat.api, "log_dir", lambda: tmp_path / "logs")
    monkeypatch.setattr(cubesat.api, "_MIN_EMIT_INTERVAL", 0.0)
    write_log(tmp_path / "logs", "tiny.jsonl", tiny_log_lines())
    expected = []
    for line in tiny_log_lines():
        expected.extend(to_messages(line, SessionEnrich(scenario="tiny", seed=7)))

    with client.websocket_connect("/ws/state") as c1, \
            client.websocket_connect("/ws/state") as c2:
        for c in (c1, c2):
            assert c.receive_json()["type"] == "hello"
            assert c.receive_json()["type"] == "sim_state"  # snapshot
        r = client.post("/replay/load", json={"filename": "tiny.jsonl", "speed": 1e6})
        assert r.status_code == 200

        def stream(ws):
            msgs = []
            while True:
                msg = ws.receive_json()
                msgs.append(msg)
                if msg.get("message") == "Run complete":
                    return msgs

        assert stream(c1) == expected
        assert stream(c2) == expected


# --------------------------------------------------------------------------
# H5: static mount guard (section 8.1) + section 7.1 error-semantics sweep
# --------------------------------------------------------------------------


def test_static_mount_guard(tmp_path):
    """Section 8.1, both branches: frontend/dist present -> StaticFiles(html=True)
    mounted at / AFTER the API routes (API keeps precedence); absent -> / is the
    JSON placeholder and API-only mode still serves everything."""
    from fastapi import FastAPI

    from cubesat.api import DIST_DIR, mount_static

    # branch 1: dist exists -> mounted; /health (registered before the mount) wins
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>ui</html>", encoding="utf-8")
    mounted_app = FastAPI()

    @mounted_app.get("/health")
    def _health() -> dict:
        return {"status": "ok"}

    assert mount_static(mounted_app, dist) is True
    mounted_client = TestClient(mounted_app)
    assert mounted_client.get("/health").json() == {"status": "ok"}
    assert mounted_client.get("/").text == "<html>ui</html>"

    # branch 2: dist absent -> placeholder, API routes unaffected
    plain_app = FastAPI()

    @plain_app.get("/health")
    def _health2() -> dict:
        return {"status": "ok"}

    assert mount_static(plain_app, tmp_path / "missing") is False
    plain_client = TestClient(plain_app)
    assert plain_client.get("/").json() == {"error": "frontend not built"}
    assert plain_client.get("/health").json() == {"status": "ok"}

    # this branch ships no frontend/ yet: the live app must be in API-only mode
    if not DIST_DIR.is_dir():
        assert client.get("/").json() == {"error": "frontend not built"}
        assert client.get("/health").status_code == 200
        assert client.get("/scenarios").status_code == 200


def test_api_replay_corrupt_load_skips_and_warns(tmp_path, monkeypatch):
    """Section 7.1 corrupt-replay row: POST /replay/load -> 200 with
    skipped == N plus a warning event; a file with ZERO good frames instead
    broadcasts a critical event -- never a 500."""
    import cubesat.api

    monkeypatch.setattr(cubesat.api, "log_dir", lambda: tmp_path / "logs")
    logs = tmp_path / "logs"
    good = "".join(json.dumps(line, sort_keys=True) + "\n" for line in tiny_log_lines())
    # one JSONDecodeError line + one parseable-but-not-a-frame line
    (logs).mkdir(parents=True, exist_ok=True)
    (logs / "corrupt.jsonl").write_text("garbage line\n" + '{"t": "nan"}\n' + good,
                                        encoding="utf-8", newline="\n")

    hub_q = get_state().hub.subscribe()
    r = client.post("/replay/load", json={"filename": "corrupt.jsonl", "speed": 1e6})
    assert r.status_code == 200
    assert r.json()["skipped"] == 2
    assert r.json()["mode"] == "replay"
    events = [hub_q.get_nowait() for _ in range(hub_q.qsize())]
    assert any(m["type"] == "event" and m["level"] == "warning" and "2 unparseable" in m["message"]
               for m in events)
    assert not any(m.get("level") == "critical" for m in events)

    # zero good frames: 200 (skipped still counted) + a critical event
    (logs / "junk.jsonl").write_text("garbage\nalso garbage\n", encoding="utf-8", newline="\n")
    hub_q2 = get_state().hub.subscribe()
    r = client.post("/replay/load", json={"filename": "junk.jsonl", "speed": 1e6})
    assert r.status_code == 200
    assert r.json()["skipped"] == 2
    events = [hub_q2.get_nowait() for _ in range(hub_q2.qsize())]
    assert any(m["type"] == "event" and m["level"] == "critical" for m in events)
    # the session is up (replay mode) but holds no frames; reset cleans up
    assert client.get("/health").json()["mode"] == "replay"
    assert client.post("/simulation/reset").json()["mode"] == "stopped"
