from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

import psycopg
import pytest

import api.queries as public_queries
import api.queries.campaign_finance as campaign_finance_queries
from api.test_campaign_finance_support import (
    CandidateCommitteeLinkSeed,
    CandidateRowSeed,
    CommitteeRowSeed,
    FilingRowSeed,
    TransactionRowSeed,
    insert_candidate_committee_link_row,
    insert_candidate_row,
    insert_committee_row,
    insert_electoral_division_row,
    insert_filing_row,
    insert_office_row,
    insert_officeholding_row,
    insert_transaction_row,
)
from core.db import insert_person
from core.refresh.donor_rollup import rebuild_donor_search_rollup
from core.types.python.models import Person
from test_support.donor_search_fixture import seed_donor_search_fixture

pytestmark = pytest.mark.integration

_SHARED_COMMITTEE_PERSON_ID = UUID("72000000-0000-4000-8000-000000000191")
_SHARED_COMMITTEE_OFFICEHOLDING_ID = UUID("72000000-0000-0000-0000-000000000191")
_SHARED_COMMITTEE_OFFICE_ID = UUID("72000000-0000-0000-0000-000000000192")
_SHARED_COMMITTEE_DIVISION_ID = UUID("72000000-0000-0000-0000-000000000193")
_SHARED_COMMITTEE_CANDIDATE_ID = UUID("72000000-0000-0000-0000-000000000194")
_SHARED_COMMITTEE_LINK_ID = UUID("72000000-0000-0000-0000-000000000196")
_SHARED_COMMITTEE_FILING_ID = UUID("72000000-0000-0000-0000-000000000197")
_SHARED_COMMITTEE_TRANSACTION_ID = UUID("72000000-0000-0000-0000-000000000198")
_RESOLVED_DONOR_ID = UUID("72100000-0000-0000-0000-000000000001")
_RESOLVED_DONOR_MEMBER_ID = UUID("72100000-0000-0000-0000-000000000002")
_POSSIBLE_DONOR_ID = UUID("72100000-0000-0000-0000-000000000000")
_RESOLVED_CLUSTER_ID = UUID("72100000-0000-0000-0000-000000000011")


def _seed_shared_committee_officeholder(conn: psycopg.Connection) -> None:
    insert_person(
        conn,
        Person(
            id=_SHARED_COMMITTEE_PERSON_ID,
            canonical_name="Gamma Officeholder",
            first_name="Gamma",
            last_name="Officeholder",
        ),
    )
    insert_electoral_division_row(
        conn,
        division_id=_SHARED_COMMITTEE_DIVISION_ID,
        name="NC gamma federal division",
        division_type="congressional_district",
        state="NC",
        district_number="03",
    )
    insert_office_row(
        conn,
        office_id=_SHARED_COMMITTEE_OFFICE_ID,
        name="us_house",
        title="Representative",
        state="NC",
        electoral_division_id=_SHARED_COMMITTEE_DIVISION_ID,
    )
    insert_officeholding_row(
        conn,
        officeholding_id=_SHARED_COMMITTEE_OFFICEHOLDING_ID,
        person_id=_SHARED_COMMITTEE_PERSON_ID,
        office_id=_SHARED_COMMITTEE_OFFICE_ID,
        electoral_division_id=_SHARED_COMMITTEE_DIVISION_ID,
    )


def _seed_shared_committee_candidate(
    conn: psycopg.Connection,
    *,
    committee_id: UUID,
    source_record_id: UUID,
) -> None:
    _seed_shared_committee_officeholder(conn)
    insert_candidate_row(
        conn,
        CandidateRowSeed(
            id=_SHARED_COMMITTEE_CANDIDATE_ID,
            fec_candidate_id="H0NC03004",
            name="Gamma Officeholder",
            office="H",
            person_id=_SHARED_COMMITTEE_PERSON_ID,
            principal_committee_id=committee_id,
            source_record_id=source_record_id,
            state="NC",
            district="03",
        ),
    )
    insert_candidate_committee_link_row(
        conn,
        CandidateCommitteeLinkSeed(
            id=_SHARED_COMMITTEE_LINK_ID,
            candidate_id=_SHARED_COMMITTEE_CANDIDATE_ID,
            committee_id=committee_id,
            valid_period="[2024-01-01,2100-01-01)",
            designation="J",
            source_record_id=source_record_id,
        ),
    )


