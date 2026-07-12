from __future__ import annotations

from decimal import Decimal

import psycopg
import pytest
from fastapi.testclient import TestClient

from api.deps import get_db
from api.main import create_app
from test_support.donor_search_fixture import DONOR_SEARCH_ALPHA_PERSON_ID, seed_donor_search_fixture

pytestmark = pytest.mark.integration


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
    assert len(payload["results"]) == 1

    jane = payload["results"][0]
    assert jane["recipients"][0]["person_id"] == str(DONOR_SEARCH_ALPHA_PERSON_ID)
    assert jane == {
        "id": "72000000-0000-0000-0000-000000000101",
        "contributor_name": "JANE SMITH",
        "contributor_employer": "Civibus Labs",
        "contributor_occupation": "Engineer",
        "contributor_city": "Durham",
        "contributor_state": "NC",
        "normalized_zip5": "27701",
        "total_amount": "500.00",
        "transaction_count": 3,
        "latest_transaction_date": "2024-07-15",
        "recipients": [
            {
                "person_id": str(fixture.alpha.person_id),
                "candidate_id": str(fixture.alpha.candidate_id),
                "fec_candidate_id": "H0NC01001",
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
