from __future__ import annotations

from collections.abc import Callable, Iterator
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.routes.campaign_finance as campaign_finance_routes
from api.deps import get_db


_DETAIL_ERROR_MESSAGE = "Campaign-finance detail unavailable"
_DETAIL_ERROR_DESCRIPTION = "The stored campaign-finance detail does not satisfy the public response contract."
_CORRUPT_STORED_VALUE = "private-corrupt-value-must-not-escape"


def _committee_row() -> dict[str, object]:
    return {
        "id": UUID("cf100000-0000-0000-0000-000000000001"),
        "fec_committee_id": "C10000001",
        "name": {"invalid": _CORRUPT_STORED_VALUE},
        "slug": "invalid-committee",
        "slug_is_unique": True,
        "organization_id": None,
        "source_record_id": None,
    }


def _candidate_row() -> dict[str, object]:
    return {
        "id": UUID("cf100000-0000-0000-0000-000000000002"),
        "fec_candidate_id": "H0NC10002",
        "name": "Invalid Candidate",
        "slug": "invalid-candidate",
        "slug_is_unique": True,
        "identity_is_safe": True,
        "has_official_total": False,
        "office": {"invalid": _CORRUPT_STORED_VALUE},
        "person_id": None,
        "source_record_id": None,
    }


def _filing_row() -> dict[str, object]:
    return {
        "id": UUID("cf100000-0000-0000-0000-000000000003"),
        "filing_fec_id": {"invalid": _CORRUPT_STORED_VALUE},
        "committee_id": UUID("cf100000-0000-0000-0000-000000000004"),
        "amendment_indicator": "N",
        "is_amended": False,
        "source_record_id": None,
        "fallback_committee_source_record_id": None,
        "fallback_committee_organization_id": None,
    }


_DETAIL_CASES = (
    ("/v1/committees/cf100000-0000-0000-0000-000000000001", _committee_row),
    ("/v1/candidates/cf100000-0000-0000-0000-000000000002", _candidate_row),
    ("/v1/filings/cf100000-0000-0000-0000-000000000003", _filing_row),
)


@pytest.fixture
def campaign_finance_detail_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(campaign_finance_routes.router, prefix="/v1")
    app.dependency_overrides[get_db] = lambda: object()

    monkeypatch.setattr(campaign_finance_routes, "fetch_campaign_finance_provenance", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(campaign_finance_routes, "fetch_committee_linked_candidates", lambda *_args, **_kwargs: [])

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.mark.parametrize(("path", "row_factory"), _DETAIL_CASES, ids=("committee", "candidate", "filing"))
def test_invalid_stored_campaign_finance_detail_returns_sanitized_json_and_remains_observable(
    path: str,
    row_factory: Callable[[], dict[str, object]],
    campaign_finance_detail_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_exception_types: list[str] = []
    monkeypatch.setattr(
        campaign_finance_routes,
        "record_handled_exception_type",
        lambda _request, exception: observed_exception_types.append(type(exception).__name__),
        raising=False,
    )
    monkeypatch.setattr(
        campaign_finance_routes,
        "fetch_one_row",
        lambda *_args, **_kwargs: row_factory(),
    )

    response = campaign_finance_detail_client.get(path)

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": _DETAIL_ERROR_MESSAGE}
    assert _CORRUPT_STORED_VALUE not in response.text
    assert "validation" not in response.text.lower()
    assert observed_exception_types == ["ValidationError"]


@pytest.mark.parametrize(
    "path",
    (
        "/v1/committees/{committee_id}",
        "/v1/candidates/{candidate_id}",
        "/v1/filings/{filing_id}",
    ),
)
def test_campaign_finance_detail_openapi_documents_sanitized_stored_record_failure(path: str) -> None:
    app = FastAPI()
    app.include_router(campaign_finance_routes.router, prefix="/v1")

    openapi = app.openapi()
    response = openapi["paths"][path]["get"]["responses"]["500"]

    assert response["description"] == _DETAIL_ERROR_DESCRIPTION
    assert response["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/CampaignFinanceDetailErrorResponse"
    }
    error_schema = openapi["components"]["schemas"]["CampaignFinanceDetailErrorResponse"]
    assert error_schema["required"] == ["detail"]
    assert error_schema["additionalProperties"] is False
    assert error_schema["properties"]["detail"]["const"] == _DETAIL_ERROR_MESSAGE
