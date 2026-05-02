from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from core.db import insert_organization
from core.types.python.models import Organization
from core.types.python.models import compute_record_hash
from domains.campaign_finance.jurisdictions.states.NC.scraper.load import (
    LoadResult,
    _build_nc_source_record,
    build_data_source,
    ensure_nc_data_source,
    load_nc_committee_registry_rows,
    load_nc_transaction,
    load_nc_transactions,
    load_nc_transactions_with_filings,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.committee_registry import (
    NCCommitteeRegistryRow,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.parse import (
    COMMITTEE_DOC_COLUMNS,
    TRANSACTION_COLUMNS,
    parse_committee_docs,
    parse_transactions,
)

pytestmark = pytest.mark.integration

_SAMPLE_TRANSACTIONS_PATH = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "transaction_export_sample.csv"
_SAMPLE_COMMITTEE_DOCS_PATH = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "committee_document_export_sample.csv"
)


def _parsed_fixture_rows() -> list[dict[str, str | None]]:
    return list(parse_transactions(_SAMPLE_TRANSACTIONS_PATH))


def _parsed_committee_doc_rows() -> list[dict[str, str | None]]:
    return list(parse_committee_docs(_SAMPLE_COMMITTEE_DOCS_PATH))


def _insert_nc_committee_bridge(
    conn: psycopg.Connection,
    *,
    committee_sboe_id: str,
    committee_name: str = "NC Committee Bridge",
) -> UUID:
    return insert_organization(
        conn,
        Organization(
            canonical_name=f"{committee_name} {committee_sboe_id}",
            identifiers={"nc_sboe_id": committee_sboe_id},
        ),
    )


def _build_unique_nc_transaction_row(
    base_row: dict[str, str | None],
    *,
    prefix: str,
) -> dict[str, str | None]:
    unique_suffix = uuid4().hex[:8]
    row = dict(base_row)
    street_line_1 = row.get("Street Line 1") or "PO BOX 1"
    row["Street Line 1"] = f"{street_line_1} {prefix}-{unique_suffix}"
    return row


def _write_transaction_rows(path: Path, rows: list[list[str | None]], headers: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(["" if value is None else value for value in row])


def _write_dict_rows(
    path: Path,
    *,
    columns: tuple[str, ...],
    rows: list[dict[str, str | None]],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: "" if row.get(column) is None else row.get(column) for column in columns})


def _source_record_id(
    conn: psycopg.Connection,
    data_source_id: UUID,
    source_record_key: str,
) -> UUID:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = %s
              AND superseded_by IS NULL
            """,
            (data_source_id, source_record_key),
        )
        source_record = cursor.fetchone()

    assert source_record is not None
    return source_record["id"]


def _entity_source_count(
    conn: psycopg.Connection,
    source_record_id: UUID,
    entity_type: str,
    extraction_role: str,
) -> int:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM core.entity_source
            WHERE source_record_id = %s
              AND entity_type = %s
              AND extraction_role = %s
            """,
            (source_record_id, entity_type, extraction_role),
        )
        row = cursor.fetchone()

    return row["count"]


def _entity_source_entity_id(
    conn: psycopg.Connection,
    source_record_id: UUID,
    entity_type: str,
    extraction_role: str,
) -> UUID | None:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT entity_id
            FROM core.entity_source
            WHERE source_record_id = %s
              AND entity_type = %s
              AND extraction_role = %s
            """,
            (source_record_id, entity_type, extraction_role),
        )
        row = cursor.fetchone()

    if row is None:
        return None
    return row["entity_id"]


def _select_nc_committee_registry_row(
    conn: psycopg.Connection,
    *,
    org_group_id: int,
) -> dict[str, object]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT org_group_id,
                   sboe_id,
                   committee_name,
                   status_desc,
                   old_id,
                   candidate_name,
                   first_seen_at,
                   last_seen_at
            FROM cf.nc_committee_registry
            WHERE org_group_id = %s
            """,
            (org_group_id,),
        )
        row = cursor.fetchone()

    assert row is not None
    return row


