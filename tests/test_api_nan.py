"""NaN / Infinity / absurd speed (audit B-13, B-14): bodies and uploads reject
non-finite numbers with a loud 422, speed has sane bounds, and the WebSocket
never emits invalid JSON."""

from __future__ import annotations

import json

import pytest
from conftest import TINY_SCENARIO, tiny_log_lines, write_log, write_tiny_scenario
from fastapi.testclient import TestClient

from cubesat.api import app
from cubesat.wire import SPEED_MAX, SPEED_MIN

client = TestClient(app)
JSON = {"content-type": "application/json"}


@pytest.fixture(autouse=True)
def _fresh_api_state(tmp_path, monkeypatch):
    import cubesat.api

    cubesat.api._state = None
    monkeypatch.setattr(cubesat.api, "scenarios_dir", lambda: tmp_path / "scenarios")
    monkeypatch.setattr(cubesat.api, "log_dir", lambda: tmp_path / "logs")
    write_tiny_scenario(tmp_path / "scenarios")
    write_log(tmp_path / "logs", "tiny.jsonl", tiny_log_lines())
    yield
    state = cubesat.api._state
    if state is not None and state.session._driver is not None:
        state.session._driver.cancel()
    cubesat.api._state = None


def _post(route: str, raw: str):
    return client.post(route, content=raw.encode(), headers=JSON)


@pytest.mark.parametrize(
    ("route", "raw", "field"),
    [
        ("/simulation/speed", '{"speed": NaN}', "speed"),
        ("/simulation/speed", '{"speed": Infinity}', "speed"),
        ("/simulation/start", '{"speed": 1e999}', "speed"),
        ("/simulation/start", '{"speed": -Infinity}', "speed"),
        ("/replay/load", '{"filename": "tiny.jsonl", "speed": NaN}', "speed"),
        ("/failure/inject", '{"sat_id": "SAT-1", "mode": "EPS_DEGRADE", "degrade_s": NaN}',
         "degrade_s"),
        ("/replay/seek", '{"t": NaN}', "t"),
        ("/replay/seek", '{"t": Infinity}', "t"),
    ],
)
def test_non_finite_body_is_422_naming_field(route, raw, field):
    r = _post(route, raw)
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail.startswith(f"{field}: ") and "finite" in detail, detail


@pytest.mark.parametrize("speed", [1e-9, SPEED_MIN / 2, SPEED_MAX * 10, 1e300])
def test_speed_outside_bounds_is_422(speed):
    r = client.post("/simulation/start", json={"speed": speed})
    assert r.status_code == 422
    assert "speed" in r.json()["detail"]
    assert client.get("/health").json()["mode"] == "stopped"


def test_speed_at_bounds_is_accepted():
    assert client.post("/simulation/start", json={"speed": SPEED_MAX}).status_code == 200
    assert client.post("/simulation/speed", json={"speed": SPEED_MIN}).status_code == 200


def test_upload_rejects_nan_and_infinity_naming_the_field(tmp_path):
    for token in ("NaN", "Infinity", "1e999"):
        body = json.dumps({"name": "n", "scenario": TINY_SCENARIO})
        body = body.replace(
            '"phase_offset_deg": 0.0', f'"phase_offset_deg": {token}'
        )
        assert token in body
        r = _post("/scenarios/upload", body)
        assert r.status_code == 422, (token, r.text)
        detail = r.json()["detail"]
        assert "formation.phase_offset_deg" in detail and "finite" in detail, detail
    assert not (tmp_path / "scenarios" / "n.json").exists()


def test_ws_never_emits_invalid_json_for_non_finite_frames(tmp_path, monkeypatch):
    """A replay log whose frame carries NaN positions used to reach the browser
    as the literal token NaN (JSON.parse throws). The frame is now replaced by a
    critical event and every WS text frame is strict JSON."""
    import cubesat.api

    monkeypatch.setattr(cubesat.api, "_MIN_EMIT_INTERVAL", 0.0)
    lines = tiny_log_lines()
    lines[2]["sats"][0]["r"] = [float("nan"), 0.0, 0.0]
    write_log(tmp_path / "logs", "nan.jsonl", lines)

    def strict(text: str):
        def bad(token):
            raise AssertionError(f"invalid JSON token {token} on the wire: {text[:120]}")

        return json.loads(text, parse_constant=bad)

    with client.websocket_connect("/ws/state") as ws:
        strict(ws.receive_text())  # hello
        strict(ws.receive_text())  # snapshot
        r = client.post("/replay/load", json={"filename": "nan.jsonl", "speed": 1e6})
        assert r.status_code == 200
        msgs = []
        while True:
            msg = strict(ws.receive_text())
            msgs.append(msg)
            if msg.get("message") == "Run complete":
                break
    assert any(m.get("level") == "critical" and "NaN" in m["message"] for m in msgs)
