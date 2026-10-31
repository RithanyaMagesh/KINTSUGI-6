"""POST /scenarios/upload tests (G5 console addition): save a user-authored
scenario JSON into the scenarios dir so /simulation/start can run it by name.

Covers: valid upload -> saved + listed + started; invalid payload -> 422 with
the scenarios dir untouched; name collision with an existing scenario -> 409
and the file unchanged; hostile names sanitized (traversal-safe by
construction) or rejected; the default name "custom".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import TINY_SCENARIO, write_tiny_scenario
from fastapi.testclient import TestClient

from cubesat.api import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _fresh_api_state():
    """Same contract as tests/test_api.py: each test starts from a fresh
    per-process Session and no stale driver task survives into the next test."""
    import cubesat.api

    cubesat.api._state = None
    yield
    state = cubesat.api._state
    if state is not None and state.session._driver is not None:
        state.session._driver.cancel()  # best effort: the loop is gone anyway
    cubesat.api._state = None


@pytest.fixture
def scenarios(tmp_path, monkeypatch) -> Path:
    """Point scenarios_dir at a tmp dir (never the real data/scenarios)."""
    import cubesat.api

    directory = tmp_path / "scenarios"
    monkeypatch.setattr(cubesat.api, "scenarios_dir", lambda: directory)
    return directory


def test_upload_saves_lists_and_starts(scenarios, tmp_path, monkeypatch):
    """Valid upload -> saved (pretty JSON), GET /scenarios lists it, and the
    existing POST /simulation/start runs it by file name."""
    import cubesat.api

    monkeypatch.setattr(cubesat.api, "log_dir", lambda: tmp_path / "logs")
    payload = dict(TINY_SCENARIO, name="my_run")
    r = client.post("/scenarios/upload", json={"name": "my_run", "scenario": payload})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "saved"
    assert body["filename"] == "my_run.json"
    assert body["scenarios"] == ["my_run.json"]
    saved = scenarios / "my_run.json"
    assert saved.is_file()
    assert json.loads(saved.read_text(encoding="utf-8")) == payload
    assert "\n" in saved.read_text(encoding="utf-8")  # pretty, not one line

    assert client.get("/scenarios").json() == {"scenarios": ["my_run.json"]}
    r = client.post("/simulation/start", json={"scenario": "my_run.json", "speed": 1e6})
    assert r.status_code == 200
    assert r.json()["mode"] == "live"
    # enrichment carries the scenario's own name, like any other live start
    assert client.get("/health").json()["scenario"] == "my_run"
    assert client.post("/simulation/reset").status_code == 200


def test_upload_default_name_custom(scenarios):
    """No name in the body -> the sanitized default "custom"."""
    r = client.post("/scenarios/upload", json={"scenario": dict(TINY_SCENARIO, name="custom")})
    assert r.status_code == 200
    assert r.json()["filename"] == "custom.json"
    assert r.json()["scenarios"] == ["custom.json"]
    assert (scenarios / "custom.json").is_file()


def test_upload_invalid_payload_422_dir_untouched(tmp_path, monkeypatch):
    """A payload the real Scenario loader rejects -> 422 with the validation
    detail, and the scenarios dir is never created or written."""
    import cubesat.api

    directory = tmp_path / "scenarios"  # does not exist yet
    monkeypatch.setattr(cubesat.api, "scenarios_dir", lambda: directory)
    r = client.post("/scenarios/upload", json={"name": "bad", "scenario": {"name": "bad"}})
    assert r.status_code == 422
    assert "invalid scenario" in r.json()["detail"]
    assert "seed: Field required" in r.json()["detail"]  # field named, plain English
    assert not directory.exists()  # untouched on failure

    # a non-dict scenario never reaches the loader: the request model 422s first
    r = client.post("/scenarios/upload", json={"name": "bad", "scenario": "nope"})
    assert r.status_code == 422
    assert not directory.exists()


def test_upload_collision_with_existing_scenario_409(scenarios):
    """A name that already exists as a scenario file (here the committed-name
    stand-in nominal.json) -> 409 naming the collision, file byte-identical."""
    scenarios.mkdir(parents=True)
    path = scenarios / "nominal.json"
    path.write_text("{}", encoding="utf-8", newline="\n")
    original = path.read_bytes()
    r = client.post("/scenarios/upload", json={"name": "nominal", "scenario": TINY_SCENARIO})
    assert r.status_code == 409
    assert "nominal.json" in r.json()["detail"]
    assert path.read_bytes() == original
    assert client.get("/scenarios").json() == {"scenarios": ["nominal.json"]}


def test_upload_hostile_name_sanitized_or_rejected(scenarios):
    """Traversal and separator characters are stripped ("../evil" saves inside
    the dir as evil.json); names that sanitize to empty are rejected with 422."""
    payload = dict(TINY_SCENARIO, name="evil")
    r = client.post("/scenarios/upload", json={"name": "../evil", "scenario": payload})
    assert r.status_code == 200
    assert r.json()["filename"] == "evil.json"
    saved = scenarios / "evil.json"
    assert saved.is_file()  # inside the scenarios dir only
    assert saved.resolve().parent == scenarios.resolve()
    assert json.loads(saved.read_text(encoding="utf-8")) == payload
    assert not (scenarios.parent / "evil.json").exists()  # nothing escaped
    assert client.get("/scenarios").json() == {"scenarios": ["evil.json"]}

    for hostile in ("..", "...", "", "///"):
        r = client.post("/scenarios/upload", json={"name": hostile, "scenario": payload})
        assert r.status_code == 422, hostile
        assert "sanitizing" in r.json()["detail"]
    # backslash traversal sanitizes to the same name -> hits the collision guard,
    # still never a second file
    r = client.post("/scenarios/upload", json={"name": "..\\..\\evil", "scenario": payload})
    assert r.status_code == 409
    assert "evil.json" in r.json()["detail"]
    assert client.get("/scenarios").json() == {"scenarios": ["evil.json"]}  # no new files


def test_upload_then_start_by_name_with_other_scenarios_present(scenarios):
    """The saved file is visible to the Session too (bound from the same
    scenarios_dir): with two scenarios present, start picks the asked-for one."""
    write_tiny_scenario(scenarios)  # tiny.json already there
    r = client.post("/scenarios/upload",
                    json={"name": "uploaded", "scenario": dict(TINY_SCENARIO, name="uploaded")})
    assert r.status_code == 200
    assert r.json()["scenarios"] == ["tiny.json", "uploaded.json"]
    r = client.post("/simulation/start", json={"scenario": "uploaded.json", "speed": 1e6})
    assert r.status_code == 200
    assert client.get("/health").json()["scenario"] == "uploaded"  # not tiny: by-name start
    assert client.post("/simulation/reset").status_code == 200


def test_upload_rejects_oversized_payload(scenarios, monkeypatch):
    """Audit regression (low): a 20 MB filler used to be accepted and written
    verbatim (disk fill / memory pressure on the shared process). A body above
    the cap is refused 413 from its Content-Length before parsing; nothing is
    written."""
    import cubesat.api

    monkeypatch.setattr(cubesat.api, "MAX_UPLOAD_BYTES", 1000)
    payload = dict(TINY_SCENARIO, filler="x" * 2000)
    r = client.post("/scenarios/upload", json={"name": "big", "scenario": payload})
    assert r.status_code == 413
    assert "exceeds" in r.json()["detail"]
    assert not scenarios.exists()  # nothing created or written


def test_upload_file_count_cap(scenarios, monkeypatch):
    """Audit regression (low): no limit on how many files uploads could
    create; the scenarios dir now refuses to grow past the cap (429)."""
    import cubesat.api

    monkeypatch.setattr(cubesat.api, "MAX_SCENARIO_FILES", 2)
    for name in ("a", "b"):
        r = client.post("/scenarios/upload",
                        json={"name": name, "scenario": dict(TINY_SCENARIO, name=name)})
        assert r.status_code == 200, name
    r = client.post("/scenarios/upload",
                    json={"name": "c", "scenario": dict(TINY_SCENARIO, name="c")})
    assert r.status_code == 429
    assert "full" in r.json()["detail"]
    assert client.get("/scenarios").json() == {"scenarios": ["a.json", "b.json"]}


def test_upload_sanitizes_hostile_labels(scenarios):
    """Audit regression (low): Scenario.name and roles[] were stored verbatim
    and echoed into /health, the WS hello and sim_state (stored injection;
    inert under React today, XSS under any non-escaping consumer). The upload
    strips the HTML/script-significant characters, so every downstream echo
    carries the sanitized string."""
    payload = dict(
        TINY_SCENARIO,
        name="<script>alert(1)</script>",
        roles=["leader", "<img src=x onerror=alert(1)>"],
    )
    r = client.post("/scenarios/upload", json={"name": "inj", "scenario": payload})
    assert r.status_code == 200
    saved = json.loads((scenarios / "inj.json").read_text(encoding="utf-8"))
    assert saved["name"] == "scriptalert(1)/script"  # </script> keeps its harmless /
    assert saved["roles"] == ["leader", "img src=x onerror=alert(1)"]
    r = client.post("/simulation/start", json={"scenario": "inj.json", "speed": 1e6})
    assert r.status_code == 200
    assert r.json()["scenario"] == "scriptalert(1)/script"
    assert client.get("/health").json()["scenario"] == "scriptalert(1)/script"
    with client.websocket_connect("/ws/state") as ws:
        assert ws.receive_json()["scenario"] == "scriptalert(1)/script"
    assert client.post("/simulation/reset").status_code == 200