def test_build_data_source_returns_expected_nc_transaction_metadata() -> None:
    data_source = build_data_source()

    assert data_source.domain == "campaign_finance"
    assert data_source.jurisdiction == "state/NC"
    assert data_source.name == "North Carolina SBoE Transaction Search"
    assert data_source.source_url == "https://cf.ncsbe.gov/CFTxnLkup/"
    assert data_source.source_format == "csv"


def test_ensure_nc_data_source_is_idempotent(db_conn: psycopg.Connection) -> None:
    first_id = ensure_nc_data_source(db_conn)
    second_id = ensure_nc_data_source(db_conn)

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
            ("campaign_finance", "state/NC", "North Carolina SBoE Transaction Search"),
        )
        count = cursor.fetchone()["count"]

    assert count == 1


def test_build_nc_source_record_uses_hash_for_key_and_record_hash() -> None:
    row = _parsed_fixture_rows()[0]
    data_source_id = uuid4()

    source_record = _build_nc_source_record(data_source_id, row)

    raw_fields = dict(row)
    expected_hash = compute_record_hash(raw_fields)

    assert source_record.data_source_id == data_source_id
    assert source_record.raw_fields == raw_fields
    assert source_record.source_record_key == expected_hash
    assert source_record.record_hash == expected_hash


def test_load_nc_transaction_handles_fixture_row_1_and_row_5_roles(db_conn: psycopg.Connection) -> None:
    fixture_rows = _parsed_fixture_rows()
    first_row = _build_unique_nc_transaction_row(fixture_rows[0], prefix="roles-first")
    fifth_row = _build_unique_nc_transaction_row(fixture_rows[4], prefix="roles-fifth")
    data_source_id = ensure_nc_data_source(db_conn)

    inserted_first = load_nc_transaction(db_conn, first_row, data_source_id)
    inserted_fifth = load_nc_transaction(db_conn, fifth_row, data_source_id)

    assert inserted_first is True
    assert inserted_fifth is True

    first_source_record_id = _source_record_id(
        db_conn,
        data_source_id,
        compute_record_hash(dict(first_row)),
    )
    fifth_source_record_id = _source_record_id(
        db_conn,
        data_source_id,
        compute_record_hash(dict(fifth_row)),
    )

    assert _entity_source_count(db_conn, first_source_record_id, "person", "donor") == 0
    assert _entity_source_count(db_conn, first_source_record_id, "organization", "contributor") == 0
    assert _entity_source_count(db_conn, first_source_record_id, "organization", "recipient") == 1
    assert _entity_source_count(db_conn, first_source_record_id, "address", "contributor_address") == 1

    assert _entity_source_count(db_conn, fifth_source_record_id, "person", "donor") == 0
    assert _entity_source_count(db_conn, fifth_source_record_id, "organization", "contributor") == 1
    assert _entity_source_count(db_conn, fifth_source_record_id, "organization", "recipient") == 1


def test_load_same_row_twice_deduplicates_active_source_record(db_conn: psycopg.Connection) -> None:
    row = _build_unique_nc_transaction_row(_parsed_fixture_rows()[0], prefix="dedupe")
    source_record_key = compute_record_hash(dict(row))
    data_source_id = ensure_nc_data_source(db_conn)

    first_insert = load_nc_transaction(db_conn, row, data_source_id)
    second_insert = load_nc_transaction(db_conn, row, data_source_id)

    assert first_insert is True
    assert second_insert is False

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = %s
              AND superseded_by IS NULL
            """,
            (data_source_id, source_record_key),
        )
        source_record_count = cursor.fetchone()["count"]

    assert source_record_count == 1


def test_synthetic_individual_row_reuses_person_by_name_and_zip(db_conn: psycopg.Connection) -> None:
    row = dict(_parsed_fixture_rows()[0])
    row["Name"] = "SMITH, JANE"

    changed_row = dict(row)
    changed_row["Amount"] = "11.0000"

    first_source_record_key = compute_record_hash(dict(row))
    second_source_record_key = compute_record_hash(dict(changed_row))
    assert first_source_record_key != second_source_record_key

    data_source_id = ensure_nc_data_source(db_conn)

    first_insert = load_nc_transaction(db_conn, row, data_source_id)
    second_insert = load_nc_transaction(db_conn, changed_row, data_source_id)

    assert first_insert is True
    assert second_insert is True

    first_source_record_id = _source_record_id(db_conn, data_source_id, first_source_record_key)
    second_source_record_id = _source_record_id(db_conn, data_source_id, second_source_record_key)

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT entity_id
            FROM core.entity_source
            WHERE source_record_id = %s
              AND entity_type = 'person'
              AND extraction_role = 'donor'
            """,
            (first_source_record_id,),
        )
        first_person_row = cursor.fetchone()

        cursor.execute(
            """
            SELECT entity_id
            FROM core.entity_source
            WHERE source_record_id = %s
              AND entity_type = 'person'
              AND extraction_role = 'donor'
            """,
            (second_source_record_id,),
        )
        second_person_row = cursor.fetchone()

    assert first_person_row is not None
    assert second_person_row is not None
    assert first_person_row["entity_id"] == second_person_row["entity_id"]


