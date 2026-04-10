from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from core.types.python.models import compute_record_hash
from domains.campaign_finance.jurisdictions.states.NC.scraper.load import (
    ensure_nc_committee_document_data_source,
    ensure_nc_data_source,
    load_nc_committee_documents,
    load_nc_transactions,
    load_nc_transactions_with_filings,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.parse import (
    COMMITTEE_DOC_COLUMNS,
    TRANSACTION_COLUMNS,
    parse_committee_docs,
    parse_transactions,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.test_load import (
    _entity_source_count,
    _insert_nc_committee_bridge,
    _parsed_committee_doc_rows,
    _source_record_id,
    _write_dict_rows,
)

pytestmark = pytest.mark.integration

_SAMPLE_COMMITTEE_DOCS_PATH = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "committee_document_export_sample.csv"
)
_REAL_TRANSACTIONS_PATH = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "real_transaction_export_adams.csv"
)
_REAL_COMMITTEE_DOCS_PATH = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "real_committee_doc_export_3517.csv"
)
_REAL_FILING_OVERLAP_SBOE_ID = "STA-C3219N-C-001"
_REAL_FILING_OVERLAP_COMMITTEE_NAME = "NC REALTORS PAC"


def _real_data_artifacts_available() -> bool:
    return _REAL_TRANSACTIONS_PATH.exists() and _REAL_COMMITTEE_DOCS_PATH.exists()


def _parsed_real_transaction_rows() -> list[dict[str, str | None]]:
    return list(parse_transactions(_REAL_TRANSACTIONS_PATH))


def _parsed_real_committee_doc_rows() -> list[dict[str, str | None]]:
    return list(parse_committee_docs(_REAL_COMMITTEE_DOCS_PATH))


def _select_filing_fec_ids(conn: psycopg.Connection, prefix: str) -> list[str]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT filing_fec_id
            FROM cf.filing
            WHERE filing_fec_id LIKE %s
            ORDER BY filing_fec_id
            """,
            (f"{prefix}%",),
        )
        rows = cursor.fetchall()
    return [row["filing_fec_id"] for row in rows]


def _filter_real_transactions_for_committee(
    committee_sboe_id: str,
) -> list[dict[str, str | None]]:
    return [row for row in _parsed_real_transaction_rows() if row.get("Committee SBoE ID") == committee_sboe_id]


def test_load_nc_committee_documents_creates_filings_and_bridges_committees(
    db_conn: psycopg.Connection,
) -> None:
    committee_rows = _parsed_committee_doc_rows()
    committee_sboe_id = committee_rows[0]["SBoE ID"]
    assert committee_sboe_id is not None
    _insert_nc_committee_bridge(db_conn, committee_sboe_id=committee_sboe_id, committee_name="Fixture Committee")

    committee_document_data_source_id = ensure_nc_committee_document_data_source(db_conn)
    result, filing_lookup = load_nc_committee_documents(
        db_conn,
        _SAMPLE_COMMITTEE_DOCS_PATH,
        data_source_id=committee_document_data_source_id,
    )

    assert result.inserted == 8
    assert result.skipped == 0
    assert result.quarantined == 0
    assert result.errors == 0
    assert len(filing_lookup) == 7
    assert "NC-001-4L70LV-C-001-2025-mid-year-semi-annual" in _select_filing_fec_ids(
        db_conn,
        "NC-001-4L70LV-C-001-",
    )

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

        cursor.execute(
            """
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE amendment_indicator = 'A') AS amended
            FROM cf.filing
            WHERE filing_fec_id LIKE 'NC-001-4L70LV-C-001-%'
            """,
        )
        filing_counts = cursor.fetchone()

        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.filing f
            JOIN core.source_record sr
              ON sr.id = f.source_record_id
            JOIN core.data_source ds
              ON ds.id = sr.data_source_id
            WHERE f.filing_fec_id LIKE 'NC-001-4L70LV-C-001-%'
              AND ds.name = 'North Carolina SBoE Committee/Document Search'
            """
        )
        filing_provenance_count = cursor.fetchone()["count"]

    assert committee_count == 1
    assert filing_counts["total"] == 7
    assert filing_counts["amended"] == 1
    assert filing_provenance_count == 7


def test_load_nc_committee_documents_is_idempotent_for_filings_and_committees(
    db_conn: psycopg.Connection,
) -> None:
    committee_sboe_id = "001-4L70LV-C-001"
    _insert_nc_committee_bridge(db_conn, committee_sboe_id=committee_sboe_id, committee_name="Idempotent Committee")
    committee_document_data_source_id = ensure_nc_committee_document_data_source(db_conn)

    first_result, _ = load_nc_committee_documents(
        db_conn,
        _SAMPLE_COMMITTEE_DOCS_PATH,
        data_source_id=committee_document_data_source_id,
    )
    filing_ids_after_first = _select_filing_fec_ids(db_conn, "NC-001-4L70LV-C-001-")

    second_result, _ = load_nc_committee_documents(
        db_conn,
        _SAMPLE_COMMITTEE_DOCS_PATH,
        data_source_id=committee_document_data_source_id,
    )
    filing_ids_after_second = _select_filing_fec_ids(db_conn, "NC-001-4L70LV-C-001-")

    assert first_result.inserted == 8
    assert second_result.inserted == 0
    assert second_result.skipped == 8
    assert filing_ids_after_second == filing_ids_after_first

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


