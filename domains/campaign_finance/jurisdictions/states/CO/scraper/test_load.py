from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from core.db import try_insert_data_source
from core.types.python.models import DataSource
from domains.campaign_finance.jurisdictions.states.CO.scraper.co_load_test_helpers import (
    SAMPLE_CONTRIBUTIONS_PATH,
    SAMPLE_EXPENDITURES_PATH,
    build_co_expected_filing_fec_id,
    build_unique_fixture_row,
    cleanup_loaded_data_source,
    fetch_entity_source_count,
    expected_co_expenditure_transaction_type,
    parsed_expenditure_rows,
    parsed_fixture_rows,
    fetch_source_record_id,
    write_fixture_rows,
)
from domains.campaign_finance.jurisdictions.states.CO.scraper.extract import (
    extract_co_contribution,
    extract_co_expenditure,
)
from domains.campaign_finance.jurisdictions.states.CO.scraper.load import (
    LoadResult,
    ensure_co_data_source,
    load_co_contribution,
    load_co_contributions,
    load_co_contributions_with_filings,
    load_co_expenditure,
    load_co_expenditures,
    load_co_expenditures_with_filings,
)
from domains.campaign_finance.jurisdictions.states.CO.scraper.parse import (
    parse_co_date,
)

pytestmark = pytest.mark.integration


def test_ensure_co_data_source_is_idempotent(db_conn: psycopg.Connection) -> None:
    first_id = ensure_co_data_source(db_conn)
    second_id = ensure_co_data_source(db_conn)

    assert second_id == first_id

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM core.data_source
            WHERE domain = %s
              AND jurisdiction = %s
              AND name = %s
            """,
            ("campaign_finance", "state/CO", "TRACER Bulk Download — Contributions"),
        )
        count = cursor.fetchone()["count"]

    assert count == 1


def test_ensure_co_data_source_supports_expenditures_with_distinct_name(
    db_conn: psycopg.Connection,
) -> None:
    contribution_source_id = ensure_co_data_source(db_conn, data_type="contributions")
    expenditure_source_id = ensure_co_data_source(db_conn, data_type="expenditures")

    assert contribution_source_id != expenditure_source_id

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT name
            FROM core.data_source
            WHERE id IN (%s, %s)
            """,
            (contribution_source_id, expenditure_source_id),
        )
        source_names = {row["name"] for row in cursor.fetchall()}

    assert source_names == {
        "TRACER Bulk Download — Contributions",
        "TRACER Bulk Download — Expenditures",
    }


def test_load_single_individual_row_creates_entities_and_provenance(db_conn: psycopg.Connection) -> None:
    row = parsed_fixture_rows()[0]
    data_source_id = ensure_co_data_source(db_conn)

    inserted = load_co_contribution(db_conn, row, data_source_id)

    assert inserted is True

    source_record_id = fetch_source_record_id(db_conn, data_source_id, row["RecordID"])
    person_count = fetch_entity_source_count(db_conn, source_record_id, "person", "donor")
    organization_count = fetch_entity_source_count(db_conn, source_record_id, "organization", "recipient")
    address_count = fetch_entity_source_count(db_conn, source_record_id, "address", "contributor_address")

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM core.entity_source
            WHERE source_record_id = %s
            """,
            (source_record_id,),
        )
        entity_source_count = cursor.fetchone()["count"]

    assert person_count == 1
    assert organization_count == 1
    assert address_count == 1
    assert entity_source_count == 3


def test_load_same_row_twice_is_deduplicated_on_record_id(db_conn: psycopg.Connection) -> None:
    row = parsed_fixture_rows()[0]
    data_source_id = ensure_co_data_source(db_conn)

    first_insert = load_co_contribution(db_conn, row, data_source_id)
    second_insert = load_co_contribution(db_conn, row, data_source_id)

    assert first_insert is True
    assert second_insert is False

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = %s
            """,
            (data_source_id, row["RecordID"]),
        )
        source_record_count = cursor.fetchone()["count"]

    assert source_record_count == 1


def test_load_single_row_without_record_id_raises_value_error(db_conn: psycopg.Connection) -> None:
    row = dict(parsed_fixture_rows()[0])
    row["RecordID"] = "   "
    data_source_id = ensure_co_data_source(db_conn)

    with pytest.raises(ValueError, match="missing RecordID"):
        load_co_contribution(db_conn, row, data_source_id)


