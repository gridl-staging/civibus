from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.deps import get_db
from api.main import create_app
from api.models import DonorSearchResponse
from api.queries.campaign_finance import DonorSearchRollupUnavailableError
from test_support.donor_search_fixture import DONOR_SEARCH_ALPHA_PERSON_ID, seed_donor_search_fixture

pytestmark = pytest.mark.integration

_RESOLVED_IDENTITY_ID = UUID("72100000-0000-0000-0000-000000000001")
_POSSIBLE_IDENTITY_ID = UUID("72100000-0000-0000-0000-000000000003")
_IDENTITY_PULL_DATE = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)


def _identity_source() -> dict[str, object]:
    return {
        "domain": "campaign_finance",
        "jurisdiction": "federal/fec",
        "data_source_name": "FEC filing",
        "data_source_url": "https://www.fec.gov/data/",
        "source_record_key": "filing-1",
        "record_url": "https://www.fec.gov/data/receipts/?data_type=processed",
        "pull_date": _IDENTITY_PULL_DATE,
    }


def _resolved_identity_query_result(source: dict[str, object]) -> dict[str, object]:
    return {
        "id": UUID("72100000-0000-0000-0000-000000000101"),
        "donor_identity_id": _RESOLVED_IDENTITY_ID,
        "contributor_name": "TRANSPARENT IDENTITY",
        "contributor_employer": "Civibus Labs",
        "contributor_occupation": "Engineer",
        "contributor_city": "Durham",
        "contributor_state": "NC",
        "normalized_zip5": "27701",
        "total_amount": Decimal("200.00"),
        "transaction_count": 2,
        "latest_transaction_date": "2025-06-02",
        "combined_record_count": 2,
        "confidence_band": "match",
        "recipients": [],
        "sources": [source],
        "underlying_records": [
            {
                "donor_identity_id": _RESOLVED_IDENTITY_ID,
                "contributor_name": "TRANSPARENT IDENTITY",
                "contributor_employer": "Civibus Labs",
                "contributor_occupation": "Engineer",
                "contributor_city": "Durham",
                "contributor_state": "NC",
                "normalized_zip5": "27701",
                "sources": [source],
            },
            {
                "donor_identity_id": UUID("72100000-0000-0000-0000-000000000002"),
                "contributor_name": "TRANSPARENT IDENTITY ALT",
                "contributor_employer": "Open Civic Works",
                "contributor_occupation": "Architect",
                "contributor_city": "Raleigh",
                "contributor_state": "NC",
                "normalized_zip5": "27601",
                "sources": [source],
            },
        ],
        "not_combined_candidates": [
            {
                "donor_identity_id": _POSSIBLE_IDENTITY_ID,
                "contributor_name": "POSSIBLE IDENTITY",
                "contributor_employer": "Civibus Labs",
                "contributor_occupation": "Analyst",
                "contributor_city": "Chapel Hill",
                "contributor_state": "NC",
                "normalized_zip5": "27514",
                "confidence_band": "possible_match",
                "sources": [source],
            }
        ],
    }


def _unresolved_identity_query_result(source: dict[str, object]) -> dict[str, object]:
    return {
        "id": UUID("72000000-0000-0000-0000-000000000101"),
        "donor_identity_id": None,
        "contributor_name": "JANE SMITH",
        "contributor_employer": "Civibus Labs",
        "contributor_occupation": "Engineer",
        "contributor_city": "Durham",
        "contributor_state": "NC",
        "normalized_zip5": "27701",
        "total_amount": Decimal("500.00"),
        "transaction_count": 3,
        "latest_transaction_date": "2024-07-15",
        "combined_record_count": 1,
        "confidence_band": None,
        "recipients": [],
        "sources": [source],
        "underlying_records": [],
        "not_combined_candidates": [],
    }


def _serialized_source(source: dict[str, object]) -> dict[str, object]:
    return {**source, "pull_date": "2026-07-09T12:00:00Z"}


