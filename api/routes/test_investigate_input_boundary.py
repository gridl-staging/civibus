from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.deps import get_db
from api.main import create_app
from api.middleware import require_authorized_request
from api.models._validation import POSTGRES_SIGNED_BIGINT_MAX
from api.models.investigate import DonorsWithPropertyParams
from api.routes import investigate as investigate_route_module


def _client_with_query_spy(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, list[DonorsWithPropertyParams]]:
    query_calls: list[DonorsWithPropertyParams] = []

    def fake_fetch_donors_with_property(
        _conn: object,
        params: DonorsWithPropertyParams,
    ) -> list[dict[str, Any]]:
        query_calls.append(params)
        return []

    monkeypatch.setattr(
        investigate_route_module,
        "fetch_donors_with_property",
        fake_fetch_donors_with_property,
    )
    app = create_app()
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[require_authorized_request] = lambda: None
    return TestClient(app), query_calls


def test_investigate_model_bounds_offset_to_postgres_signed_bigint() -> None:
    assert DonorsWithPropertyParams(offset=POSTGRES_SIGNED_BIGINT_MAX).offset == POSTGRES_SIGNED_BIGINT_MAX

    with pytest.raises(ValidationError) as exc_info:
        DonorsWithPropertyParams(offset=POSTGRES_SIGNED_BIGINT_MAX + 1)

    assert exc_info.value.errors()[0]["loc"] == ("offset",)


def test_investigate_rejects_postgres_offset_overflow_before_query_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, query_calls = _client_with_query_spy(monkeypatch)

    response = client.get(
        "/v1/investigate/donors-with-property",
        params={"offset": POSTGRES_SIGNED_BIGINT_MAX + 1},
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {
                "type": "less_than_equal",
                "loc": ["query", "offset"],
                "msg": f"Input should be less than or equal to {POSTGRES_SIGNED_BIGINT_MAX}",
                "input": str(POSTGRES_SIGNED_BIGINT_MAX + 1),
                "ctx": {"le": POSTGRES_SIGNED_BIGINT_MAX},
            }
        ]
    }
    assert query_calls == []


def test_investigate_preserves_filter_limit_and_inclusive_postgres_offset_maximum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, query_calls = _client_with_query_spy(monkeypatch)

    response = client.get(
        "/v1/investigate/donors-with-property",
        params={
            "jurisdiction": "state/nc",
            "limit": 17,
            "offset": POSTGRES_SIGNED_BIGINT_MAX,
        },
    )

    assert response.status_code == 200
    assert response.json() == []
    assert query_calls == [
        DonorsWithPropertyParams(
            jurisdiction="state/nc",
            limit=17,
            offset=POSTGRES_SIGNED_BIGINT_MAX,
        )
    ]


def test_investigate_openapi_declares_existing_query_contract_and_postgres_offset_boundary() -> None:
    parameters = {
        parameter["name"]: parameter
        for parameter in create_app().openapi()["paths"]["/v1/investigate/donors-with-property"]["get"]["parameters"]
    }

    assert parameters["jurisdiction"]["in"] == "query"
    assert parameters["jurisdiction"]["required"] is False
    assert parameters["jurisdiction"]["schema"]["anyOf"] == [
        {"type": "string"},
        {"type": "null"},
    ]
    assert parameters["limit"]["schema"]["default"] == 50
    assert parameters["limit"]["schema"]["minimum"] == 1
    assert parameters["limit"]["schema"]["maximum"] == 200
    assert parameters["offset"]["schema"]["default"] == 0
    assert parameters["offset"]["schema"]["minimum"] == 0
    assert parameters["offset"]["schema"]["maximum"] == POSTGRES_SIGNED_BIGINT_MAX