def test_load_single_row_normalizes_record_id_whitespace(db_conn: psycopg.Connection) -> None:
    row = dict(parsed_fixture_rows()[0])
    row["RecordID"] = "  padded-record-id  "
    data_source_id = ensure_co_data_source(db_conn)

    inserted = load_co_contribution(db_conn, row, data_source_id)

    assert inserted is True

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT source_record_key
            FROM core.source_record
            WHERE data_source_id = %s
            LIMIT 1
            """,
            (data_source_id,),
        )
        source_record = cursor.fetchone()

    assert source_record is not None
    assert source_record["source_record_key"] == "padded-record-id"


def test_load_business_row_creates_contributor_org_but_not_person(db_conn: psycopg.Connection) -> None:
    row = parsed_fixture_rows()[1]
    extracted = extract_co_contribution(row)
    assert extracted["contributor_org"] is not None
    contributor_org_name = extracted["contributor_org"].canonical_name
    committee_id = extracted["committee"].identifiers["co_committee_id"]
    data_source_id = ensure_co_data_source(db_conn)

    inserted = load_co_contribution(db_conn, row, data_source_id)

    assert inserted is True

    source_record_id = fetch_source_record_id(db_conn, data_source_id, row["RecordID"])
    person_count = fetch_entity_source_count(db_conn, source_record_id, "person", "donor")

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM core.entity_source es
            JOIN core.organization o
              ON o.id = es.entity_id
            WHERE es.source_record_id = %s
              AND es.entity_type = 'organization'
              AND es.extraction_role = 'contributor'
              AND o.canonical_name = %s
            """,
            (source_record_id, contributor_org_name),
        )
        contributor_org_count = cursor.fetchone()["count"]

        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM core.entity_source es
            JOIN core.organization o
              ON o.id = es.entity_id
            WHERE es.source_record_id = %s
              AND es.entity_type = 'organization'
              AND es.extraction_role = 'recipient'
              AND o.identifiers @> %s::jsonb
            """,
            (source_record_id, Jsonb({"co_committee_id": committee_id})),
        )
        committee_count = cursor.fetchone()["count"]

    assert person_count == 0
    assert contributor_org_count == 1
    assert committee_count == 1


def test_person_to_data_source_provenance_chain_has_co_jurisdiction(db_conn: psycopg.Connection) -> None:
    row = parsed_fixture_rows()[0]
    data_source_id = ensure_co_data_source(db_conn)

    inserted = load_co_contribution(db_conn, row, data_source_id)

    assert inserted is True

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT ds.domain, ds.jurisdiction
            FROM core.person p
            JOIN core.entity_source es
              ON es.entity_type = 'person'
             AND es.entity_id = p.id
             AND es.extraction_role = 'donor'
            JOIN core.source_record sr
              ON sr.id = es.source_record_id
            JOIN core.data_source ds
              ON ds.id = sr.data_source_id
            WHERE sr.source_record_key = %s
            LIMIT 1
            """,
            (row["RecordID"],),
        )
        provenance_row = cursor.fetchone()

    assert provenance_row is not None
    assert provenance_row["domain"] == "campaign_finance"
    assert provenance_row["jurisdiction"] == "state/CO"


def test_load_co_contributions_is_idempotent_for_fixture(db_conn: psycopg.Connection) -> None:
    data_source_id = ensure_co_data_source(db_conn)

    first_result = load_co_contributions(db_conn, SAMPLE_CONTRIBUTIONS_PATH, data_source_id=data_source_id)

    assert isinstance(first_result, LoadResult)
    assert first_result.inserted == 11
    assert first_result.skipped == 0

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, source_record_key, record_hash, raw_fields, pull_date, superseded_by
            FROM core.source_record
            WHERE data_source_id = %s
            ORDER BY source_record_key, superseded_by NULLS FIRST
            """,
            (data_source_id,),
        )
        first_source_record_snapshot = cursor.fetchall()

    second_result = load_co_contributions(db_conn, SAMPLE_CONTRIBUTIONS_PATH, data_source_id=data_source_id)

    assert isinstance(second_result, LoadResult)
    assert second_result.inserted == 0
    assert second_result.skipped == 11

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, source_record_key, record_hash, raw_fields, pull_date, superseded_by
            FROM core.source_record
            WHERE data_source_id = %s
            ORDER BY source_record_key, superseded_by NULLS FIRST
            """,
            (data_source_id,),
        )
        second_source_record_snapshot = cursor.fetchall()

    assert second_source_record_snapshot == first_source_record_snapshot


