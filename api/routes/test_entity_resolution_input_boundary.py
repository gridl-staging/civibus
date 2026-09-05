from __future__ import annotations

from typing import Any, get_args

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.deps import get_db
from api.main import create_app
from api.middleware import require_administrative_request
from api.models._validation import POSTGRES_SIGNED_BIGINT_MAX
from api.models.entity_resolution import EREntityType, ERClusterListParams
from api.routes import entity_resolution as entity_resolution_route_module


def _override_route_dependencies(app: FastAPI) -> None:
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[require_administrative_request] = lambda: None


def _client_with_query_spy(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, list[ERClusterListParams]]:
    calls: list[ERClusterListParams] = []

    def fake_fetch_er_cluster_list(
        _conn: object,
        params: ERClusterListParams,
    ) -> list[dict[str, Any]]:
        calls.append(params)
        return []

    monkeypatch.setattr(
        entity_resolution_route_module,
        "fetch_er_cluster_list",
        fake_fetch_er_cluster_list,
    )
    app = create_app()
    _override_route_dependencies(app)
    return TestClient(app), calls


def test_er_cluster_list_rejects_postgres_offset_overflow_before_query_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, query_calls = _client_with_query_spy(monkeypatch)

    response = client.get(
        "/v1/er/clusters",
        params={
            "entity_type": "person",
            "limit": 200,
            "offset": POSTGRES_SIGNED_BIGINT_MAX + 1,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "offset"]
    assert query_calls == []


def test_er_cluster_list_accepts_inclusive_postgres_offset_maximum_without_input_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, query_calls = _client_with_query_spy(monkeypatch)

    response = client.get(
        "/v1/er/clusters",
        params={
            "entity_type": "organization",
            "limit": 1,
            "offset": POSTGRES_SIGNED_BIGINT_MAX,
        },
    )

    assert response.status_code == 200
    assert response.json() == []
    assert query_calls == [
        ERClusterListParams(
            entity_type="organization",
            limit=1,
            offset=POSTGRES_SIGNED_BIGINT_MAX,
        )
    ]


def test_er_cluster_list_model_bounds_offset_to_postgres_signed_bigint() -> None:
    assert ERClusterListParams(offset=POSTGRES_SIGNED_BIGINT_MAX).offset == POSTGRES_SIGNED_BIGINT_MAX

    with pytest.raises(ValidationError) as exc_info:
        ERClusterListParams(offset=POSTGRES_SIGNED_BIGINT_MAX + 1)

    assert exc_info.value.errors()[0]["loc"] == ("offset",)


def test_er_cluster_list_openapi_declares_existing_filters_and_postgres_offset_boundary() -> None:
    parameters = {
        parameter["name"]: parameter["schema"]
        for parameter in create_app().openapi()["paths"]["/v1/er/clusters"]["get"]["parameters"]
    }

    assert parameters["entity_type"]["anyOf"][0]["enum"] == list(get_args(EREntityType))
    assert parameters["limit"]["minimum"] == 1
    assert parameters["limit"]["maximum"] == 200
    assert parameters["offset"]["minimum"] == 0
    assert parameters["offset"]["maximum"] == POSTGRES_SIGNED_BIGINT_MAX