def _resolved_identity_json(
    query_result: dict[str, object],
    source: dict[str, object],
) -> dict[str, object]:
    underlying_records = query_result["underlying_records"]
    candidates = query_result["not_combined_candidates"]
    assert isinstance(underlying_records, list)
    assert isinstance(candidates, list)
    return {
        **query_result,
        "id": "72100000-0000-0000-0000-000000000101",
        "donor_identity_id": str(_RESOLVED_IDENTITY_ID),
        "total_amount": "200.00",
        "sources": [_serialized_source(source)],
        "underlying_records": [
            {
                **underlying_records[0],
                "donor_identity_id": str(_RESOLVED_IDENTITY_ID),
                "sources": [_serialized_source(source)],
            },
            {
                **underlying_records[1],
                "donor_identity_id": "72100000-0000-0000-0000-000000000002",
                "sources": [_serialized_source(source)],
            },
        ],
        "not_combined_candidates": [
            {
                **candidates[0],
                "donor_identity_id": str(_POSSIBLE_IDENTITY_ID),
                "sources": [_serialized_source(source)],
            }
        ],
    }


def test_donor_search_route_serializes_identity_transparency_payload_exactly(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _identity_source()
    resolved = _resolved_identity_query_result(source)
    unresolved = _unresolved_identity_query_result(source)
    query_payload = {
        "query": "identity",
        "by": "name",
        "limit": 20,
        "offset": 0,
        "rollup_completed_at": "2026-07-17T12:00:00Z",
        "results": [resolved, unresolved],
    }
    monkeypatch.setattr("api.routes.donors.search_donors", lambda *_args, **_kwargs: query_payload)

    response = api_client.get("/v1/donors/search", params={"q": "identity", "by": "name"})

    assert response.status_code == 200
    assert response.json() == {
        **query_payload,
        "results": [
            _resolved_identity_json(resolved, source),
            {
                **unresolved,
                "id": "72000000-0000-0000-0000-000000000101",
                "total_amount": "500.00",
                "sources": [_serialized_source(source)],
            },
        ],
    }


def test_donor_search_response_rejects_success_without_rollup_timestamp() -> None:
    query_payload = {
        "query": "identity",
        "by": "name",
        "limit": 20,
        "offset": 0,
        "rollup_completed_at": None,
        "results": [],
    }
    with pytest.raises(ValidationError, match="rollup_completed_at"):
        DonorSearchResponse.model_validate(query_payload)


def test_donor_search_route_returns_seeded_name_payload(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    fixture = seed_donor_search_fixture(db_conn)

    response = api_client.get("/v1/donors/search", params={"q": "JANE", "by": "name", "limit": 5})

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "JANE"
    assert payload["by"] == "name"
    assert payload["limit"] == 5
    assert payload["offset"] == 0
    assert payload["rollup_completed_at"] is not None
    assert len(payload["results"]) == 1

    jane = payload["results"][0]
    assert jane["recipients"][0]["person_id"] == str(DONOR_SEARCH_ALPHA_PERSON_ID)
    assert jane == {
        "id": "72000000-0000-0000-0000-000000000101",
        "donor_identity_id": None,
        "contributor_name": "JANE SMITH",
        "contributor_employer": "Civibus Labs",
        "contributor_occupation": "Engineer",
        "contributor_city": "Durham",
        "contributor_state": "NC",
        "normalized_zip5": "27701",
        "total_amount": "500.00",
        "transaction_count": 3,
        "latest_transaction_date": "2024-07-15",
        "combined_record_count": 1,
        "confidence_band": None,
        "recipients": [
            {
                "person_id": str(fixture.alpha.person_id),
                "candidate_id": str(fixture.alpha.candidate_id),
                "fec_candidate_id": "H9NC72001",
                "candidate_name": "Alpha Officeholder",
                "committee_id": str(fixture.alpha.committee_id),
                "fec_committee_id": "C72000001",
                "committee_name": "Alpha Officeholder Committee",
                "total_amount": "375.00",
                "transaction_count": 2,
            },
            {
                "person_id": str(fixture.beta.person_id),
                "candidate_id": str(fixture.beta.candidate_id),
                "fec_candidate_id": "S0NC00002",
                "candidate_name": "Beta Officeholder",
                "committee_id": str(fixture.beta.committee_id),
                "fec_committee_id": "C72000002",
                "committee_name": "Beta Officeholder Committee",
                "total_amount": "125.00",
                "transaction_count": 1,
            },
        ],
        "sources": [
            {
                "domain": "campaign_finance",
                "jurisdiction": "federal/fec",
                "data_source_name": "Campaign Finance API Source donor-search-fixture",
                "data_source_url": "https://example.org/campaign-finance-source",
                "source_record_key": "donor-search-current",
                "record_url": "https://example.org/fec/donor-search/current",
                "pull_date": "2026-07-09T12:00:00Z",
            },
            {
                "domain": "campaign_finance",
                "jurisdiction": "federal/fec",
                "data_source_name": "Campaign Finance API Source donor-search-fixture",
                "data_source_url": "https://example.org/campaign-finance-source",
                "source_record_key": "donor-search-secondary",
                "record_url": "https://example.org/fec/donor-search/secondary",
                "pull_date": "2026-07-09T11:00:00Z",
            },
        ],
        "underlying_records": [],
        "not_combined_candidates": [],
    }


@pytest.mark.parametrize(
    "reason",
    [
        "missing_provenance",
        "stale_provenance",
        "future_provenance_timestamp",
        "malformed_provenance_timestamp",
        "donor_key_fingerprint_mismatch",
    ],
)
def test_donor_search_route_translates_rollup_unavailable_to_service_response(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
) -> None:
    def raise_unavailable(*_args: object, **_kwargs: object) -> None:
        raise DonorSearchRollupUnavailableError(reason)

    monkeypatch.setattr("api.routes.donors.search_donors", raise_unavailable)

    response = api_client.get("/v1/donors/search", params={"q": "smith", "by": "name"})

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "code": "donor_search_rollup_unavailable",
        }
    }