def test_load_co_contributions_tracks_superseded_rows_on_each_run(db_conn: psycopg.Connection) -> None:
    data_source_id = ensure_co_data_source(db_conn)

    first_result = load_co_contributions(db_conn, SAMPLE_CONTRIBUTIONS_PATH, data_source_id=data_source_id)
    second_result = load_co_contributions(db_conn, SAMPLE_CONTRIBUTIONS_PATH, data_source_id=data_source_id)

    assert first_result.superseded == 1
    assert second_result.superseded == 1


def test_load_co_contributions_counts_missing_record_id_as_error(tmp_path: Path, db_conn: psycopg.Connection) -> None:
    row = dict(parsed_fixture_rows()[0])
    row["RecordID"] = ""
    file_path = tmp_path / "missing-record-id.csv"
    write_fixture_rows(file_path, [row])
    data_source_id = ensure_co_data_source(db_conn)

    result = load_co_contributions(db_conn, file_path, data_source_id=data_source_id)

    assert result.inserted == 0
    assert result.skipped == 0
    assert result.errors == 1

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM core.source_record
            WHERE data_source_id = %s
            """,
            (data_source_id,),
        )
        source_record_count = cursor.fetchone()["count"]

    assert source_record_count == 0


def test_load_co_expenditure_inserts_payee_role_and_deduplicates_by_record_id(
    db_conn: psycopg.Connection,
) -> None:
    row = parsed_expenditure_rows()[0]
    data_source_id = ensure_co_data_source(db_conn, data_type="expenditures")

    first_insert = load_co_expenditure(db_conn, row, data_source_id)
    second_insert = load_co_expenditure(db_conn, row, data_source_id)

    assert first_insert is True
    assert second_insert is False

    source_record_id = fetch_source_record_id(db_conn, data_source_id, row["RecordID"])
    person_payee_count = fetch_entity_source_count(db_conn, source_record_id, "person", "payee")
    committee_payer_count = fetch_entity_source_count(db_conn, source_record_id, "organization", "payer")

    assert person_payee_count == 1
    assert committee_payer_count == 1


def test_load_co_expenditure_business_row_uses_organization_payee(db_conn: psycopg.Connection) -> None:
    row = parsed_expenditure_rows()[1]
    extracted = extract_co_expenditure(row)
    assert extracted["payee_org"] is not None
    payee_org_name = extracted["payee_org"].canonical_name
    data_source_id = ensure_co_data_source(db_conn, data_type="expenditures")

    inserted = load_co_expenditure(db_conn, row, data_source_id)

    assert inserted is True

    source_record_id = fetch_source_record_id(db_conn, data_source_id, row["RecordID"])
    payee_org_count = fetch_entity_source_count(db_conn, source_record_id, "organization", "payee")
    payer_count = fetch_entity_source_count(db_conn, source_record_id, "organization", "payer")

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM core.entity_source es
            JOIN core.organization o
              ON o.id = es.entity_id
            WHERE es.source_record_id = %s
              AND es.entity_type = 'organization'
              AND es.extraction_role = 'payee'
              AND o.canonical_name = %s
            """,
            (source_record_id, payee_org_name),
        )
        matching_payee_count = cursor.fetchone()["count"]

    assert payee_org_count == 1
    assert payer_count == 1
    assert matching_payee_count == 1


def test_load_co_expenditures_batch_loads_fixture(db_conn: psycopg.Connection) -> None:
    data_source_id = ensure_co_data_source(db_conn, data_type="expenditures")

    result = load_co_expenditures(db_conn, SAMPLE_EXPENDITURES_PATH, data_source_id=data_source_id)

    assert isinstance(result, LoadResult)
    assert result.inserted == 5
    assert result.skipped == 0
    assert result.quarantined == 0
    assert result.superseded == 1
    assert result.errors == 0