def _seed_shared_committee_donation(
    conn: psycopg.Connection,
    *,
    committee_id: UUID,
    source_record_id: UUID,
) -> None:
    insert_filing_row(
        conn,
        FilingRowSeed(
            id=_SHARED_COMMITTEE_FILING_ID,
            filing_fec_id="donor-search-shared-committee-filing",
            committee_id=committee_id,
            amendment_indicator="N",
            source_record_id=source_record_id,
        ),
    )
    insert_transaction_row(
        conn,
        TransactionRowSeed(
            id=_SHARED_COMMITTEE_TRANSACTION_ID,
            filing_id=_SHARED_COMMITTEE_FILING_ID,
            committee_id=committee_id,
            transaction_type="15",
            amount=Decimal("80.00"),
            amendment_indicator="N",
            source_record_id=source_record_id,
            transaction_identifier="donor-search-shared-committee-donation",
            transaction_date=date(2025, 6, 1),
            contributor_name_raw="JOINT SMITH",
            contributor_entity_type="IND",
            contributor_employer="Shared Committee Fixture",
            contributor_occupation="Engineer",
            contributor_city="Durham",
            contributor_state="NC",
            contributor_zip="27701",
            recipient_candidate_id=_SHARED_COMMITTEE_CANDIDATE_ID,
            recipient_committee_id=committee_id,
        ),
    )


def _insert_donor_identity_rows(conn: psycopg.Connection) -> None:
    donor_rows = [
        (
            _RESOLVED_DONOR_ID,
            "TRANSPARENT IDENTITY",
            "Civibus Labs",
            "Engineer",
            "Durham",
            "NC",
            "27701",
        ),
        (
            _RESOLVED_DONOR_MEMBER_ID,
            "TRANSPARENT IDENTITY ALT",
            "Open Civic Works",
            "Architect",
            "Raleigh",
            "NC",
            "27601",
        ),
        (
            _POSSIBLE_DONOR_ID,
            "OUTSIDE ALIAS",
            "Civibus Labs",
            "Analyst",
            "Chapel Hill",
            "NC",
            "27514",
        ),
    ]
    with conn.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO core.donor_identity (
                id,
                canonical_name,
                contributor_name_raw,
                contributor_employer,
                contributor_occupation,
                contributor_city,
                contributor_state,
                contributor_zip,
                zip5,
                transaction_count
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
            """,
            [
                (donor_id, name, name, employer, occupation, city, state, zip_code, zip_code)
                for donor_id, name, employer, occupation, city, state, zip_code in donor_rows
            ],
        )


def _insert_donor_identity_cluster(conn: psycopg.Connection) -> None:
    conn.execute(
        """
        INSERT INTO core.entity_cluster (
            id,
            entity_type,
            canonical_entity_id,
            cluster_confidence,
            member_count
        )
        VALUES (%s, 'donor_identity', %s, 0.99, 2)
        """,
        (_RESOLVED_CLUSTER_ID, _RESOLVED_DONOR_ID),
    )
    with conn.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO core.cluster_member (
                id,
                cluster_id,
                entity_type,
                entity_id,
                is_canonical,
                merged_at,
                merged_by
            )
            VALUES (%s, %s, 'donor_identity', %s, %s, CURRENT_TIMESTAMP, 'test_fixture')
            """,
            [
                (
                    UUID("72100000-0000-0000-0000-000000000021"),
                    _RESOLVED_CLUSTER_ID,
                    _RESOLVED_DONOR_ID,
                    True,
                ),
                (
                    UUID("72100000-0000-0000-0000-000000000022"),
                    _RESOLVED_CLUSTER_ID,
                    _RESOLVED_DONOR_MEMBER_ID,
                    False,
                ),
            ],
        )


