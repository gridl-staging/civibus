from __future__ import annotations

from typing import Any, get_args

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.deps import get_db
from api.main import create_app
from api.middleware import require_authorized_request
from api.models._validation import POSTGRES_SIGNED_BIGINT_MAX
from api.models.search import SEARCH_QUERY_MAX_LENGTH, SearchEntityType, SearchParams
from api.routes import search as search_route_module


def _override_route_dependencies(app: FastAPI) -> None:
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[require_authorized_request] = lambda: None


def _client_with_query_spy(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, list[SearchParams]]:
    calls: list[SearchParams] = []

    def fake_fetch_search_results(_conn: object, params: SearchParams) -> dict[str, Any]:
        calls.append(params)
        return {"items": [], "has_next": False}

    monkeypatch.setattr(search_route_module, "fetch_search_results", fake_fetch_search_results)
    app = create_app()
    _override_route_dependencies(app)
    return TestClient(app), calls


def test_search_rejects_postgres_offset_overflow_before_query_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, query_calls = _client_with_query_spy(monkeypatch)

    response = client.get(
        "/v1/search",
        params={"q": "civ", "entity_type": "org", "limit": 100, "offset": POSTGRES_SIGNED_BIGINT_MAX + 1},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "offset"]
    assert query_calls == []


def test_search_accepts_inclusive_postgres_offset_maximum_without_input_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, query_calls = _client_with_query_spy(monkeypatch)

    response = client.get(
        "/v1/search",
        params={"q": "civ", "entity_type": "org", "limit": 100, "offset": POSTGRES_SIGNED_BIGINT_MAX},
    )

    assert response.status_code == 200
    assert response.json() == {"items": [], "has_next": False}
    assert query_calls == [SearchParams(q="civ", entity_type="org", limit=100, offset=POSTGRES_SIGNED_BIGINT_MAX)]


def test_search_model_bounds_offset_to_postgres_signed_bigint() -> None:
    assert SearchParams(q="civ", offset=POSTGRES_SIGNED_BIGINT_MAX).offset == POSTGRES_SIGNED_BIGINT_MAX

    with pytest.raises(ValidationError) as exc_info:
        SearchParams(q="civ", offset=POSTGRES_SIGNED_BIGINT_MAX + 1)

    assert exc_info.value.errors()[0]["loc"] == ("offset",)


def test_search_openapi_declares_postgres_offset_boundary() -> None:
    parameters = {
        parameter["name"]: parameter["schema"]
        for parameter in create_app().openapi()["paths"]["/v1/search"]["get"]["parameters"]
    }

    assert parameters["q"]["minLength"] == 2
    assert parameters["q"]["maxLength"] == SEARCH_QUERY_MAX_LENGTH
    assert parameters["entity_type"]["anyOf"][0]["enum"] == list(get_args(SearchEntityType))
    assert parameters["limit"]["minimum"] == 1
    assert parameters["limit"]["maximum"] == 100
    assert parameters["offset"]["minimum"] == 0
    assert parameters["offset"]["maximum"] == POSTGRES_SIGNED_BIGINT_MAX