def test_committees_and_named_contributor_orgs_are_deduplicated(db_conn: psycopg.Connection) -> None:
    fixture_rows = _parsed_fixture_rows()
    first_committee_row = _build_unique_nc_transaction_row(fixture_rows[0], prefix="committee-first")
    second_committee_row = _build_unique_nc_transaction_row(fixture_rows[1], prefix="committee-second")

    first_org_row = _build_unique_nc_transaction_row(fixture_rows[4], prefix="org-first")
    second_org_row = dict(first_org_row)
    second_org_row["Amount"] = "301.0000"

    data_source_id = ensure_nc_data_source(db_conn)

    assert load_nc_transaction(db_conn, first_committee_row, data_source_id) is True
    assert load_nc_transaction(db_conn, second_committee_row, data_source_id) is True
    assert load_nc_transaction(db_conn, first_org_row, data_source_id) is True
    assert load_nc_transaction(db_conn, second_org_row, data_source_id) is True

    first_committee_source_record_id = _source_record_id(
        db_conn,
        data_source_id,
        compute_record_hash(dict(first_committee_row)),
    )
    second_committee_source_record_id = _source_record_id(
        db_conn,
        data_source_id,
        compute_record_hash(dict(second_committee_row)),
    )
    first_org_source_record_id = _source_record_id(
        db_conn,
        data_source_id,
        compute_record_hash(dict(first_org_row)),
    )
    second_org_source_record_id = _source_record_id(
        db_conn,
        data_source_id,
        compute_record_hash(dict(second_org_row)),
    )

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT es.entity_id
            FROM core.entity_source es
            WHERE es.source_record_id = %s
              AND es.entity_type = 'organization'
              AND es.extraction_role = 'recipient'
            """,
            (first_committee_source_record_id,),
        )
        first_committee_entity = cursor.fetchone()

        cursor.execute(
            """
            SELECT es.entity_id
            FROM core.entity_source es
            WHERE es.source_record_id = %s
              AND es.entity_type = 'organization'
              AND es.extraction_role = 'recipient'
            """,
            (second_committee_source_record_id,),
        )
        second_committee_entity = cursor.fetchone()

        cursor.execute(
            """
            SELECT identifiers
            FROM core.organization
            WHERE id = %s
            """,
            (first_committee_entity["entity_id"],),
        )
        committee_identifiers = cursor.fetchone()["identifiers"]

        cursor.execute(
            """
            SELECT es.entity_id
            FROM core.entity_source es
            WHERE es.source_record_id = %s
              AND es.entity_type = 'organization'
              AND es.extraction_role = 'contributor'
            """,
            (first_org_source_record_id,),
        )
        first_org_entity = cursor.fetchone()

        cursor.execute(
            """
            SELECT es.entity_id
            FROM core.entity_source es
            WHERE es.source_record_id = %s
              AND es.entity_type = 'organization'
              AND es.extraction_role = 'contributor'
            """,
            (second_org_source_record_id,),
        )
        second_org_entity = cursor.fetchone()

    assert first_committee_entity is not None
    assert second_committee_entity is not None
    assert first_committee_entity["entity_id"] == second_committee_entity["entity_id"]
    assert committee_identifiers["nc_sboe_id"] == "STA-C3352N-C-001"

    assert first_org_entity is not None
    assert second_org_entity is not None
    assert first_org_entity["entity_id"] == second_org_entity["entity_id"]


def test_loaded_provenance_chain_joins_to_nc_data_source(db_conn: psycopg.Connection) -> None:
    committee_row = _build_unique_nc_transaction_row(_parsed_fixture_rows()[0], prefix="provenance-committee")
    person_row = _build_unique_nc_transaction_row(_parsed_fixture_rows()[0], prefix="provenance-person")
    person_row["Name"] = "SMITH, JANE"

    data_source_id = ensure_nc_data_source(db_conn)

    assert load_nc_transaction(db_conn, committee_row, data_source_id) is True
    assert load_nc_transaction(db_conn, person_row, data_source_id) is True

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT ds.domain, ds.jurisdiction
            FROM core.organization o
            JOIN core.entity_source es
              ON es.entity_type = 'organization'
             AND es.entity_id = o.id
             AND es.extraction_role = 'recipient'
            JOIN core.source_record sr
              ON sr.id = es.source_record_id
            JOIN core.data_source ds
              ON ds.id = sr.data_source_id
            WHERE sr.source_record_key = %s
            LIMIT 1
            """,
            (compute_record_hash(dict(committee_row)),),
        )
        committee_provenance = cursor.fetchone()

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
            (compute_record_hash(dict(person_row)),),
        )
        person_provenance = cursor.fetchone()

    assert committee_provenance is not None
    assert committee_provenance["domain"] == "campaign_finance"
    assert committee_provenance["jurisdiction"] == "state/NC"

    assert person_provenance is not None
    assert person_provenance["domain"] == "campaign_finance"
    assert person_provenance["jurisdiction"] == "state/NC"


