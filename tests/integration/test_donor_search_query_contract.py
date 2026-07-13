from __future__ import annotations

from datetime import date
from decimal import Decimal

import psycopg
import pytest

from api.queries.campaign_finance import search_donors
from test_support.donor_search_fixture import seed_donor_search_fixture

pytestmark = pytest.mark.integration


def test_search_donors_name_mode_preserves_exact_rollups_and_nested_order(
    db_conn: psycopg.Connection,
) -> None:
    fixture = seed_donor_search_fixture(db_conn)

    payload = search_donors(db_conn, q="sMiTh", by="name", limit=5, offset=0)

    assert payload["query"] == "sMiTh"
    assert payload["by"] == "name"
    assert payload["limit"] == 5
    assert payload["offset"] == 0
    assert [result["id"] for result in payload["results"]] == [
        "72000000-0000-0000-0000-000000000101",
        "72000000-0000-0000-0000-000000000103",
    ]
    assert [result["contributor_name"] for result in payload["results"]] == ["JANE SMITH", "JOHN SMITH"]

    jane = payload["results"][0]
    assert jane["contributor_employer"] == "Civibus Labs"
    assert jane["contributor_occupation"] == "Engineer"
    assert jane["contributor_city"] == "Durham"
    assert jane["contributor_state"] == "NC"
    assert jane["normalized_zip5"] == "27701"
    assert jane["total_amount"] == Decimal("500.00")
    assert jane["transaction_count"] == 3
    assert jane["latest_transaction_date"] == date(2024, 7, 15)
    assert jane["recipients"] == [
        {
            "person_id": fixture.alpha.person_id,
            "candidate_id": fixture.alpha.candidate_id,
            "fec_candidate_id": "H0NC01001",
            "candidate_name": "Alpha Officeholder",
            "committee_id": fixture.alpha.committee_id,
            "fec_committee_id": "C72000001",
            "committee_name": "Alpha Officeholder Committee",
            "total_amount": Decimal("375.00"),
            "transaction_count": 2,
        },
        {
            "person_id": fixture.beta.person_id,
            "candidate_id": fixture.beta.candidate_id,
            "fec_candidate_id": "S0NC00002",
            "candidate_name": "Beta Officeholder",
            "committee_id": fixture.beta.committee_id,
            "fec_committee_id": "C72000002",
            "committee_name": "Beta Officeholder Committee",
            "total_amount": Decimal("125.00"),
            "transaction_count": 1,
        },
    ]
    assert [
        (source["source_record_key"], source["record_url"], source["pull_date"].isoformat())
        for source in jane["sources"]
    ] == [
        (
            "donor-search-current",
            "https://example.org/fec/donor-search/current",
            "2026-07-09T12:00:00+00:00",
        ),
        (
            "donor-search-secondary",
            "https://example.org/fec/donor-search/secondary",
            "2026-07-09T11:00:00+00:00",
        ),
    ]

    john = payload["results"][1]
    assert john["id"] == "72000000-0000-0000-0000-000000000103"
    assert john["total_amount"] == Decimal("425.00")
    assert john["transaction_count"] == 1
    assert john["latest_transaction_date"] == date(2025, 1, 15)
    assert [recipient["person_id"] for recipient in john["recipients"]] == [fixture.alpha.person_id]
    assert [source["source_record_key"] for source in john["sources"]] == ["donor-search-current"]


def test_search_donors_zip_mode_and_page_two_continuation_preserve_exact_contract(
    db_conn: psycopg.Connection,
) -> None:
    fixture = seed_donor_search_fixture(db_conn)

    zip_payload = search_donors(db_conn, q="27701-1234", by="zip", limit=5, offset=0)
    page_two_payload = search_donors(db_conn, q="smith", by="name", limit=1, offset=1)

    assert zip_payload["query"] == "27701-1234"
    assert zip_payload["by"] == "zip"
    assert zip_payload["limit"] == 5
    assert zip_payload["offset"] == 0
    assert [result["id"] for result in zip_payload["results"]] == ["72000000-0000-0000-0000-000000000101"]
    assert zip_payload["results"][0]["normalized_zip5"] == "27701"
    assert zip_payload["results"][0]["total_amount"] == Decimal("500.00")
    assert zip_payload["results"][0]["transaction_count"] == 3
    assert [recipient["person_id"] for recipient in zip_payload["results"][0]["recipients"]] == [
        fixture.alpha.person_id,
        fixture.beta.person_id,
    ]
    assert [source["source_record_key"] for source in zip_payload["results"][0]["sources"]] == [
        "donor-search-current",
        "donor-search-secondary",
    ]

    assert page_two_payload["query"] == "smith"
    assert page_two_payload["by"] == "name"
    assert page_two_payload["limit"] == 1
    assert page_two_payload["offset"] == 1
    assert [result["id"] for result in page_two_payload["results"]] == ["72000000-0000-0000-0000-000000000103"]
    assert page_two_payload["results"][0]["contributor_name"] == "JOHN SMITH"
    assert page_two_payload["results"][0]["total_amount"] == Decimal("425.00")
    assert page_two_payload["results"][0]["transaction_count"] == 1
