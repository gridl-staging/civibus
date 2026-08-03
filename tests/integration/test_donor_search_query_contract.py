from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import psycopg
import pytest
from psycopg.rows import dict_row

from api.contribution_insights_contract import (
    CONTRIBUTION_INSIGHTS_MIN_DATE,
    NOT_SUPERSEDED_SOURCE_RECORD_WHERE_SQL,
    contribution_insights_transaction_where_sql,
)
from api.queries import campaign_finance as campaign_finance_queries
from api.queries.campaign_finance import DonorSearchRollupUnavailableError, search_donors
from api.test_campaign_finance_support import TransactionRowSeed, insert_transaction_row
from core.entity_resolution.extract import _donor_identity_id
from core.refresh import donor_rollup
from test_support.donor_search_fixture import (
    DonorSearchFixtureIds,
    seed_donor_search_fixture,
    seed_full_scope_skewed_donor_search_fixture,
)

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class IdentityVariantSeed:
    transaction_id: UUID
    amount: Decimal
    contributor_name_raw: str
    contributor_employer: str
    contributor_occupation: str
    contributor_city: str
    contributor_state: str
    contributor_zip: str


_LIVE_TRANSACTION_ORACLE_SQL = f"""
    WITH current_federal_officeholders AS MATERIALIZED (
        SELECT DISTINCT officeholding.person_id
        FROM civic.officeholding officeholding
        JOIN civic.office office
          ON office.id = officeholding.office_id
        WHERE officeholding.valid_period @> CURRENT_DATE
          AND office.office_level = 'federal'
    ),
    current_federal_committee_scope AS MATERIALIZED (
        SELECT DISTINCT link.committee_id
        FROM current_federal_officeholders current_officeholder
        JOIN cf.candidate candidate
          ON candidate.person_id = current_officeholder.person_id
        JOIN cf.candidate_committee_link link
          ON link.candidate_id = candidate.id
        WHERE candidate.person_id IS NOT NULL
          AND link.valid_period @> CURRENT_DATE
    ),
    live_donor_transactions AS MATERIALIZED (
        SELECT
            BTRIM(t.contributor_name_raw) AS contributor_name,
            NULLIF(BTRIM(t.contributor_employer), '') AS contributor_employer,
            NULLIF(BTRIM(t.contributor_occupation), '') AS contributor_occupation,
            NULLIF(BTRIM(t.contributor_city), '') AS contributor_city,
            NULLIF(BTRIM(t.contributor_state), '') AS contributor_state,
            NULLIF(LEFT(t.contributor_zip, 5), '') AS normalized_zip5,
            t.amount
        FROM cf.transaction t
        JOIN current_federal_committee_scope scope
          ON scope.committee_id = t.committee_id
        WHERE t.contributor_name_raw IS NOT NULL
          AND BTRIM(t.contributor_name_raw) != ''
{contribution_insights_transaction_where_sql()}
{NOT_SUPERSEDED_SOURCE_RECORD_WHERE_SQL}
    )
    SELECT
        contributor_name,
        contributor_employer,
        contributor_occupation,
        contributor_city,
        contributor_state,
        normalized_zip5,
        COALESCE(SUM(amount), 0) AS total_amount,
        COUNT(*)::integer AS transaction_count
    FROM live_donor_transactions
    WHERE contributor_name ILIKE %s
    GROUP BY
        contributor_name,
        contributor_employer,
        contributor_occupation,
        contributor_city,
        contributor_state,
        normalized_zip5
    ORDER BY total_amount DESC, transaction_count DESC, contributor_name ASC
    LIMIT %s
"""


def _fetch_live_transaction_oracle_rows(
    conn: psycopg.Connection,
    *,
    query: str,
    limit: int,
) -> list[dict[str, object]]:
    """Compute expected donor rows without consulting the serving rollup."""
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            _LIVE_TRANSACTION_ORACLE_SQL,
            (CONTRIBUTION_INSIGHTS_MIN_DATE, f"%{query}%", limit),
        )
        return list(cursor.fetchall())