def test_load_co_contributions_with_filings_builds_relational_rows_and_is_idempotent(
    db_conn: psycopg.Connection,
) -> None:
    first_result = load_co_contributions_with_filings(db_conn, SAMPLE_CONTRIBUTIONS_PATH)

    assert first_result.inserted == 11
    assert first_result.skipped == 0
    assert first_result.superseded == 1
    assert first_result.errors == 0

    parsed_rows = parsed_fixture_rows()
    expected_filing_fec_ids = {build_co_expected_filing_fec_id(row, "contributions") for row in parsed_rows}
    expected_rows = [row for row in parsed_rows if row.get("Amended") != "Y"]
    expected_record_ids = sorted(row["RecordID"] for row in expected_rows if row.get("RecordID"))
    expected_by_record_id = {
        row["RecordID"]: (
            build_co_expected_filing_fec_id(row, "contributions"),
            "A" if row.get("Amendment") == "Y" else "N",
        )
        for row in expected_rows
        if row.get("RecordID")
    }

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT filing_fec_id
            FROM cf.filing
            WHERE filing_fec_id = ANY(%s)
            ORDER BY filing_fec_id
            """,
            (sorted(expected_filing_fec_ids),),
        )
        filing_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.committee c
            JOIN core.organization o
              ON o.id = c.organization_id
            WHERE c.state = 'CO'
              AND o.identifiers ? 'co_committee_id'
            """,
        )
        committee_count = cursor.fetchone()["count"]

        cursor.execute(
            """
            SELECT t.transaction_identifier,
                   t.amendment_indicator,
                   f.filing_fec_id,
                   t.source_record_id,
                   t.contributor_person_id,
                   t.contributor_organization_id,
                   (
                       SELECT es.entity_id
                       FROM core.entity_source es
                       WHERE es.source_record_id = t.source_record_id
                         AND es.entity_type = 'person'
                         AND es.extraction_role = 'donor'
                       LIMIT 1
                   ) AS expected_contributor_person_id,
                   (
                       SELECT es.entity_id
                       FROM core.entity_source es
                       WHERE es.source_record_id = t.source_record_id
                         AND es.entity_type = 'organization'
                         AND es.extraction_role = 'contributor'
                       LIMIT 1
                   ) AS expected_contributor_organization_id
            FROM cf.transaction t
            JOIN cf.filing f
              ON f.id = t.filing_id
            WHERE t.transaction_identifier = ANY(%s)
            ORDER BY t.transaction_identifier
            """,
            (expected_record_ids,),
        )
        transaction_rows = cursor.fetchall()

    contribution_data_source_id = ensure_co_data_source(db_conn, data_type="contributions")
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, source_record_key, record_hash, raw_fields
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = ANY(%s)
              AND superseded_by IS NULL
            ORDER BY source_record_key
            """,
            (contribution_data_source_id, expected_record_ids),
        )
        source_record_snapshot = cursor.fetchall()

    assert [row["filing_fec_id"] for row in filing_rows] == sorted(expected_filing_fec_ids)
    assert committee_count == len(expected_filing_fec_ids)
    assert [row["transaction_identifier"] for row in transaction_rows] == expected_record_ids
    assert [row["source_record_key"] for row in source_record_snapshot] == expected_record_ids

    for transaction_row in transaction_rows:
        expected_filing_fec_id, expected_amendment_indicator = expected_by_record_id[
            transaction_row["transaction_identifier"]
        ]
        assert transaction_row["filing_fec_id"] == expected_filing_fec_id
        assert transaction_row["amendment_indicator"] == expected_amendment_indicator
        assert transaction_row["contributor_person_id"] == transaction_row["expected_contributor_person_id"]
        assert transaction_row["contributor_organization_id"] == transaction_row["expected_contributor_organization_id"]

    first_filing_rows = filing_rows
    first_transaction_rows = transaction_rows
    first_committee_count = committee_count

    rerun_result = load_co_contributions_with_filings(db_conn, SAMPLE_CONTRIBUTIONS_PATH)
    assert rerun_result.inserted == 0
    assert rerun_result.skipped == 11
    assert rerun_result.superseded == 1
    assert rerun_result.errors == 0

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT filing_fec_id
            FROM cf.filing
            WHERE filing_fec_id = ANY(%s)
            ORDER BY filing_fec_id
            """,
            (sorted(expected_filing_fec_ids),),
        )
        rerun_filing_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT t.transaction_identifier,
                   t.amendment_indicator,
                   f.filing_fec_id,
                   t.source_record_id,
                   t.contributor_person_id,
                   t.contributor_organization_id,
                   (
                       SELECT es.entity_id
                       FROM core.entity_source es
                       WHERE es.source_record_id = t.source_record_id
                         AND es.entity_type = 'person'
                         AND es.extraction_role = 'donor'
                       LIMIT 1
                   ) AS expected_contributor_person_id,
                   (
                       SELECT es.entity_id
                       FROM core.entity_source es
                       WHERE es.source_record_id = t.source_record_id
                         AND es.entity_type = 'organization'
                         AND es.extraction_role = 'contributor'
                       LIMIT 1
                   ) AS expected_contributor_organization_id
            FROM cf.transaction t
            JOIN cf.filing f
              ON f.id = t.filing_id
            WHERE transaction_identifier = ANY(%s)
            ORDER BY t.transaction_identifier
            """,
            (expected_record_ids,),
        )
        rerun_transaction_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT id, source_record_key, record_hash, raw_fields
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = ANY(%s)
              AND superseded_by IS NULL
            ORDER BY source_record_key
            """,
            (contribution_data_source_id, expected_record_ids),
        )
        rerun_source_record_snapshot = cursor.fetchall()

        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.committee c
            JOIN core.organization o
              ON o.id = c.organization_id
            WHERE c.state = 'CO'
              AND o.identifiers ? 'co_committee_id'
            """,
        )
        rerun_committee_count = cursor.fetchone()["count"]

    assert rerun_filing_rows == first_filing_rows
    assert rerun_transaction_rows == first_transaction_rows
    assert rerun_committee_count == first_committee_count
    assert rerun_source_record_snapshot == source_record_snapshot


def test_load_co_contributions_reingest_keeps_transaction_linked_to_active_source_record(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    row = build_unique_fixture_row()
    file_path = tmp_path / "co-amendment-row.csv"
    write_fixture_rows(file_path, [row])
    data_source_id = ensure_co_data_source(db_conn)

    first_result = load_co_contributions_with_filings(db_conn, file_path)
    assert first_result.inserted == 1
    assert first_result.errors == 0

    amended_row = dict(row)
    amended_row["ContributionAmount"] = "275.00"
    amended_row["Explanation"] = "amount corrected"
    write_fixture_rows(file_path, [amended_row])

    second_result = load_co_contributions_with_filings(db_conn, file_path)
    assert second_result.inserted == 1
    assert second_result.errors == 0

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) FILTER (WHERE superseded_by IS NULL) AS active_count,
                   COUNT(*) FILTER (WHERE superseded_by IS NOT NULL) AS superseded_count,
                   (ARRAY_AGG(id) FILTER (WHERE superseded_by IS NULL))[1] AS active_source_record_id
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = %s
            """,
            (data_source_id, row["RecordID"]),
        )
        source_record_state = cursor.fetchone()

        cursor.execute(
            """
            SELECT source_record_id
            FROM cf.transaction
            WHERE transaction_identifier = %s
            """,
            (row["RecordID"],),
        )
        transaction_row = cursor.fetchone()

    assert source_record_state is not None
    assert transaction_row is not None
    assert source_record_state["active_count"] == 1
    assert source_record_state["superseded_count"] == 1
    assert transaction_row["source_record_id"] == source_record_state["active_source_record_id"]