def test_load_nc_transactions_reports_insert_and_duplicate_skip_counts(
    tmp_path: Path,
    db_conn: psycopg.Connection,
) -> None:
    data_source_id = ensure_nc_data_source(db_conn)
    file_path = tmp_path / "unique-transactions.csv"
    rows = [
        _build_unique_nc_transaction_row(row, prefix=f"batch-{index}")
        for index, row in enumerate(_parsed_fixture_rows(), start=1)
    ]
    _write_dict_rows(file_path, columns=TRANSACTION_COLUMNS, rows=rows)

    first_result = load_nc_transactions(db_conn, file_path, data_source_id=data_source_id)
    second_result = load_nc_transactions(db_conn, file_path, data_source_id=data_source_id)

    assert isinstance(first_result, LoadResult)
    assert first_result.inserted == 5
    assert first_result.skipped == 0
    assert first_result.quarantined == 0
    assert first_result.errors == 0

    assert isinstance(second_result, LoadResult)
    assert second_result.inserted == 0
    assert second_result.skipped == 5
    assert second_result.quarantined == 0
    assert second_result.errors == 0


def test_load_nc_transactions_rejects_negative_limit(db_conn: psycopg.Connection) -> None:
    data_source_id = ensure_nc_data_source(db_conn)

    with pytest.raises(ValueError, match="greater than or equal to 0"):
        load_nc_transactions(db_conn, _SAMPLE_TRANSACTIONS_PATH, data_source_id=data_source_id, limit=-1)


def test_load_nc_transactions_counts_malformed_rows_as_quarantined(
    tmp_path: Path,
    db_conn: psycopg.Connection,
) -> None:
    row = _build_unique_nc_transaction_row(_parsed_fixture_rows()[0], prefix="malformed")
    headers = list(row)
    file_path = tmp_path / "malformed_transactions.csv"
    _write_transaction_rows(
        file_path,
        [
            [row[column_name] for column_name in headers],
            [row[column_name] for column_name in headers] + ["EXTRA"],
        ],
        headers,
    )
    data_source_id = ensure_nc_data_source(db_conn)

    result = load_nc_transactions(db_conn, file_path, data_source_id=data_source_id)

    assert result.inserted == 1
    assert result.skipped == 0
    assert result.quarantined == 1
    assert result.errors == 0


