"""Host guard (audit B-8): localhost / 127.0.0.1 / [::1] are ALWAYS allowed (container
healthchecks, local use); CUBESAT_ALLOWED_HOSTS adds hosts (comma-separated), and the
explicit value `*` still allows any. Each case loads a FRESH copy of cubesat/api.py,
because the middleware list is built when the module is imported."""

from __future__ import annotations

import importlib.util
import sys

import pytest
from fastapi.testclient import TestClient

import cubesat.api as real_api


def _fresh_client(monkeypatch, env: str | None) -> TestClient:
    if env is None:
        monkeypatch.delenv("CUBESAT_ALLOWED_HOSTS", raising=False)
    else:
        monkeypatch.setenv("CUBESAT_ALLOWED_HOSTS", env)
    spec = importlib.util.spec_from_file_location("cubesat_api_fresh", real_api.__file__)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)  # pydantic resolves annotations here
    spec.loader.exec_module(module)
    return TestClient(module.app)


def _status(client: TestClient, host: str) -> int:
    return client.get("/health", headers={"Host": host}).status_code


LOCAL = ["localhost", "localhost:8000", "127.0.0.1", "127.0.0.1:8102", "[::1]", "[::1]:8000"]


def test_env_hosts_are_additional_localhost_always_allowed(monkeypatch):
    client = _fresh_client(monkeypatch, "demo.example.com")
    for host in LOCAL:
        assert _status(client, host) == 200, host  # the Dockerfile HEALTHCHECK case
    assert _status(client, "demo.example.com") == 200
    assert _status(client, "demo.example.com:443") == 200
    assert _status(client, "evil.com") == 400


def test_env_accepts_comma_separated_list_with_spaces(monkeypatch):
    client = _fresh_client(monkeypatch, "a.example.com, b.example.com")
    assert _status(client, "a.example.com") == 200
    assert _status(client, "b.example.com") == 200
    assert _status(client, "c.example.com") == 400


def test_unset_env_is_localhost_only(monkeypatch):
    client = _fresh_client(monkeypatch, None)
    for host in LOCAL:
        assert _status(client, host) == 200, host
    assert _status(client, "evil.com") == 400


@pytest.mark.parametrize("env", ["*", "demo.example.com,*"])
def test_star_still_allows_any_host(monkeypatch, env):
    client = _fresh_client(monkeypatch, env)
    assert _status(client, "anything.example.org") == 200
