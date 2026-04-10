from __future__ import annotations

from fastapi import APIRouter
import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from api.deps import get_db
from api.main import create_app
from api.middleware import require_authorized_request


def _build_probe_router(path: str, router_name: str) -> APIRouter:
    router = APIRouter()

    @router.get(path)
    def probe() -> dict[str, str]:
        return {"router": router_name}

    return router


def test_health_endpoint_is_public_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIVIBUS_ENV", "production")
    monkeypatch.setenv("CIVIBUS_API_KEYS", "public-health-key")

    client = TestClient(create_app())
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize("api_key", [None, "not-configured"])
def test_v1_routes_reject_missing_or_invalid_api_key(
    monkeypatch: pytest.MonkeyPatch,
    api_key: str | None,
) -> None:
    monkeypatch.setenv("CIVIBUS_ENV", "production")
    monkeypatch.setenv("CIVIBUS_API_KEYS", "valid-key-1,valid-key-2")

    request_headers = {} if api_key is None else {"X-API-Key": api_key}

    client = TestClient(create_app())
    response = client.get("/v1/search", params={"q": "civ"}, headers=request_headers)

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing API key"}


def test_valid_api_key_reaches_route_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIVIBUS_ENV", "production")
    monkeypatch.setenv("CIVIBUS_API_KEYS", "valid-key")

    app = create_app()
    app.dependency_overrides[get_db] = lambda: object()
    client = TestClient(app)
    response = client.get("/v1/person/not-a-uuid", headers={"X-API-Key": "valid-key"})

    assert response.status_code != 401


def test_dependency_override_can_bypass_auth_for_test_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIVIBUS_ENV", "production")
    monkeypatch.setenv("CIVIBUS_API_KEYS", "valid-key")

    app = create_app()
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[require_authorized_request] = lambda: None
    client = TestClient(app)
    response = client.get("/v1/person/not-a-uuid")

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["path", "person_id"]


def test_development_without_api_keys_leaves_v1_routes_reachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CIVIBUS_ENV", "development")
    monkeypatch.delenv("CIVIBUS_API_KEYS", raising=False)

    app = create_app()
    app.dependency_overrides[get_db] = lambda: object()
    client = TestClient(app)
    response = client.get("/v1/person/not-a-uuid")

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["path", "person_id"]


@pytest.mark.parametrize("configured_keys", [None, "", "  ,  "])
def test_startup_fails_outside_development_when_api_keys_missing(
    monkeypatch: pytest.MonkeyPatch,
    configured_keys: str | None,
) -> None:
    monkeypatch.setenv("CIVIBUS_ENV", "production")
    if configured_keys is None:
        monkeypatch.delenv("CIVIBUS_API_KEYS", raising=False)
    else:
        monkeypatch.setenv("CIVIBUS_API_KEYS", configured_keys)

    with pytest.raises(RuntimeError, match="CIVIBUS_API_KEYS"):
        create_app()


def test_entity_resolution_routes_require_admin_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIVIBUS_ENV", "production")
    monkeypatch.setenv("CIVIBUS_API_KEYS", "public-key")
    monkeypatch.setenv("CIVIBUS_ADMIN_API_KEYS", "admin-key")
    monkeypatch.setattr(api_main, "entities_router", _build_probe_router("/public-probe", "public"))
    monkeypatch.setattr(api_main, "campaign_finance_router", APIRouter())
    monkeypatch.setattr(api_main, "property_router", APIRouter())
    monkeypatch.setattr(api_main, "graph_router", APIRouter())
    monkeypatch.setattr(api_main, "search_router", APIRouter())
    monkeypatch.setattr(api_main, "entity_resolution_router", _build_probe_router("/admin-probe", "admin"))

    client = TestClient(create_app())

    public_response = client.get("/v1/public-probe", headers={"X-API-Key": "public-key"})
    forbidden_admin_response = client.get("/v1/admin-probe", headers={"X-API-Key": "public-key"})
    authorized_admin_response = client.get("/v1/admin-probe", headers={"X-API-Key": "admin-key"})

    assert public_response.status_code == 200
    assert forbidden_admin_response.status_code == 401
    assert forbidden_admin_response.json() == {"detail": "Invalid or missing API key"}
    assert authorized_admin_response.status_code == 200
