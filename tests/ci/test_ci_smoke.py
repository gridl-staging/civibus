"""DB-free CI canary tests."""

from fastapi.testclient import TestClient

from api.main import create_app


def test_ci_canary_health_check() -> None:
    """Ensure the application health endpoint is reachable in CI."""
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
