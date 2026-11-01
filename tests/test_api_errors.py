"""Loud 422 (kit section 4, audit B-13/B-14): every 422 carries a plain-English
`detail` string naming the field and the reason -- no pydantic URLs, no stack
traces, no file paths -- and the server never silently drops a requested option
(policy / predictor): it honours it or answers 422.
"""

from __future__ import annotations

import pytest
from conftest import TINY_SCENARIO, tiny_log_lines, write_log, write_tiny_scenario
from fastapi.testclient import TestClient

from cubesat.api import app

client = TestClient(app)


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


def _loud(response, *needles: str) -> str:
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, str), detail
    for needle in needles:
        assert needle in detail, (needle, detail)
    for leak in ("Traceback", "pydantic.dev", ".py", "/Users", "\\"):
        assert leak not in detail, (leak, detail)
    return detail


def test_invalid_policy_names_field_and_choices():
    r = client.post("/simulation/start", json={"policy": "bogus"})
    _loud(r, "policy", "hungarian", "even_split", "hungarian_keepout")


def test_bad_failure_mode_names_field_and_choices():
    r = client.post("/failure/inject", json={"sat_id": "SAT-1", "mode": "MELT"})
    _loud(r, "mode", "DEAD", "THRUSTER_OUT", "EPS_DEGRADE")


def test_missing_field_and_non_json_body():
    _loud(client.post("/failure/inject", json={"mode": "DEAD"}), "sat_id")
    r = client.post(
        "/simulation/start", content=b"{not json", headers={"content-type": "application/json"}
    )
    _loud(r, "request body", "JSON")


@pytest.mark.parametrize(
    ("route", "body"),
    [
        ("/simulation/start", {"speed": 0}),
        ("/simulation/start", {"speed": -3}),
        ("/replay/load", {"filename": "tiny.jsonl", "speed": 0}),
    ],
)
def test_speed_not_positive(route, body):
    _loud(client.post(route, json=body), "speed", "greater than")


def test_speed_endpoint_not_positive():
    assert client.post("/simulation/start", json={"speed": 1e6}).status_code == 200
    _loud(client.post("/simulation/speed", json={"speed": -1}), "speed", "greater than")


def test_predictor_unavailable_is_422_and_keeps_running_session(monkeypatch):
    import predictor.runtime as predictor_runtime

    assert client.post("/simulation/start", json={"speed": 2.0}).status_code == 200

    def boom(telemetry):
        raise RuntimeError("model gone at /secret/path/predictor.txt")

    monkeypatch.setattr(predictor_runtime, "score_run", boom)
    r = client.post("/simulation/start", json={"speed": 2.0, "predictor": True})
    detail = _loud(r, "predictor", "unavailable")
    assert "secret" not in detail
    health = client.get("/health").json()
    assert health["mode"] == "live" and health["scenario"] == "tiny"  # not torn down


def test_replay_predictor_unavailable_is_422(monkeypatch, tmp_path):
    (tmp_path / "scenarios" / "tiny.json").unlink()  # the log's scenario is gone
    r = client.post("/replay/load", json={"filename": "tiny.jsonl", "predictor": True})
    _loud(r, "predictor", "unavailable")
    assert client.get("/health").json()["mode"] == "stopped"


def test_upload_invalid_scenario_names_field():
    bad = dict(TINY_SCENARIO, dt_s=-1.0)
    r = client.post("/scenarios/upload", json={"name": "bad", "scenario": bad})
    _loud(r, "invalid scenario", "dt_s")