def _set_rollup_provenance(
    conn: psycopg.Connection,
    *,
    completed_at: datetime,
    fingerprint: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO cf.donor_search_rollup_provenance (
            singleton,
            donor_key_fingerprint,
            row_count,
            build_duration_milliseconds,
            completed_at
        )
        VALUES (TRUE, %s, 1, 1, %s)
        ON CONFLICT (singleton) DO UPDATE
        SET donor_key_fingerprint = EXCLUDED.donor_key_fingerprint,
            row_count = EXCLUDED.row_count,
            build_duration_milliseconds = EXCLUDED.build_duration_milliseconds,
            completed_at = EXCLUDED.completed_at
        """,
        (fingerprint or donor_rollup.donor_key_fingerprint(), completed_at),
    )


@pytest.mark.parametrize(
    ("provenance_setup", "expected_reason"),
    [
        (lambda conn, now: conn.execute("DELETE FROM cf.donor_search_rollup_provenance"), "missing_provenance"),
        (
            lambda conn, now: _set_rollup_provenance(conn, completed_at=now - timedelta(days=8, seconds=1)),
            "stale_provenance",
        ),
        (
            lambda conn, now: _set_rollup_provenance(conn, completed_at=now + timedelta(seconds=1)),
            "future_provenance_timestamp",
        ),
        (
            lambda conn, now: _set_rollup_provenance(conn, completed_at=now, fingerprint="not-current"),
            "donor_key_fingerprint_mismatch",
        ),
    ],
)
def test_search_donors_rejects_unusable_rollup_provenance(
    db_conn: psycopg.Connection,
    provenance_setup,
    expected_reason: str,
) -> None:
    seed_donor_search_fixture(db_conn)
    now = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)
    provenance_setup(db_conn, now)

    with pytest.raises(DonorSearchRollupUnavailableError) as exc_info:
        campaign_finance_queries._require_current_donor_search_rollup(db_conn, now=now)

    assert exc_info.value.reason == expected_reason


def test_search_donors_rejects_malformed_rollup_provenance_timestamp() -> None:
    with pytest.raises(DonorSearchRollupUnavailableError) as exc_info:
        campaign_finance_queries._coerce_rollup_completed_at("not-a-timestamp")

    assert exc_info.value.reason == "malformed_provenance_timestamp"


def test_search_donors_uses_refresh_owner_for_donor_key_fingerprint(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_donor_search_fixture(db_conn)
    calls = 0
    original_fingerprint = donor_rollup.donor_key_fingerprint

    def fake_fingerprint() -> str:
        nonlocal calls
        calls += 1
        return original_fingerprint()

    monkeypatch.setattr(donor_rollup, "donor_key_fingerprint", fake_fingerprint)

    payload = search_donors(db_conn, q="smith", by="name", limit=1, offset=0)

    assert calls == 1
    assert payload["rollup_completed_at"] is not None
    assert len(payload["results"]) == 1


def _insert_identity_variant_transaction_row(
    conn: psycopg.Connection,
    *,
    fixture: DonorSearchFixtureIds,
    seed: IdentityVariantSeed,
) -> None:
    insert_transaction_row(
        conn,
        TransactionRowSeed(
            id=seed.transaction_id,
            filing_id=UUID("72000000-0000-0000-0000-000000000041"),
            committee_id=fixture.alpha.committee_id,
            transaction_type="15",
            amount=seed.amount,
            amendment_indicator="N",
            source_record_id=fixture.source_record_current,
            transaction_identifier=f"identity-variant-{seed.transaction_id}",
            transaction_date=date(2025, 6, 1),
            contributor_name_raw=seed.contributor_name_raw,
            contributor_entity_type="IND",
            contributor_employer=seed.contributor_employer,
            contributor_occupation=seed.contributor_occupation,
            contributor_city=seed.contributor_city,
            contributor_state=seed.contributor_state,
            contributor_zip=seed.contributor_zip,
            recipient_candidate_id=fixture.alpha.candidate_id,
            recipient_committee_id=fixture.alpha.committee_id,
        ),
    )


def _insert_identity_variant_transaction(
    conn: psycopg.Connection,
    *,
    fixture: DonorSearchFixtureIds,
    seed: IdentityVariantSeed,
) -> UUID:
    _insert_identity_variant_transaction_row(conn, fixture=fixture, seed=seed)
    donor_identity_id = _donor_identity_id(asdict(seed))
    conn.execute(
        """
        INSERT INTO core.donor_identity (
            id, canonical_name, contributor_name_raw, contributor_employer,
            contributor_occupation, contributor_city, contributor_state,
            contributor_zip, zip5, transaction_count
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
        """,
        (
            donor_identity_id,
            seed.contributor_name_raw.strip(),
            seed.contributor_name_raw,
            seed.contributor_employer,
            seed.contributor_occupation,
            seed.contributor_city,
            seed.contributor_state,
            seed.contributor_zip,
            seed.contributor_zip[:5],
        ),
    )
    return donor_identity_id


def _insert_identity_variant_transaction_without_identity(
    conn: psycopg.Connection,
    *,
    fixture: DonorSearchFixtureIds,
    seed: IdentityVariantSeed,
) -> None:
    _insert_identity_variant_transaction_row(conn, fixture=fixture, seed=seed)


def _insert_active_identity_cluster(
    conn: psycopg.Connection,
    *,
    cluster_id: UUID,
    member_ids: list[UUID],
) -> None:
    conn.execute(
        """
        INSERT INTO core.entity_cluster (
            id, entity_type, canonical_entity_id, cluster_confidence, member_count
        )
        VALUES (%s, 'donor_identity', %s, 0.99, %s)
        """,
        (cluster_id, member_ids[0], len(member_ids)),
    )
    with conn.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO core.cluster_member (
                id, cluster_id, entity_type, entity_id, is_canonical, merged_at, merged_by
            )
            VALUES (%s, %s, 'donor_identity', %s, %s, CURRENT_TIMESTAMP, 'test_fixture')
            """,
            [
                (UUID(int=cluster_id.int + index + 1), cluster_id, member_id, index == 0)
                for index, member_id in enumerate(member_ids)
            ],
        )


def test_search_donors_resolves_raw_identity_variants_without_rollup_fanout(
    db_conn: psycopg.Connection,
) -> None:
    fixture = seed_donor_search_fixture(db_conn)
    shared_seed = IdentityVariantSeed(
        transaction_id=UUID("72200000-0000-0000-0000-000000000001"),
        amount=Decimal("10.00"),
        contributor_name_raw="ALICE VARIANT",
        contributor_employer="Civic Works",
        contributor_occupation="",
        contributor_city="Durham",
        contributor_state="NC",
        contributor_zip="27701-1111",
    )
    variant_seed = IdentityVariantSeed(
        transaction_id=UUID("72200000-0000-0000-0000-000000000002"),
        amount=Decimal("20.00"),
        contributor_name_raw=" ALICE VARIANT ",
        contributor_employer=" Civic Works ",
        contributor_occupation="",
        contributor_city=" Durham ",
        contributor_state="NC",
        contributor_zip="27701-2222",
    )
    shared_identity_id = _insert_identity_variant_transaction(db_conn, fixture=fixture, seed=shared_seed)
    variant_identity_id = _insert_identity_variant_transaction(db_conn, fixture=fixture, seed=variant_seed)
    _insert_active_identity_cluster(
        db_conn,
        cluster_id=UUID("72200000-0000-0000-0000-000000000101"),
        member_ids=[shared_identity_id, variant_identity_id],
    )

    for suffix, zip_code, amount in ((3, "27701-3333", "30.00"), (4, "27701-4444", "40.00")):
        identity_id = _insert_identity_variant_transaction(
            db_conn,
            fixture=fixture,
            seed=IdentityVariantSeed(
                transaction_id=UUID(f"72200000-0000-0000-0000-{suffix:012d}"),
                amount=Decimal(amount),
                contributor_name_raw="CASEY COLLISION",
                contributor_employer="Civic Works",
                contributor_occupation="",
                contributor_city="Durham",
                contributor_state="NC",
                contributor_zip=zip_code,
            ),
        )
        _insert_active_identity_cluster(
            db_conn,
            cluster_id=UUID(f"72200000-0000-0000-0000-{suffix + 100:012d}"),
            member_ids=[identity_id],
        )

    donor_rollup.rebuild_donor_search_rollup(db_conn)
    resolved_results = search_donors(db_conn, q="alice variant", by="name", limit=20, offset=0)["results"]
    collision_results = search_donors(db_conn, q="casey collision", by="name", limit=20, offset=0)["results"]

    assert len(resolved_results) == 1
    assert resolved_results[0]["donor_identity_id"] == str(shared_identity_id)
    assert resolved_results[0]["combined_record_count"] == 2
    assert resolved_results[0]["total_amount"] == Decimal("30.00")
    assert resolved_results[0]["transaction_count"] == 2
    assert len(collision_results) == 1
    assert collision_results[0]["donor_identity_id"] is None
    assert collision_results[0]["total_amount"] == Decimal("70.00")
    assert collision_results[0]["transaction_count"] == 2


def test_search_donors_leaves_partially_unresolved_identity_variants_unattributed(
    db_conn: psycopg.Connection,
) -> None:
    fixture = seed_donor_search_fixture(db_conn)
    resolved_seed = IdentityVariantSeed(
        transaction_id=UUID("72200000-0000-0000-0000-000000000201"),
        amount=Decimal("15.00"),
        contributor_name_raw="MORGAN PARTIAL",
        contributor_employer="Civic Works",
        contributor_occupation="",
        contributor_city="Durham",
        contributor_state="NC",
        contributor_zip="27701-5555",
    )
    unresolved_seed = IdentityVariantSeed(
        transaction_id=UUID("72200000-0000-0000-0000-000000000202"),
        amount=Decimal("25.00"),
        contributor_name_raw=" MORGAN PARTIAL ",
        contributor_employer=" Civic Works ",
        contributor_occupation="",
        contributor_city=" Durham ",
        contributor_state="NC",
        contributor_zip="27701-6666",
    )
    resolved_identity_id = _insert_identity_variant_transaction(db_conn, fixture=fixture, seed=resolved_seed)
    _insert_active_identity_cluster(
        db_conn,
        cluster_id=UUID("72200000-0000-0000-0000-000000000301"),
        member_ids=[resolved_identity_id],
    )
    _insert_identity_variant_transaction_without_identity(db_conn, fixture=fixture, seed=unresolved_seed)

    donor_rollup.rebuild_donor_search_rollup(db_conn)
    results = search_donors(db_conn, q="morgan partial", by="name", limit=20, offset=0)["results"]

    assert len(results) == 1
    assert results[0]["donor_identity_id"] is None
    assert results[0]["combined_record_count"] == 1
    assert results[0]["underlying_records"] == []
    assert results[0]["total_amount"] == Decimal("40.00")
    assert results[0]["transaction_count"] == 2


def test_search_donors_rejects_cluster_without_active_canonical_identity(
    db_conn: psycopg.Connection,
) -> None:
    fixture = seed_donor_search_fixture(db_conn)
    seed = IdentityVariantSeed(
        transaction_id=UUID("72200000-0000-0000-0000-000000000401"),
        amount=Decimal("35.00"),
        contributor_name_raw="RILEY INVALID CANONICAL",
        contributor_employer="Civic Works",
        contributor_occupation="Engineer",
        contributor_city="Durham",
        contributor_state="NC",
        contributor_zip="27701-7777",
    )
    identity_id = _insert_identity_variant_transaction(db_conn, fixture=fixture, seed=seed)
    cluster_id = UUID("72200000-0000-0000-0000-000000000501")
    _insert_active_identity_cluster(db_conn, cluster_id=cluster_id, member_ids=[identity_id])
    missing_canonical_id = UUID("72200000-0000-0000-0000-000000000599")
    db_conn.execute(
        "UPDATE core.entity_cluster SET canonical_entity_id = %s WHERE id = %s",
        (missing_canonical_id, cluster_id),
    )

    donor_rollup.rebuild_donor_search_rollup(db_conn)
    results = search_donors(db_conn, q="riley invalid canonical", by="name", limit=20, offset=0)["results"]

    assert len(results) == 1
    assert results[0]["donor_identity_id"] is None
    assert results[0]["contributor_name"] == "RILEY INVALID CANONICAL"
    assert results[0]["combined_record_count"] == 1
    assert results[0]["underlying_records"] == []
    assert results[0]["total_amount"] == Decimal("35.00")
    assert results[0]["transaction_count"] == 1


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


def test_search_donors_text_modes_do_not_match_the_other_text_field(
    db_conn: psycopg.Connection,
) -> None:
    seed_donor_search_fixture(db_conn)

    name_results = search_donors(
        db_conn,
        q="technical services",
        by="name",
        limit=20,
        offset=0,
    )["results"]
    employer_results = search_donors(
        db_conn,
        q="smith",
        by="employer",
        limit=20,
        offset=0,
    )["results"]

    assert name_results == []
    assert employer_results == []


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


def _donor_equivalence_tuple(row: dict[str, object]) -> tuple[object, ...]:
    return (
        row["contributor_name"],
        row["contributor_employer"],
        row["contributor_occupation"],
        row["contributor_city"],
        row["contributor_state"],
        row["normalized_zip5"],
        row["total_amount"],
        row["transaction_count"],
    )


def test_rollup_output_matches_live_path(db_conn: psycopg.Connection) -> None:
    seed_full_scope_skewed_donor_search_fixture(db_conn)

    for query in ("williams", "johnson", "smith"):
        live_results = _fetch_live_transaction_oracle_rows(db_conn, query=query, limit=50)
        rollup_results = search_donors(db_conn, q=query, by="name", limit=50, offset=0)["results"]

        print(f"donor rollup equivalence query={query} n={len(live_results)}")
        assert len(live_results) >= 5
        assert sum(row["total_amount"] for row in live_results) > 0
        assert [_donor_equivalence_tuple(row) for row in rollup_results] == [
            _donor_equivalence_tuple(row) for row in live_results
        ]


def test_search_donors_full_scope_bound_preserves_high_volume_donor_values(
    db_conn: psycopg.Connection,
) -> None:
    fixture = seed_full_scope_skewed_donor_search_fixture(db_conn)

    payload = search_donors(db_conn, q="williams", by="name", limit=20, offset=0)
    page_two = search_donors(db_conn, q="williams", by="name", limit=2, offset=1)

    assert payload["query"] == "williams"
    assert payload["by"] == "name"
    assert payload["limit"] == 20
    assert payload["offset"] == 0
    assert [result["contributor_name"] for result in payload["results"][:3]] == [
        "FOCUSED WILLIAMS",
        "WILLIAMS COMMON DONOR 000",
        "WILLIAMS COMMON DONOR 001",
    ]
    assert [result["contributor_name"] for result in page_two["results"]] == [
        "WILLIAMS COMMON DONOR 000",
        "WILLIAMS COMMON DONOR 001",
    ]
    assert payload["results"][0]["contributor_name"] == "FOCUSED WILLIAMS"
    donor = payload["results"][0]
    assert donor["id"] == "72000000-0000-0009-8000-000000000001"
    assert donor["contributor_employer"] == "Bound Fixture"
    assert donor["contributor_occupation"] == "Engineer"
    assert donor["contributor_city"] == "Durham"
    assert donor["contributor_state"] == "NC"
    assert donor["normalized_zip5"] == "27701"
    assert donor["total_amount"] == Decimal("3000.00")
    assert donor["transaction_count"] == 30
    assert [
        (
            recipient["person_id"],
            recipient["candidate_id"],
            recipient["fec_candidate_id"],
            recipient["candidate_name"],
            recipient["committee_id"],
            recipient["fec_committee_id"],
            recipient["committee_name"],
            recipient["total_amount"],
            recipient["transaction_count"],
        )
        for recipient in donor["recipients"]
    ] == [
        (
            fixture.primary_recipient.person_id,
            fixture.primary_recipient.candidate_id,
            "S6NC00000",
            "Full Scope Officeholder 000",
            fixture.primary_recipient.committee_id,
            "C70200000",
            "Full Scope Officeholder 000 Committee",
            Decimal("2000.00"),
            20,
        ),
        (
            fixture.secondary_recipient.person_id,
            fixture.secondary_recipient.candidate_id,
            "S6NC00001",
            "Full Scope Officeholder 001",
            fixture.secondary_recipient.committee_id,
            "C70200001",
            "Full Scope Officeholder 001 Committee",
            Decimal("1000.00"),
            10,
        ),
    ]
    assert [
        (source["source_record_key"], source["record_url"], source["pull_date"].isoformat())
        for source in donor["sources"]
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
    assert [source["source_record_key"] for source in page_two["results"][0]["sources"]] == [
        "donor-search-current",
    ]