@pytest.mark.parametrize(
    ("params", "expected_detail"),
    [
        ({"q": "smith", "by": "committee"}, "Unsupported donor search mode"),
        ({"q": "ja", "by": "name"}, "at least 3 characters"),
        ({"q": "ab", "by": "employer"}, "at least 3 characters"),
        ({"q": "27A01", "by": "zip"}, "5-digit ZIP"),
    ],
)
def test_donor_search_route_translates_query_validation_to_422(
    api_client: TestClient,
    db_conn: psycopg.Connection,
    params: dict[str, str],
    expected_detail: str,
) -> None:
    seed_donor_search_fixture(db_conn)

    response = api_client.get("/v1/donors/search", params=params)

    assert response.status_code == 422
    assert expected_detail in response.json()["detail"]


def test_donor_search_route_preserves_query_limit_clamp(
    api_client: TestClient,
    db_conn: psycopg.Connection,
) -> None:
    seed_donor_search_fixture(db_conn, extra_smith_rows=55)

    response = api_client.get("/v1/donors/search", params={"q": "smith", "by": "name", "limit": 500})

    assert response.status_code == 200
    payload = response.json()
    assert payload["limit"] == 50
    assert len(payload["results"]) == 50
    assert Decimal(payload["results"][0]["total_amount"]) == Decimal("500.00")


@pytest.mark.parametrize("api_key", [None, "wrong-key"])
def test_donor_search_route_requires_v1_api_key(
    monkeypatch: pytest.MonkeyPatch,
    db_conn: psycopg.Connection,
    api_key: str | None,
) -> None:
    monkeypatch.setenv("CIVIBUS_ENV", "production")
    monkeypatch.setenv("CIVIBUS_API_KEYS", "test-key")

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_conn
    request_headers = {} if api_key is None else {"X-API-Key": api_key}

    with TestClient(app) as client:
        response = client.get("/v1/donors/search", params={"q": "JANE", "by": "name"}, headers=request_headers)

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing API key"}
