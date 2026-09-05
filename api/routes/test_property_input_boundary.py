from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.deps import get_db
from api.main import create_app
from api.middleware import require_authorized_request
from api.models._validation import POSTGRES_SIGNED_BIGINT_MAX
from api.models.property import ParcelListParams
from api.routes import property as property_route_module


def _client_with_query_spy(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, list[ParcelListParams]]:
    calls: list[ParcelListParams] = []

    def fake_fetch_parcel_list(_conn: object, params: ParcelListParams) -> list[dict[str, Any]]:
        calls.append(params)
        return []

    monkeypatch.setattr(property_route_module, "fetch_parcel_list", fake_fetch_parcel_list)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[require_authorized_request] = lambda: None
    return TestClient(app), calls


def test_parcel_list_rejects_postgres_offset_overflow_before_query_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, query_calls = _client_with_query_spy(monkeypatch)

    response = client.get("/v1/parcels", params={"offset": POSTGRES_SIGNED_BIGINT_MAX + 1})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "offset"]
    assert query_calls == []


def test_parcel_list_accepts_inclusive_postgres_offset_maximum_without_input_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, query_calls = _client_with_query_spy(monkeypatch)

    response = client.get(
        "/v1/parcels",
        params={"city": "Durham", "limit": 1, "offset": POSTGRES_SIGNED_BIGINT_MAX},
    )

    assert response.status_code == 200
    assert response.json() == []
    assert query_calls == [ParcelListParams(city="Durham", limit=1, offset=POSTGRES_SIGNED_BIGINT_MAX)]


def test_parcel_list_model_bounds_offset_to_postgres_signed_bigint() -> None:
    assert ParcelListParams(offset=POSTGRES_SIGNED_BIGINT_MAX).offset == POSTGRES_SIGNED_BIGINT_MAX

    with pytest.raises(ValidationError) as exc_info:
        ParcelListParams(offset=POSTGRES_SIGNED_BIGINT_MAX + 1)

    assert exc_info.value.errors()[0]["loc"] == ("offset",)


def test_parcel_list_openapi_declares_postgres_offset_boundary() -> None:
    parameters = {
        parameter["name"]: parameter["schema"]
        for parameter in create_app().openapi()["paths"]["/v1/parcels"]["get"]["parameters"]
    }

    assert parameters["limit"]["minimum"] == 1
    assert parameters["limit"]["maximum"] == 200
    assert parameters["offset"]["minimum"] == 0
    assert parameters["offset"]["maximum"] == POSTGRES_SIGNED_BIGINT_MAX