def test_real_data_artifacts_parse_and_expose_filing_overlap() -> None:
    if not _real_data_artifacts_available():
        pytest.skip("Real-data artifacts not present")

    txn_rows = _parsed_real_transaction_rows()
    doc_rows = _parsed_real_committee_doc_rows()

    assert len(txn_rows) > 0, "Transaction export should not be empty"
    assert len(doc_rows) > 0, "Committee-doc export should not be empty"

    txn_keys = {(row["Committee SBoE ID"], row["Report Name"]) for row in txn_rows}
    doc_keys = {
        (row["SBoE ID"], f"{row['Year']} {row['Doc Name']}")
        for row in doc_rows
        if row.get("Doc Type") == "Disclosure Report"
    }
    overlap = txn_keys & doc_keys
    assert len(overlap) >= 1, (
        "Real-data artifacts must share at least one (Committee SBoE ID, Report Name) pair for filing-aware tests"
    )


def test_real_data_transactions_load_without_filings(
    db_conn: psycopg.Connection,
) -> None:
    if not _real_data_artifacts_available():
        pytest.skip("Real-data artifacts not present")

    data_source_id = ensure_nc_data_source(db_conn)
    expected_row_count = len(_parsed_real_transaction_rows())

    first_result = load_nc_transactions(
        db_conn,
        _REAL_TRANSACTIONS_PATH,
        data_source_id=data_source_id,
    )

    assert first_result.inserted == expected_row_count
    assert first_result.skipped == 0
    assert first_result.errors == 0

    second_result = load_nc_transactions(
        db_conn,
        _REAL_TRANSACTIONS_PATH,
        data_source_id=data_source_id,
    )
    assert second_result.inserted == 0
    assert second_result.skipped == expected_row_count

    first_row = _parsed_real_transaction_rows()[0]
    source_record_key = compute_record_hash(dict(first_row))
    sr_id = _source_record_id(db_conn, data_source_id, source_record_key)
    person_count = _entity_source_count(db_conn, sr_id, "person", "donor")
    assert person_count >= 1, "Expected at least one person entity_source for a real transaction row"


def test_real_data_transactions_with_filings_builds_relational_chain(
    tmp_path: Path,
    db_conn: psycopg.Connection,
) -> None:
    if not _real_data_artifacts_available():
        pytest.skip("Real-data artifacts not present")

    matching_rows = _filter_real_transactions_for_committee(
        _REAL_FILING_OVERLAP_SBOE_ID,
    )
    assert len(matching_rows) >= 1, f"Expected at least 1 transaction for {_REAL_FILING_OVERLAP_SBOE_ID}"

    _insert_nc_committee_bridge(
        db_conn,
        committee_sboe_id=_REAL_FILING_OVERLAP_SBOE_ID,
        committee_name=_REAL_FILING_OVERLAP_COMMITTEE_NAME,
    )

    filtered_txn_path = tmp_path / "filtered-real-transactions.csv"
    _write_dict_rows(
        filtered_txn_path,
        columns=TRANSACTION_COLUMNS,
        rows=matching_rows,
    )

    result = load_nc_transactions_with_filings(
        db_conn,
        filtered_txn_path,
        _REAL_COMMITTEE_DOCS_PATH,
    )
    assert result.inserted == len(matching_rows)
    assert result.skipped == 0
    assert result.errors == 0

    source_record_keys = [compute_record_hash(dict(row)) for row in matching_rows]
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT t.transaction_identifier,
                   f.filing_fec_id,
                   o.identifiers ->> 'nc_sboe_id' AS committee_sboe_id,
                   ds_tx.name AS transaction_data_source_name,
                   ds_f.name AS filing_data_source_name
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
        chain_rows = cursor.fetchall()

    assert len(chain_rows) == len(matching_rows), f"Expected {len(matching_rows)} chain rows, got {len(chain_rows)}"
    for row in chain_rows:
        assert row["committee_sboe_id"] == _REAL_FILING_OVERLAP_SBOE_ID
        assert row["transaction_data_source_name"] == "North Carolina SBoE Transaction Search"
        assert row["filing_data_source_name"] == "North Carolina SBoE Committee/Document Search"
        assert row["filing_fec_id"].startswith("NC-STA-C3219N-C-001-")

    rerun_result = load_nc_transactions_with_filings(
        db_conn,
        filtered_txn_path,
        _REAL_COMMITTEE_DOCS_PATH,
    )
    assert rerun_result.inserted == 0
    assert rerun_result.skipped == len(matching_rows)


