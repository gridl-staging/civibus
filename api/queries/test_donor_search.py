from __future__ import annotations

from decimal import Decimal

import psycopg
import pytest

import api.queries as public_queries
import api.queries.campaign_finance as campaign_finance_queries
from test_support.donor_search_fixture import seed_donor_search_fixture

pytestmark = pytest.mark.integration


def test_search_donors_by_name_rolls_up_current_federal_recipient_activity(
    db_conn: psycopg.Connection,
) -> None:
    fixture = seed_donor_search_fixture(db_conn)

    payload = campaign_finance_queries.search_donors(db_conn, q="sMiTh", by="name", limit=20, offset=0)

    assert payload["query"] == "sMiTh"
    assert payload["by"] == "name"
    assert payload["limit"] == 20
    assert payload["offset"] == 0
    assert [row["contributor_name"] for row in payload["results"]] == ["JANE SMITH", "JOHN SMITH"]

    jane = payload["results"][0]
    assert jane["id"] == "72000000-0000-0000-0000-000000000101"
    assert jane["contributor_employer"] == "Civibus Labs"
    assert jane["contributor_occupation"] == "Engineer"
    assert jane["contributor_city"] == "Durham"
    assert jane["contributor_state"] == "NC"
    assert jane["normalized_zip5"] == "27701"
    assert jane["total_amount"] == Decimal("500.00")
    assert jane["transaction_count"] == 3
    assert jane["latest_transaction_date"].isoformat() == "2024-07-15"
    assert jane["recipients"] == [
        {
            "person_id": fixture.alpha.person_id,
            "candidate_id": fixture.alpha.candidate_id,
            "fec_candidate_id": "H9NC72001",
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
        (source["source_record_key"], source["data_source_name"], source["record_url"]) for source in jane["sources"]
    ] == [
        (
            "donor-search-current",
            "Campaign Finance API Source donor-search-fixture",
            "https://example.org/fec/donor-search/current",
        ),
        (
            "donor-search-secondary",
            "Campaign Finance API Source donor-search-fixture",
            "https://example.org/fec/donor-search/secondary",
        ),
    ]

    john = payload["results"][1]
    assert john["total_amount"] == Decimal("425.00")
    assert john["transaction_count"] == 1
    assert [recipient["person_id"] for recipient in john["recipients"]] == [fixture.alpha.person_id]
    assert john["recipients"][0]["person_id"] == fixture.alpha.person_id


def test_search_donors_supports_employer_and_zip_modes(db_conn: psycopg.Connection) -> None:
    seed_donor_search_fixture(db_conn)

    employer_payload = campaign_finance_queries.search_donors(
        db_conn,
        q="technical services",
        by="employer",
    )
    assert [row["contributor_name"] for row in employer_payload["results"]] == ["ALICIA RIVERA"]
    assert employer_payload["results"][0]["contributor_employer"] == "ActBlue Technical Services"
    assert employer_payload["results"][0]["total_amount"] == Decimal("90.00")

    zip_payload = campaign_finance_queries.search_donors(db_conn, q="27701-1234", by="zip")
    assert [row["contributor_name"] for row in zip_payload["results"]] == ["JANE SMITH"]
    assert zip_payload["results"][0]["normalized_zip5"] == "27701"


def test_donor_search_fixture_is_idempotent_for_live_smoke_reseeding(db_conn: psycopg.Connection) -> None:
    first_fixture = seed_donor_search_fixture(db_conn)
    second_fixture = seed_donor_search_fixture(db_conn)

    payload = campaign_finance_queries.search_donors(db_conn, q="Jane", by="name", limit=20, offset=0)

    assert first_fixture == second_fixture
    assert [row["contributor_name"] for row in payload["results"]] == ["JANE SMITH"]
    assert payload["results"][0]["total_amount"] == Decimal("500.00")
    assert payload["results"][0]["transaction_count"] == 3


def test_search_donors_validates_input_and_clamps_limit(db_conn: psycopg.Connection) -> None:
    seed_donor_search_fixture(db_conn, extra_smith_rows=55)

    with pytest.raises(ValueError, match="Unsupported donor search mode"):
        campaign_finance_queries.search_donors(db_conn, q="smith", by="committee")
    with pytest.raises(ValueError, match="at least 3 characters"):
        campaign_finance_queries.search_donors(db_conn, q="sm", by="name")
    with pytest.raises(ValueError, match="at least 3 characters"):
        campaign_finance_queries.search_donors(db_conn, q="ab", by="employer")
    with pytest.raises(ValueError, match="5-digit ZIP"):
        campaign_finance_queries.search_donors(db_conn, q="27A01", by="zip")

    payload = campaign_finance_queries.search_donors(db_conn, q="smith", by="name", limit=500)
    assert payload["limit"] == campaign_finance_queries.DONOR_SEARCH_MAX_LIMIT == 50
    assert len(payload["results"]) == 50


def test_search_donors_offset_and_public_query_exports_are_stable(db_conn: psycopg.Connection) -> None:
    seed_donor_search_fixture(db_conn)

    assert public_queries.DONOR_SEARCH_MIN_QUERY_LEN == 3
    assert public_queries.DONOR_SEARCH_MAX_LIMIT == 50
    assert public_queries.search_donors is campaign_finance_queries.search_donors

    payload = campaign_finance_queries.search_donors(db_conn, q="smith", by="name", limit=1, offset=1)

    assert payload["limit"] == 1
    assert payload["offset"] == 1
    assert [row["contributor_name"] for row in payload["results"]] == ["JOHN SMITH"]


def test_search_donors_ordering_tie_breaks_are_deterministic(db_conn: psycopg.Connection) -> None:
    seed_donor_search_fixture(db_conn, include_ordering_tie_rows=True)

    payload = campaign_finance_queries.search_donors(db_conn, q="order smith", by="name", limit=10)

    ordered_keys = [
        (
            row["contributor_name"],
            row["total_amount"],
            row["transaction_count"],
            row["id"],
        )
        for row in payload["results"]
    ]
    assert ordered_keys == [
        ("ORDER SMITH COUNT", Decimal("60.00"), 2, "72000000-0000-0000-0000-000000000121"),
        ("ORDER SMITH ALPHA", Decimal("60.00"), 1, "72000000-0000-0000-0000-000000000123"),
        ("ORDER SMITH BETA", Decimal("60.00"), 1, "72000000-0000-0000-0000-000000000124"),
        ("ORDER SMITH STABLE", Decimal("40.00"), 1, "72000000-0000-0000-0000-000000000125"),
        ("ORDER SMITH STABLE", Decimal("40.00"), 1, "72000000-0000-0000-0000-000000000126"),
    ]
