"""GET /healthz answers 200 without touching the bridge — Docker healthcheck target."""

from starlette.testclient import TestClient

from enphase_bridge_mcp.server import app


def test_healthz_returns_ok() -> None:
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