def test_load_nc_committee_documents_duplicate_lookup_keys_collapse_to_single_filing(
    tmp_path: Path,
    db_conn: psycopg.Connection,
) -> None:
    duplicate_rows = [dict(_parsed_committee_doc_rows()[6]), dict(_parsed_committee_doc_rows()[7])]
    committee_sboe_id = duplicate_rows[0]["SBoE ID"]
    assert committee_sboe_id is not None
    _insert_nc_committee_bridge(db_conn, committee_sboe_id=committee_sboe_id, committee_name="Duplicate Key Committee")

    duplicate_docs_path = tmp_path / "duplicate-committee-docs.csv"
    _write_dict_rows(duplicate_docs_path, columns=COMMITTEE_DOC_COLUMNS, rows=duplicate_rows)

    committee_document_data_source_id = ensure_nc_committee_document_data_source(db_conn)
    result, filing_lookup = load_nc_committee_documents(
        db_conn,
        duplicate_docs_path,
        data_source_id=committee_document_data_source_id,
    )

    assert result.inserted == 2
    assert len(filing_lookup) == 1
    assert _select_filing_fec_ids(db_conn, "NC-001-4L70LV-C-001-2023-thirty-five-day") == [
        "NC-001-4L70LV-C-001-2023-thirty-five-day"
    ]

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT amendment_indicator
            FROM cf.filing
            WHERE filing_fec_id = 'NC-001-4L70LV-C-001-2023-thirty-five-day'
            """,
        )
        filing_row = cursor.fetchone()
    assert filing_row["amendment_indicator"] == "A"


def test_real_committee_docs_blank_doc_name_rows_keep_source_record_provenance(
    tmp_path: Path,
    db_conn: psycopg.Connection,
) -> None:
    blank_doc_rows = [row for row in _parsed_real_committee_doc_rows() if not (row.get("Doc Name") or "").strip()]
    assert blank_doc_rows, "Expected retained real committee-doc fixture to include blank Doc Name rows"

    blank_row = dict(blank_doc_rows[0])
    blank_row["Committee Name"] = f"{blank_row.get('Committee Name') or 'Blank Doc Committee'} {uuid4().hex[:8]}"
    committee_sboe_id = blank_row["SBoE ID"]
    assert committee_sboe_id is not None
    _insert_nc_committee_bridge(
        db_conn,
        committee_sboe_id=committee_sboe_id,
        committee_name="Real Blank Doc Committee",
    )

    blank_docs_path = tmp_path / "blank-doc-name-committee-docs.csv"
    _write_dict_rows(blank_docs_path, columns=COMMITTEE_DOC_COLUMNS, rows=[blank_row])

    committee_document_data_source_id = ensure_nc_committee_document_data_source(db_conn)
    first_result, first_lookup = load_nc_committee_documents(
        db_conn,
        blank_docs_path,
        data_source_id=committee_document_data_source_id,
    )
    second_result, second_lookup = load_nc_committee_documents(
        db_conn,
        blank_docs_path,
        data_source_id=committee_document_data_source_id,
    )

    assert first_result.inserted == 1
    assert first_result.skipped == 0
    assert second_result.inserted == 0
    assert second_result.skipped == 1
    assert first_lookup == {}
    assert second_lookup == {}

    source_record_id = _source_record_id(
        db_conn,
        committee_document_data_source_id,
        compute_record_hash(blank_row),
    )
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.filing
            WHERE source_record_id = %s
            """,
            (source_record_id,),
        )
        filing_count = cursor.fetchone()["count"]

    assert filing_count == 0


def test_load_nc_committee_documents_raises_on_unknown_amendment_flag(
    tmp_path: Path,
    db_conn: psycopg.Connection,
) -> None:
    committee_row = dict(_parsed_committee_doc_rows()[0])
    committee_row["Amend"] = "UNKNOWN"
    committee_sboe_id = committee_row["SBoE ID"]
    assert committee_sboe_id is not None
    _insert_nc_committee_bridge(db_conn, committee_sboe_id=committee_sboe_id, committee_name="Bad Amend Committee")

    committee_path = tmp_path / "unknown-amend-committee-docs.csv"
    _write_dict_rows(committee_path, columns=COMMITTEE_DOC_COLUMNS, rows=[committee_row])

    committee_document_data_source_id = ensure_nc_committee_document_data_source(db_conn)
    with pytest.raises(ValueError, match="Unknown NC amendment flag"):
        load_nc_committee_documents(db_conn, committee_path, data_source_id=committee_document_data_source_id)
