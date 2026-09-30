"""H2 REST tests (BACKEND_SPEC v1.1 sections 5.4, 7.2, 7.3, 11): zero sim calls.

H2 scope: enriched /health, /scenarios, /replay/files, /replay/file/{filename}
(+ traversal guard, CUBESAT_LOG_DIR override). The /simulation/* and /failure/*
routes arrive in H3/H4; test_api_scenarios_listing_and_start_409 gains its
start-409 assertions then.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from cubesat.api import app

client = TestClient(app)


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
