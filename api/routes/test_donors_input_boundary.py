from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps import get_db
from api.main import create_app
from api.middleware import require_authorized_request
from api.models._validation import POSTGRES_SIGNED_BIGINT_MAX
from api.queries import DonorSearchRollupUnavailableError
from api.routes import donors as donor_route_module


_DONOR_SEARCH_MAX_QUERY_LEN = 100
_DONOR_SEARCH_MAX_LIMIT = 50


def _override_route_dependencies(app: FastAPI) -> None:
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[require_authorized_request] = lambda: None


def _client_with_query_spy(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []

    def fake_search_donors(
        _conn: object,
        *,
        q: str,
        by: str,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        calls.append({"q": q, "by": by, "limit": limit, "offset": offset})
        return {
            "query": q,
            "by": by,
            "limit": limit,
            "offset": offset,
            "rollup_completed_at": datetime(2026, 8, 27, tzinfo=timezone.utc),
            "results": [],
        }

    monkeypatch.setattr("api.routes.donors.search_donors", fake_search_donors)
    app = create_app()
    _override_route_dependencies(app)
    return TestClient(app), calls


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"q": "x" * (_DONOR_SEARCH_MAX_QUERY_LEN + 1), "by": "name"}, "q"),
        ({"q": "smith", "by": "name", "limit": 0}, "limit"),
        ({"q": "smith", "by": "name", "limit": _DONOR_SEARCH_MAX_LIMIT + 1}, "limit"),
        ({"q": "smith", "by": "name", "offset": -1}, "offset"),
        ({"q": "smith", "by": "name", "offset": POSTGRES_SIGNED_BIGINT_MAX + 1}, "offset"),
    ],
)
def test_donor_search_rejects_out_of_contract_inputs_before_query_execution(
    monkeypatch: pytest.MonkeyPatch,
    params: dict[str, str | int],
    field: str,
) -> None:
    client, query_calls = _client_with_query_spy(monkeypatch)

    response = client.get("/v1/donors/search", params=params)

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", field]
    assert query_calls == []


@pytest.mark.parametrize(
    ("params", "expected_detail"),
    [
        ({"q": "ab", "by": "name"}, "Donor name searches require at least 3 characters"),
        ({"q": "smith", "by": "committee"}, "Unsupported donor search mode: committee"),
    ],
)
def test_donor_search_preserves_query_owned_semantic_422_detail(
    params: dict[str, str],
    expected_detail: str,
) -> None:
    app = create_app()
    _override_route_dependencies(app)

    response = TestClient(app).get("/v1/donors/search", params=params)

    assert response.status_code == 422
    assert response.json() == {"detail": expected_detail}


def test_donor_search_preserves_current_web_caller_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, query_calls = _client_with_query_spy(monkeypatch)

    response = client.get(
        "/v1/donors/search",
        params={"q": "Jane", "by": "name", "limit": 20, "offset": 0},
    )

    assert response.status_code == 200
    assert query_calls == [{"q": "Jane", "by": "name", "limit": 20, "offset": 0}]


def test_donor_search_accepts_inclusive_postgres_offset_maximum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, query_calls = _client_with_query_spy(monkeypatch)

    response = client.get(
        "/v1/donors/search",
        params={"q": "Jane", "by": "name", "limit": 20, "offset": POSTGRES_SIGNED_BIGINT_MAX},
    )

    assert response.status_code == 200
    assert query_calls == [{"q": "Jane", "by": "name", "limit": 20, "offset": POSTGRES_SIGNED_BIGINT_MAX}]


def test_donor_search_reuses_model_layer_postgres_offset_owner() -> None:
    assert donor_route_module.POSTGRES_SIGNED_BIGINT_MAX == POSTGRES_SIGNED_BIGINT_MAX
    assert not hasattr(donor_route_module, "_POSTGRES_OFFSET_MAX")


def test_donor_search_openapi_declares_repository_owned_input_bounds() -> None:
    schemas = {
        parameter["name"]: parameter["schema"]
        for parameter in create_app().openapi()["paths"]["/v1/donors/search"]["get"]["parameters"]
    }

    assert schemas["q"]["maxLength"] == _DONOR_SEARCH_MAX_QUERY_LEN
    assert schemas["limit"]["minimum"] == 1
    assert schemas["limit"]["maximum"] == _DONOR_SEARCH_MAX_LIMIT
    assert schemas["offset"]["minimum"] == 0
    assert schemas["offset"]["maximum"] == POSTGRES_SIGNED_BIGINT_MAX


def test_donor_search_openapi_covers_runtime_service_unavailable_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_unavailable(*_args: object, **_kwargs: object) -> None:
        raise DonorSearchRollupUnavailableError("stale_provenance")

    monkeypatch.setattr("api.routes.donors.search_donors", raise_unavailable)
    app = create_app()
    _override_route_dependencies(app)

    response = TestClient(app).get("/v1/donors/search", params={"q": "smith", "by": "name"})
    documented_responses = app.openapi()["paths"]["/v1/donors/search"]["get"]["responses"]

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "donor_search_rollup_unavailable"}}
    assert documented_responses["503"] == {
        "description": "Donor search is unavailable.",
        "content": {
            "application/json": {
                "schema": {
                    "oneOf": [
                        {
                            "type": "object",
                            "properties": {
                                "detail": {
                                    "type": "object",
                                    "properties": {
                                        "code": {
                                            "type": "string",
                                            "enum": ["donor_search_rollup_unavailable"],
                                        }
                                    },
                                    "required": ["code"],
                                    "additionalProperties": False,
                                }
                            },
                            "required": ["detail"],
                            "additionalProperties": False,
                        },
                        {
                            "type": "object",
                            "properties": {
                                "detail": {
                                    "type": "string",
                                    "enum": ["Database unavailable"],
                                }
                            },
                            "required": ["detail"],
                            "additionalProperties": False,
                        },
                    ]
                }
            }
        },
    }
    assert documented_responses["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/DonorSearchResponse"
    }
    assert documented_responses["422"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/HTTPValidationError"
    }
