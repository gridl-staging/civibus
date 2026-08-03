"""Donor-rollup builder contracts."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from uuid import UUID

import psycopg
import pytest

from api.queries import campaign_finance as campaign_finance_queries
from core.refresh import donor_rollup
from test_support.donor_search_fixture import seed_donor_search_fixture


pytestmark = pytest.mark.integration


def test_rollup_grain_derives_from_key_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    observed_aliases: list[str] = []
    owner_key_columns = (*reversed(campaign_finance_queries._DONOR_SEARCH_KEY_COLUMNS), "contributor_middle_name")

    def replacement_key_sql(alias: str) -> str:
        observed_aliases.append(alias)
        return f"owned_key({alias}.normalized_zip5, {alias}.contributor_name)"

    monkeypatch.setattr(campaign_finance_queries, "_DONOR_SEARCH_KEY_COLUMNS", owner_key_columns)
    monkeypatch.setattr(campaign_finance_queries, "_donor_key_sql", replacement_key_sql)

    rendered_grain = donor_rollup.rendered_donor_grain_expression()

    assert observed_aliases == [donor_rollup.DONOR_GRAIN_ALIAS]
    assert "t.contributor_middle_name" in rendered_grain
    assert rendered_grain.endswith(
        "owned_key(donor_source.normalized_zip5, donor_source.contributor_name)\n"
        "GROUP BY donor_source.normalized_zip5, donor_source.contributor_state, "
        "donor_source.contributor_city, donor_source.contributor_occupation, "
        "donor_source.contributor_employer, donor_source.contributor_name, "
        "donor_source.contributor_middle_name"
    )


def test_rollup_carries_key_definition_fingerprint(db_conn: psycopg.Connection) -> None:
    seed_donor_search_fixture(db_conn)

    result = donor_rollup.rebuild_donor_search_rollup(db_conn)
    stored_fingerprint = db_conn.execute(
        "SELECT donor_key_fingerprint FROM cf.donor_search_rollup_provenance WHERE singleton"
    ).fetchone()

    assert result.row_count > 0
    assert stored_fingerprint == (donor_rollup.donor_key_fingerprint(),)
    assert stored_fingerprint == (hashlib.sha256(donor_rollup.rendered_donor_grain_expression().encode()).hexdigest(),)


def test_rollup_populates_name_employer_and_zip_search_attributes(db_conn: psycopg.Connection) -> None:
    fixture = seed_donor_search_fixture(db_conn)
    db_conn.execute(
        """
        INSERT INTO cf.committee_summary (committee_id, cycle, derived_jurisdiction)
        VALUES (%s, 2026, 'federal/fec')
        ON CONFLICT (committee_id, cycle)
        DO UPDATE SET derived_jurisdiction = EXCLUDED.derived_jurisdiction
        """,
        (fixture.alpha.committee_id,),
    )

    donor_rollup.rebuild_donor_search_rollup(db_conn)

    searchable_rows = db_conn.execute(
        """
        SELECT
            representative_transaction_id::text,
            contributor_name,
            contributor_employer,
            normalized_zip5,
            jurisdiction,
            search_text,
            ROUND(total_amount, 2)::text,
            transaction_count,
            latest_transaction_date::text
        FROM cf.donor_search_rollup
        WHERE LOWER(contributor_name) LIKE '%smith%'
          AND LOWER(contributor_employer) LIKE '%civibus labs%'
          AND normalized_zip5 = '27701'
          AND jurisdiction = 'federal/fec'
          AND search_text LIKE '%smith%'
          AND search_text LIKE '%civibus labs%'
          AND search_text LIKE '%27701%'
        """
    ).fetchall()
    relation_owned_names = db_conn.execute(
        """
        SELECT indexname
        FROM pg_indexes
        WHERE schemaname = 'cf'
          AND tablename = 'donor_search_rollup'
        ORDER BY indexname
        """
    ).fetchall()

    assert searchable_rows == [
        (
            "72000000-0000-0000-0000-000000000101",
            "JANE SMITH",
            "Civibus Labs",
            "27701",
            "federal/fec",
            "jane smith\x1fcivibus labs\x1f27701",
            "500.00",
            3,
            "2024-07-15",
        )
    ]
    assert relation_owned_names == [
        ("donor_search_rollup_pkey",),
        ("idx_donor_search_rollup_normalized_zip5",),
        ("idx_donor_search_rollup_search_text_trgm",),
    ]


def test_rollup_preserves_exact_identity_variants_without_changing_aggregate(
    db_conn: psycopg.Connection,
) -> None:
    seed_donor_search_fixture(db_conn)
    db_conn.execute(
        """
        UPDATE cf.transaction
        SET contributor_name_raw = ' JANE SMITH ',
            contributor_employer = ' Civibus Labs ',
            contributor_occupation = '',
            contributor_city = ' Durham ',
            contributor_zip = '27701-9999'
        WHERE id = '72000000-0000-0000-0000-000000000102'
        """
    )
    db_conn.execute(
        """
        UPDATE cf.transaction
        SET contributor_occupation = ''
        WHERE id IN (
            '72000000-0000-0000-0000-000000000101',
            '72000000-0000-0000-0000-000000000112'
        )
        """
    )

    donor_rollup.rebuild_donor_search_rollup(db_conn)
    variants = db_conn.execute(
        """
        SELECT
            contributor_name_raw,
            contributor_employer,
            contributor_occupation,
            contributor_city,
            contributor_state,
            contributor_zip
        FROM cf.donor_search_rollup_identity_variant
        WHERE donor_key = (
            SELECT donor_key
            FROM cf.donor_search_rollup
            WHERE representative_transaction_id = %s
        )
        ORDER BY contributor_zip
        """,
        (UUID("72000000-0000-0000-0000-000000000101"),),
    ).fetchall()
    aggregate = db_conn.execute(
        """
        SELECT total_amount, transaction_count
        FROM cf.donor_search_rollup
        WHERE representative_transaction_id = %s
        """,
        (UUID("72000000-0000-0000-0000-000000000101"),),
    ).fetchone()

    assert variants == [
        ("JANE SMITH", "Civibus Labs", "", "Durham", "NC", "27701-1234"),
        (" JANE SMITH ", " Civibus Labs ", "", " Durham ", "NC", "27701-9999"),
    ]
    assert aggregate == (Decimal("500.00"), 3)


def test_failed_rebuild_never_exposes_half_built_rollup(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_donor_search_fixture(db_conn)
    first_build = donor_rollup.rebuild_donor_search_rollup(db_conn)
    before_failure = db_conn.execute(
        "SELECT donor_key, total_amount, transaction_count FROM cf.donor_search_rollup ORDER BY donor_key"
    ).fetchall()
    variants_before_failure = db_conn.execute(
        """
        SELECT donor_key, contributor_name_raw, contributor_zip
        FROM cf.donor_search_rollup_identity_variant
        ORDER BY donor_key, contributor_name_raw, contributor_zip
        """
    ).fetchall()

    monkeypatch.setattr(
        donor_rollup,
        "_identity_variant_select_sql",
        lambda: "SELECT missing_rollup_function(%s)",
    )
    with pytest.raises(psycopg.errors.UndefinedFunction):
        donor_rollup.rebuild_donor_search_rollup(db_conn)

    after_failure = db_conn.execute(
        "SELECT donor_key, total_amount, transaction_count FROM cf.donor_search_rollup ORDER BY donor_key"
    ).fetchall()
    variants_after_failure = db_conn.execute(
        """
        SELECT donor_key, contributor_name_raw, contributor_zip
        FROM cf.donor_search_rollup_identity_variant
        ORDER BY donor_key, contributor_name_raw, contributor_zip
        """
    ).fetchall()
    provenance = db_conn.execute(
        "SELECT row_count, donor_key_fingerprint FROM cf.donor_search_rollup_provenance WHERE singleton"
    ).fetchone()

    assert after_failure == before_failure
    assert variants_after_failure == variants_before_failure
    assert provenance == (first_build.row_count, first_build.donor_key_fingerprint)