def test_load_co_expenditures_with_filings_uses_expenditure_field_mappings(
    db_conn: psycopg.Connection,
) -> None:
    result = load_co_expenditures_with_filings(db_conn, SAMPLE_EXPENDITURES_PATH)

    assert result.inserted == 5
    assert result.skipped == 0
    assert result.superseded == 1
    assert result.errors == 0

    parsed_rows = parsed_expenditure_rows()
    expected_filing_fec_ids = {build_co_expected_filing_fec_id(row, "expenditures") for row in parsed_rows}
    expected_rows = [row for row in parsed_rows if row.get("Amended") != "Y"]
    expected_record_ids = sorted(row["RecordID"] for row in expected_rows if row.get("RecordID"))
    expected_by_record_id = {
        row["RecordID"]: (
            expected_co_expenditure_transaction_type(row),
            Decimal(str(row["ExpenditureAmount"])),
            parse_co_date(row["ExpenditureDate"]),
            build_co_expected_filing_fec_id(row, "expenditures"),
        )
        for row in expected_rows
        if row.get("RecordID")
    }

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT t.transaction_identifier,
                   t.transaction_type,
                   t.amount,
                   t.transaction_date::text AS transaction_date,
                   f.filing_fec_id,
                   t.contributor_person_id,
                   t.contributor_organization_id,
                   (
                       SELECT es.entity_id
                       FROM core.entity_source es
                       WHERE es.source_record_id = t.source_record_id
                         AND es.entity_type = 'person'
                         AND es.extraction_role = 'payee'
                       LIMIT 1
                   ) AS expected_contributor_person_id,
                   (
                       SELECT es.entity_id
                       FROM core.entity_source es
                       WHERE es.source_record_id = t.source_record_id
                         AND es.entity_type = 'organization'
                         AND es.extraction_role = 'payee'
                       LIMIT 1
                   ) AS expected_contributor_organization_id
            FROM cf.transaction t
            JOIN cf.filing f
              ON f.id = t.filing_id
            WHERE t.transaction_identifier = ANY(%s)
            ORDER BY t.transaction_identifier
            """,
            (expected_record_ids,),
        )
        transaction_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.filing
            WHERE filing_fec_id = ANY(%s)
            """,
            (sorted(expected_filing_fec_ids),),
        )
        filing_count = cursor.fetchone()["count"]

    assert filing_count == len(expected_filing_fec_ids)
    assert [row["transaction_identifier"] for row in transaction_rows] == expected_record_ids

    for transaction_row in transaction_rows:
        expected_type, expected_amount, expected_date, expected_filing_fec_id = expected_by_record_id[
            transaction_row["transaction_identifier"]
        ]
        assert transaction_row["transaction_type"] == expected_type
        assert transaction_row["amount"] == expected_amount
        assert transaction_row["transaction_date"] == expected_date
        assert transaction_row["filing_fec_id"] == expected_filing_fec_id
        assert transaction_row["contributor_person_id"] == transaction_row["expected_contributor_person_id"]
        assert transaction_row["contributor_organization_id"] == transaction_row["expected_contributor_organization_id"]