def _insert_donor_identity_decisions(conn: psycopg.Connection) -> None:
    with conn.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO core.match_decision (
                id,
                entity_type,
                entity_id_a,
                entity_id_b,
                decision,
                confidence,
                decided_by,
                decision_method
            )
            VALUES (%s, 'donor_identity', %s, %s, %s, %s, 'test_fixture', 'probabilistic')
            """,
            [
                (
                    UUID("72100000-0000-0000-0000-000000000031"),
                    _RESOLVED_DONOR_ID,
                    _RESOLVED_DONOR_MEMBER_ID,
                    "match",
                    0.99,
                ),
                (
                    UUID("72100000-0000-0000-0000-000000000032"),
                    _POSSIBLE_DONOR_ID,
                    _RESOLVED_DONOR_ID,
                    "possible_match",
                    0.72,
                ),
            ],
        )


def _insert_donor_identity_transactions(conn: psycopg.Connection) -> None:
    transaction_rows = [
        TransactionRowSeed(
            id=UUID("72100000-0000-0000-0000-000000000101"),
            filing_id=UUID("72000000-0000-0000-0000-000000000041"),
            committee_id=UUID("72000000-0000-0000-0000-000000000015"),
            transaction_type="15",
            amount=Decimal("120.00"),
            amendment_indicator="N",
            source_record_id=UUID("72000000-0000-0000-0000-000000000001"),
            transaction_identifier="donor-search-identity-resolved",
            transaction_date=date(2025, 6, 1),
            contributor_name_raw="TRANSPARENT IDENTITY",
            contributor_entity_type="IND",
            contributor_employer="Civibus Labs",
            contributor_occupation="Engineer",
            contributor_city="Durham",
            contributor_state="NC",
            contributor_zip="27701",
        ),
        TransactionRowSeed(
            id=UUID("72100000-0000-0000-0000-000000000102"),
            filing_id=UUID("72000000-0000-0000-0000-000000000042"),
            committee_id=UUID("72000000-0000-0000-0000-000000000025"),
            transaction_type="15",
            amount=Decimal("80.00"),
            amendment_indicator="N",
            source_record_id=UUID("72000000-0000-0000-0000-000000000002"),
            transaction_identifier="donor-search-identity-member",
            transaction_date=date(2025, 6, 2),
            contributor_name_raw="TRANSPARENT IDENTITY ALT",
            contributor_entity_type="IND",
            contributor_employer="Open Civic Works",
            contributor_occupation="Architect",
            contributor_city="Raleigh",
            contributor_state="NC",
            contributor_zip="27601",
        ),
        TransactionRowSeed(
            id=UUID("72100000-0000-0000-0000-000000000103"),
            filing_id=UUID("72000000-0000-0000-0000-000000000041"),
            committee_id=UUID("72000000-0000-0000-0000-000000000015"),
            transaction_type="15",
            amount=Decimal("60.00"),
            amendment_indicator="N",
            source_record_id=UUID("72000000-0000-0000-0000-000000000003"),
            transaction_identifier="donor-search-identity-possible",
            transaction_date=date(2025, 6, 3),
            contributor_name_raw="OUTSIDE ALIAS",
            contributor_entity_type="IND",
            contributor_employer="Civibus Labs",
            contributor_occupation="Analyst",
            contributor_city="Chapel Hill",
            contributor_state="NC",
            contributor_zip="27514",
        ),
    ]
    for transaction in transaction_rows:
        insert_transaction_row(conn, transaction)


def _seed_donor_identity_transparency_fixture(
    conn: psycopg.Connection,
) -> None:
    _insert_donor_identity_rows(conn)
    _insert_donor_identity_cluster(conn)
    _insert_donor_identity_decisions(conn)
    _insert_donor_identity_transactions(conn)


def test_search_donors_discloses_resolved_identity_and_keeps_possible_match_separate(
    db_conn: psycopg.Connection,
) -> None:
    seed_donor_search_fixture(db_conn)
    _seed_donor_identity_transparency_fixture(db_conn)
    rebuild_donor_search_rollup(db_conn)

    payload = campaign_finance_queries.search_donors(db_conn, q="transparent", by="name", limit=1, offset=0)

    resolved = payload["results"][0]
    assert resolved["donor_identity_id"] == str(_RESOLVED_DONOR_ID)
    assert resolved["total_amount"] == Decimal("200.00")
    assert resolved["transaction_count"] == 2
    assert resolved["combined_record_count"] == 2
    assert resolved["confidence_band"] == "match"
    assert [
        (
            record["donor_identity_id"],
            record["contributor_name"],
            record["contributor_employer"],
            record["contributor_occupation"],
            record["contributor_city"],
            record["contributor_state"],
            record["normalized_zip5"],
            [source["record_url"] for source in record["sources"]],
        )
        for record in resolved["underlying_records"]
    ] == [
        (
            str(_RESOLVED_DONOR_ID),
            "TRANSPARENT IDENTITY",
            "Civibus Labs",
            "Engineer",
            "Durham",
            "NC",
            "27701",
            ["https://example.org/fec/donor-search/current"],
        ),
        (
            str(_RESOLVED_DONOR_MEMBER_ID),
            "TRANSPARENT IDENTITY ALT",
            "Open Civic Works",
            "Architect",
            "Raleigh",
            "NC",
            "27601",
            ["https://example.org/fec/donor-search/secondary"],
        ),
    ]
    assert resolved["not_combined_candidates"] == [
        {
            "donor_identity_id": str(_POSSIBLE_DONOR_ID),
            "contributor_name": "OUTSIDE ALIAS",
            "contributor_employer": "Civibus Labs",
            "contributor_occupation": "Analyst",
            "contributor_city": "Chapel Hill",
            "contributor_state": "NC",
            "normalized_zip5": "27514",
            "confidence_band": "possible_match",
            "sources": [
                {
                    "domain": "campaign_finance",
                    "jurisdiction": "federal/fec",
                    "data_source_name": "Campaign Finance API Source donor-search-fixture",
                    "data_source_url": "https://example.org/campaign-finance-source",
                    "source_record_key": "donor-search-replacement",
                    "record_url": "https://example.org/fec/donor-search/replacement",
                    "pull_date": db_conn.execute(
                        "SELECT pull_date FROM core.source_record WHERE id = %s",
                        (UUID("72000000-0000-0000-0000-000000000003"),),
                    ).fetchone()[0],
                }
            ],
        }
    ]
    assert _POSSIBLE_DONOR_ID not in {UUID(record["donor_identity_id"]) for record in resolved["underlying_records"]}
    assert resolved["combined_record_count"] == len(resolved["underlying_records"])
    assert (
        db_conn.execute(
            """
        SELECT COUNT(*)
        FROM cf.transaction
        WHERE id::text LIKE '72100000-%'
          AND contributor_person_id IS NOT NULL
        """
        ).fetchone()[0]
        == 0
    )


def test_search_donors_preserves_unresolved_md5_fallback_identity(
    db_conn: psycopg.Connection,
) -> None:
    seed_donor_search_fixture(db_conn)

    payload = campaign_finance_queries.search_donors(db_conn, q="jane", by="name", limit=20, offset=0)

    assert len(payload["results"]) == 1
    unresolved = payload["results"][0]
    assert unresolved["id"] == "72000000-0000-0000-0000-000000000101"
    assert unresolved["donor_identity_id"] is None
    assert unresolved["contributor_name"] == "JANE SMITH"
    assert unresolved["contributor_employer"] == "Civibus Labs"
    assert unresolved["contributor_occupation"] == "Engineer"
    assert unresolved["contributor_city"] == "Durham"
    assert unresolved["contributor_state"] == "NC"
    assert unresolved["normalized_zip5"] == "27701"
    assert unresolved["total_amount"] == Decimal("500.00")
    assert unresolved["transaction_count"] == 3
    assert unresolved["combined_record_count"] == 1
    assert unresolved["confidence_band"] is None
    assert unresolved["underlying_records"] == []
    assert unresolved["not_combined_candidates"] == []


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
            "identity_is_safe": True,
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
            "identity_is_safe": True,
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


def test_search_donors_counts_shared_committee_transactions_once(db_conn: psycopg.Connection) -> None:
    fixture = seed_donor_search_fixture(db_conn)
    _seed_shared_committee_candidate(
        db_conn,
        committee_id=fixture.alpha.committee_id,
        source_record_id=fixture.source_record_current,
    )
    _seed_shared_committee_donation(
        db_conn,
        committee_id=fixture.alpha.committee_id,
        source_record_id=fixture.source_record_current,
    )
    rebuild_donor_search_rollup(db_conn)

    payload = campaign_finance_queries.search_donors(db_conn, q="joint smith", by="name", limit=20, offset=0)

    assert [row["contributor_name"] for row in payload["results"]] == ["JOINT SMITH"]
    donor = payload["results"][0]
    assert donor["total_amount"] == Decimal("80.00")
    assert donor["transaction_count"] == 1
    assert [
        (recipient["person_id"], recipient["total_amount"], recipient["transaction_count"])
        for recipient in donor["recipients"]
    ] == [
        (fixture.alpha.person_id, Decimal("80.00"), 1),
        (_SHARED_COMMITTEE_PERSON_ID, Decimal("80.00"), 1),
    ]


_IDENTITY_GATE_SAFE_PERSON_ID = UUID("73000000-0000-4000-8000-000000000001")
_IDENTITY_GATE_UNSAFE_PERSON_ID = UUID("73000000-0000-4000-8000-000000000002")


def _seed_identity_gate_recipient(
    conn: psycopg.Connection,
    *,
    suffix: int,
    person_id: UUID,
    canonical_name: str,
    candidate_name: str,
    fec_candidate_id: str,
    fec_committee_id: str,
    committee_name: str,
    district: str,
    amount: Decimal,
    source_record_id: UUID,
) -> None:
    """Seed one current federal officeholder whose candidate committee received
    one donation from HONESTY GATE SMITH. Test-local because the shared fixture
    (test_support/donor_search_fixture.py) only carries already-cased,
    identity-safe candidate names, which pass the identity gate vacuously."""
    division_id = UUID(f"73000000-0000-0000-0000-0000000000{suffix}1")
    office_id = UUID(f"73000000-0000-0000-0000-0000000000{suffix}2")
    officeholding_id = UUID(f"73000000-0000-0000-0000-0000000000{suffix}3")
    candidate_id = UUID(f"73000000-0000-0000-0000-0000000000{suffix}4")
    committee_id = UUID(f"73000000-0000-0000-0000-0000000000{suffix}5")
    link_id = UUID(f"73000000-0000-0000-0000-0000000000{suffix}6")
    filing_id = UUID(f"73000000-0000-0000-0000-0000000000{suffix}7")
    transaction_id = UUID(f"73000000-0000-0000-0000-0000000000{suffix}8")

    insert_person(
        conn,
        Person(
            id=person_id,
            canonical_name=canonical_name,
            first_name="Honesty",
            last_name=canonical_name.split()[-1],
        ),
    )
    insert_electoral_division_row(
        conn,
        division_id=division_id,
        name=f"NC honesty federal division {district}",
        division_type="congressional_district",
        state="NC",
        district_number=district,
    )
    insert_office_row(
        conn,
        office_id=office_id,
        name="us_house",
        title="Representative",
        state="NC",
        electoral_division_id=division_id,
    )
    insert_officeholding_row(
        conn,
        officeholding_id=officeholding_id,
        person_id=person_id,
        office_id=office_id,
        electoral_division_id=division_id,
    )
    insert_committee_row(
        conn,
        CommitteeRowSeed(
            id=committee_id,
            fec_committee_id=fec_committee_id,
            name=committee_name,
            state="NC",
            city="Raleigh",
        ),
    )
    insert_candidate_row(
        conn,
        CandidateRowSeed(
            id=candidate_id,
            fec_candidate_id=fec_candidate_id,
            name=candidate_name,
            office="H",
            person_id=person_id,
            principal_committee_id=committee_id,
            source_record_id=source_record_id,
            state="NC",
            district=district,
        ),
    )
    insert_candidate_committee_link_row(
        conn,
        CandidateCommitteeLinkSeed(
            id=link_id,
            candidate_id=candidate_id,
            committee_id=committee_id,
            valid_period="[2024-01-01,2100-01-01)",
            designation="P",
            source_record_id=source_record_id,
        ),
    )
    insert_filing_row(
        conn,
        FilingRowSeed(
            id=filing_id,
            filing_fec_id=f"donor-search-identity-gate-filing-{suffix}",
            committee_id=committee_id,
            amendment_indicator="N",
            source_record_id=source_record_id,
        ),
    )
    insert_transaction_row(
        conn,
        TransactionRowSeed(
            id=transaction_id,
            filing_id=filing_id,
            committee_id=committee_id,
            transaction_type="15",
            amount=amount,
            amendment_indicator="N",
            source_record_id=source_record_id,
            transaction_identifier=f"donor-search-identity-gate-donation-{suffix}",
            transaction_date=date(2025, 6, 1),
            contributor_name_raw="HONESTY GATE SMITH",
            contributor_entity_type="IND",
            contributor_employer="Civibus Labs",
            contributor_occupation="Engineer",
            contributor_city="Durham",
            contributor_state="NC",
            contributor_zip="27701",
            recipient_candidate_id=candidate_id,
            recipient_committee_id=committee_id,
        ),
    )


def test_search_donors_flags_recipient_identity_safety(db_conn: psycopg.Connection) -> None:
    """Each recipient row must carry the candidate identity gate. Specimens are
    deliberate: an ALL-CAPS digit-free FEC name is identity-SAFE (frontends may
    format it), while a digit-bearing address-like source string is UNSAFE and
    must stay raw. The shared fixture's mixed-case names cannot distinguish the
    two branches."""
    fixture = seed_donor_search_fixture(db_conn)
    _seed_identity_gate_recipient(
        db_conn,
        suffix=1,
        person_id=_IDENTITY_GATE_SAFE_PERSON_ID,
        canonical_name="Safe Honesty Officeholder",
        candidate_name="OSSOFF, T. JONATHAN",
        fec_candidate_id="H0NC72051",
        fec_committee_id="C72000051",
        committee_name="Honesty Safe Committee",
        district="05",
        amount=Decimal("300.00"),
        source_record_id=fixture.source_record_current,
    )
    _seed_identity_gate_recipient(
        db_conn,
        suffix=2,
        person_id=_IDENTITY_GATE_UNSAFE_PERSON_ID,
        canonical_name="Unsafe Honesty Officeholder",
        candidate_name="212 MAIN AVE W. JOHN, RODNEY",
        fec_candidate_id="H0NC72052",
        fec_committee_id="C72000052",
        committee_name="Honesty Unsafe Committee",
        district="06",
        amount=Decimal("100.00"),
        source_record_id=fixture.source_record_current,
    )
    rebuild_donor_search_rollup(db_conn)

    payload = campaign_finance_queries.search_donors(db_conn, q="honesty gate", by="name", limit=20, offset=0)

    assert [row["contributor_name"] for row in payload["results"]] == ["HONESTY GATE SMITH"]
    donor = payload["results"][0]
    assert donor["recipients"] == [
        {
            "person_id": _IDENTITY_GATE_SAFE_PERSON_ID,
            "candidate_id": UUID("73000000-0000-0000-0000-000000000014"),
            "fec_candidate_id": "H0NC72051",
            "candidate_name": "OSSOFF, T. JONATHAN",
            "identity_is_safe": True,
            "committee_id": UUID("73000000-0000-0000-0000-000000000015"),
            "fec_committee_id": "C72000051",
            "committee_name": "Honesty Safe Committee",
            "total_amount": Decimal("300.00"),
            "transaction_count": 1,
        },
        {
            "person_id": _IDENTITY_GATE_UNSAFE_PERSON_ID,
            "candidate_id": UUID("73000000-0000-0000-0000-000000000024"),
            "fec_candidate_id": "H0NC72052",
            "candidate_name": "212 MAIN AVE W. JOHN, RODNEY",
            "identity_is_safe": False,
            "committee_id": UUID("73000000-0000-0000-0000-000000000025"),
            "fec_committee_id": "C72000052",
            "committee_name": "Honesty Unsafe Committee",
            "total_amount": Decimal("100.00"),
            "transaction_count": 1,
        },
    ]


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


def test_search_donors_preserves_transaction_id_tie_break_across_page_boundary(
    db_conn: psycopg.Connection,
) -> None:
    seed_donor_search_fixture(db_conn, include_ordering_tie_rows=True)

    payload = campaign_finance_queries.search_donors(
        db_conn,
        q="order smith",
        by="name",
        limit=1,
        offset=3,
    )

    assert [row["id"] for row in payload["results"]] == ["72000000-0000-0000-0000-000000000125"]
