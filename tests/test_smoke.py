from fastapi.testclient import TestClient

from cubesat import __version__
from cubesat.api import app


def test_version_present():
    assert __version__


def test_health_endpoint():
    """INTENTIONAL CONTRACT CHANGE (BACKEND_SPEC section 8.1): /health is
    enriched for G5 -- status ok plus mode/sim_time/scenario/paused."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert set(body) == {"status", "mode", "sim_time", "scenario", "paused"}