def test_load_nc_committee_registry_rows_is_idempotent_and_advances_last_seen_at(
    db_conn: psycopg.Connection,
) -> None:
    first_seen_at = datetime(2026, 4, 24, 9, 0, tzinfo=UTC)
    second_seen_at = datetime(2026, 4, 24, 9, 15, tzinfo=UTC)
    rows = [
        NCCommitteeRegistryRow(
            org_group_id=3970,
            sboe_id="STA-C3672N-C-001",
            committee_name="01ST CONG DIST BLACK LEADERSHIP CAUCUS",
            status_desc="CLOSED",
            old_id="7940000",
            candidate_name="CIVIC",
        )
    ]

    first_result = load_nc_committee_registry_rows(
        db_conn,
        rows,
        seen_at=first_seen_at,
    )
    first_registry_row = _select_nc_committee_registry_row(db_conn, org_group_id=3970)
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.nc_committee_registry
            WHERE org_group_id = %s
            """,
            (3970,),
        )
        first_registry_count = cursor.fetchone()["count"]

    second_result = load_nc_committee_registry_rows(
        db_conn,
        rows,
        seen_at=second_seen_at,
    )
    second_registry_row = _select_nc_committee_registry_row(db_conn, org_group_id=3970)
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.nc_committee_registry
            WHERE org_group_id = %s
            """,
            (3970,),
        )
        second_registry_count = cursor.fetchone()["count"]

    assert first_result.inserted == 1
    assert first_result.skipped == 0
    assert first_result.errors == 0
    assert second_result.inserted == 0
    assert second_result.skipped == 1
    assert second_result.errors == 0
    expected_second_registry_row = dict(first_registry_row)
    expected_second_registry_row["last_seen_at"] = second_seen_at
    assert first_registry_row["first_seen_at"] == first_seen_at
    assert second_registry_row["first_seen_at"] == first_seen_at
    assert first_registry_row["last_seen_at"] == first_seen_at
    assert second_registry_row["last_seen_at"] == second_seen_at
    assert second_registry_row == expected_second_registry_row
    assert first_registry_count == 1
    assert second_registry_count == first_registry_count


def test_load_nc_committee_registry_rows_updates_mutable_fields_on_rerun(
    db_conn: psycopg.Connection,
) -> None:
    initial_seen_at = datetime(2026, 4, 24, 10, 0, tzinfo=UTC)
    rerun_seen_at = datetime(2026, 4, 24, 10, 30, tzinfo=UTC)
    first_rows = [
        NCCommitteeRegistryRow(
            org_group_id=58871,
            sboe_id="STA-MAX-C-001",
            committee_name="MAX COMMITTEE",
            status_desc="ACTIVE (EXEMPT)",
            old_id="OLD-1",
            candidate_name="OLD CANDIDATE",
        )
    ]
    second_rows = [
        NCCommitteeRegistryRow(
            org_group_id=58871,
            sboe_id="STA-MAX-C-001",
            committee_name="MAX COMMITTEE UPDATED",
            status_desc="TERMINATED",
            old_id="OLD-UPDATED",
            candidate_name="NEW CANDIDATE",
        )
    ]

    first_result = load_nc_committee_registry_rows(
        db_conn,
        first_rows,
        seen_at=initial_seen_at,
    )
    second_result = load_nc_committee_registry_rows(
        db_conn,
        second_rows,
        seen_at=rerun_seen_at,
    )
    registry_row = _select_nc_committee_registry_row(db_conn, org_group_id=58871)

    assert first_result.inserted == 1
    assert second_result.inserted == 0
    assert second_result.skipped == 1
    assert registry_row["committee_name"] == "MAX COMMITTEE UPDATED"
    assert registry_row["status_desc"] == "TERMINATED"
    assert registry_row["candidate_name"] == "NEW CANDIDATE"
    assert registry_row["old_id"] == "OLD-UPDATED"
    assert registry_row["first_seen_at"] == initial_seen_at
    assert registry_row["last_seen_at"] == rerun_seen_at