def test_load_co_contributions_rejects_negative_limit(db_conn: psycopg.Connection) -> None:
    data_source_id = ensure_co_data_source(db_conn)

    with pytest.raises(ValueError, match="greater than or equal to 0"):
        load_co_contributions(db_conn, SAMPLE_CONTRIBUTIONS_PATH, data_source_id=data_source_id, limit=-1)


def test_load_co_expenditures_rejects_negative_limit(db_conn: psycopg.Connection) -> None:
    data_source_id = ensure_co_data_source(db_conn, data_type="expenditures")

    with pytest.raises(ValueError, match="greater than or equal to 0"):
        load_co_expenditures(db_conn, SAMPLE_EXPENDITURES_PATH, data_source_id=data_source_id, limit=-1)


def test_load_co_contributions_commits_short_batches_when_loader_owns_transaction(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    row = build_unique_fixture_row()
    file_path = tmp_path / "review_contributions.csv"
    write_fixture_rows(file_path, [row])

    data_source_id: UUID | None = None
    db_conn.rollback()

    try:
        data_source = DataSource(
            domain="campaign_finance",
            jurisdiction="state/CO",
            name=f"TRACER Review Contributions {uuid4()}",
            source_url="https://example.invalid/review-contributions.csv",
            source_format="csv",
        )
        data_source_id = try_insert_data_source(db_conn, data_source)
        assert data_source_id is not None

        db_conn.commit()

        result = load_co_contributions(db_conn, file_path, data_source_id=data_source_id)

        assert result.inserted == 1
        assert result.skipped == 0
        assert result.errors == 0
        assert db_conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

        with db_conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS count
                FROM core.source_record
                WHERE data_source_id = %s
                  AND source_record_key = %s
                """,
                (data_source_id, row["RecordID"]),
            )
            source_record_count = cursor.fetchone()["count"]

        assert source_record_count == 1
    finally:
        db_conn.rollback()
        if data_source_id is not None:
            cleanup_loaded_data_source(data_source_id)
