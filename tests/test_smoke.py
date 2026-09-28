from fastapi.testclient import TestClient

from cubesat import __version__
from cubesat.api import app


def test_version_present():
    assert __version__


def test_health_endpoint():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