def test_load_nc_transactions_with_filings_builds_relational_chain_from_stitched_fixture_rows(
    tmp_path: Path,
    db_conn: psycopg.Connection,
) -> None:
    transaction_rows = _parsed_fixture_rows()[:2]
    committee_row = dict(_parsed_committee_doc_rows()[1])
    committee_sboe_id = committee_row["SBoE ID"]
    assert committee_sboe_id is not None
    _insert_nc_committee_bridge(db_conn, committee_sboe_id=committee_sboe_id, committee_name="Stitched Committee")

    stitched_transaction_rows: list[dict[str, str | None]] = []
    for transaction_row in transaction_rows:
        stitched_row = dict(transaction_row)
        stitched_row["Committee SBoE ID"] = committee_sboe_id
        stitched_row["Committee Name"] = committee_row["Committee Name"]
        stitched_row["Report Name"] = f"{committee_row['Year']} {committee_row['Doc Name']}"
        stitched_transaction_rows.append(stitched_row)

    transaction_path = tmp_path / "stitched-transactions.csv"
    committee_path = tmp_path / "stitched-committee-docs.csv"
    _write_dict_rows(transaction_path, columns=TRANSACTION_COLUMNS, rows=stitched_transaction_rows)
    _write_dict_rows(committee_path, columns=COMMITTEE_DOC_COLUMNS, rows=[committee_row])

    result = load_nc_transactions_with_filings(db_conn, transaction_path, committee_path)
    assert result.inserted == 2
    assert result.skipped == 0
    assert result.errors == 0

    source_record_keys = [compute_record_hash(dict(row)) for row in stitched_transaction_rows]
    expected_filing_fec_id = "NC-001-4L70LV-C-001-2025-mid-year-semi-annual"

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT t.transaction_identifier,
                   t.source_record_id AS transaction_source_record_id,
                   f.filing_fec_id,
                   f.source_record_id AS filing_source_record_id,
                   ds_tx.name AS transaction_data_source_name,
                   ds_f.name AS filing_data_source_name,
                   o.identifiers ->> 'nc_sboe_id' AS committee_sboe_id,
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
            JOIN cf.committee c
              ON c.id = t.committee_id
            JOIN core.organization o
              ON o.id = c.organization_id
            JOIN core.source_record sr_tx
              ON sr_tx.id = t.source_record_id
            JOIN core.data_source ds_tx
              ON ds_tx.id = sr_tx.data_source_id
            JOIN core.source_record sr_f
              ON sr_f.id = f.source_record_id
            JOIN core.data_source ds_f
              ON ds_f.id = sr_f.data_source_id
            WHERE t.transaction_identifier = ANY(%s)
            ORDER BY t.transaction_identifier
            """,
            (source_record_keys,),
        )
        transaction_rows = cursor.fetchall()

    assert [row["transaction_identifier"] for row in transaction_rows] == sorted(source_record_keys)
    assert all(row["filing_fec_id"] == expected_filing_fec_id for row in transaction_rows)
    assert all(row["committee_sboe_id"] == committee_sboe_id for row in transaction_rows)
    assert all(
        row["transaction_data_source_name"] == "North Carolina SBoE Transaction Search" for row in transaction_rows
    )
    assert all(
        row["filing_data_source_name"] == "North Carolina SBoE Committee/Document Search" for row in transaction_rows
    )
    for row in transaction_rows:
        assert row["contributor_person_id"] == row["expected_contributor_person_id"]
        assert row["contributor_organization_id"] == row["expected_contributor_organization_id"]

    rerun_result = load_nc_transactions_with_filings(db_conn, transaction_path, committee_path)
    assert rerun_result.inserted == 0
    assert rerun_result.skipped == 2

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.transaction
            WHERE transaction_identifier = ANY(%s)
            """,
            (source_record_keys,),
        )
        transaction_count = cursor.fetchone()["count"]
    assert transaction_count == 2


def test_load_nc_transactions_with_filings_raises_for_missing_filing_join(
    tmp_path: Path,
    db_conn: psycopg.Connection,
) -> None:
    committee_row = dict(_parsed_committee_doc_rows()[0])
    committee_sboe_id = committee_row["SBoE ID"]
    assert committee_sboe_id is not None
    _insert_nc_committee_bridge(db_conn, committee_sboe_id=committee_sboe_id, committee_name="Missing Join Committee")

    transaction_row = dict(_parsed_fixture_rows()[0])
    transaction_row["Committee SBoE ID"] = committee_sboe_id
    transaction_row["Committee Name"] = committee_row["Committee Name"]
    transaction_row["Report Name"] = "2025 Nonexistent Report"

    transaction_path = tmp_path / "missing-join-transactions.csv"
    committee_path = tmp_path / "missing-join-committee-docs.csv"
    _write_dict_rows(transaction_path, columns=TRANSACTION_COLUMNS, rows=[transaction_row])
    _write_dict_rows(committee_path, columns=COMMITTEE_DOC_COLUMNS, rows=[committee_row])

    with pytest.raises(ValueError, match="No NC filing join match"):
        load_nc_transactions_with_filings(db_conn, transaction_path, committee_path)


def test_load_nc_transactions_with_filings_creates_missing_committee_bridge_from_docs(
    tmp_path: Path,
    db_conn: psycopg.Connection,
) -> None:
    committee_row = dict(_parsed_committee_doc_rows()[1])
    committee_sboe_id = committee_row["SBoE ID"]
    assert committee_sboe_id is not None

    transaction_row = dict(_parsed_fixture_rows()[0])
    transaction_row["Committee SBoE ID"] = committee_sboe_id
    transaction_row["Committee Name"] = committee_row["Committee Name"]
    transaction_row["Report Name"] = f"{committee_row['Year']} {committee_row['Doc Name']}"

    transaction_path = tmp_path / "missing-bridge-transactions.csv"
    committee_path = tmp_path / "missing-bridge-committee-docs.csv"
    _write_dict_rows(transaction_path, columns=TRANSACTION_COLUMNS, rows=[transaction_row])
    _write_dict_rows(committee_path, columns=COMMITTEE_DOC_COLUMNS, rows=[committee_row])

    result = load_nc_transactions_with_filings(db_conn, transaction_path, committee_path)
    assert result.inserted == 1
    assert result.errors == 0

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.committee c
            JOIN core.organization o
              ON o.id = c.organization_id
            WHERE c.state = 'NC'
              AND o.identifiers ->> 'nc_sboe_id' = %s
            """,
            (committee_sboe_id,),
        )
        committee_count = cursor.fetchone()["count"]

    assert committee_count == 1


def test_load_nc_transactions_with_filings_preserves_amended_lookup_state_for_duplicate_docs(
    tmp_path: Path,
    db_conn: psycopg.Connection,
) -> None:
    duplicate_rows = [dict(_parsed_committee_doc_rows()[6]), dict(_parsed_committee_doc_rows()[7])]
    committee_sboe_id = duplicate_rows[0]["SBoE ID"]
    assert committee_sboe_id is not None
    _insert_nc_committee_bridge(
        db_conn,
        committee_sboe_id=committee_sboe_id,
        committee_name="Duplicate Amend Committee",
    )

    transaction_row = dict(_parsed_fixture_rows()[0])
    transaction_row["Committee SBoE ID"] = committee_sboe_id
    transaction_row["Committee Name"] = duplicate_rows[0]["Committee Name"]
    transaction_row["Report Name"] = f"{duplicate_rows[0]['Year']} {duplicate_rows[0]['Doc Name']}"

    transaction_path = tmp_path / "duplicate-amend-transactions.csv"
    committee_path = tmp_path / "duplicate-amend-committee-docs.csv"
    _write_dict_rows(transaction_path, columns=TRANSACTION_COLUMNS, rows=[transaction_row])
    _write_dict_rows(committee_path, columns=COMMITTEE_DOC_COLUMNS, rows=duplicate_rows)

    load_nc_transactions_with_filings(db_conn, transaction_path, committee_path)

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT t.amendment_indicator AS transaction_amendment_indicator,
                   f.amendment_indicator AS filing_amendment_indicator
            FROM cf.transaction t
            JOIN cf.filing f
              ON f.id = t.filing_id
            WHERE t.transaction_identifier = %s
            LIMIT 1
            """,
            (compute_record_hash(transaction_row),),
        )
        row = cursor.fetchone()

    assert row is not None
    assert row["filing_amendment_indicator"] == "A"
    assert row["transaction_amendment_indicator"] == "A"
