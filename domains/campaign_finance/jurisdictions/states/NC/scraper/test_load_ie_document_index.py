from __future__ import annotations

import inspect
import json
from datetime import date
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from core.types.python.models import compute_record_hash
from domains.campaign_finance.jurisdictions.states.NC.scraper.load import (
    ensure_nc_ie_document_index_data_source,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.parse import (
    build_nc_committee_doc_linkage_key,
    parse_committee_docs,
)

pytestmark = pytest.mark.integration

_IE_DOCUMENT_INDEX_FIXTURE = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "cfdoclkup_ie_document_index_sample_2026_04_18.csv"
)
_STAGE1_LINKAGE_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "cfdoclkup_ie_document_index_stage1_linkage_sample_2026_04_24.csv"
)
_STAGE1_EXTRACTED_LINKS_FIXTURE = (
    Path(__file__).resolve().parents[6]
    / "docs"
    / "research"
    / "artifacts"
    / "2026_04_24_nc_ie_amounts"
    / "local"
    / "extracted_report_section_links.json"
)


@pytest.fixture(autouse=True)
def _disable_live_report_section_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    from domains.campaign_finance.jurisdictions.states.NC.scraper import load_ie_document_index as ie_loader

    monkeypatch.setattr(
        ie_loader,
        "fetch_ie_document_result_report_section_urls",
        lambda _year: {},
        raising=False,
    )


@pytest.fixture(autouse=True)
def _isolate_nc_ie_test_rows_via_savepoint_then_skip_on_lock_contention(
    db_conn: psycopg.Connection,
) -> None:
    """Skip NC IE doc-index integration tests when prod NC IE data exists.

    Why: the test fixtures insert source-records whose record_hash collides
    with rows the live `state-nc-ie-document-index` job already committed,
    so naive insert-then-rollback reads as `inserted=0, skipped=N` rather
    than `inserted=N`. An earlier autouse fixture issued blanket DELETEs
    inside the test transaction; under concurrent IRS 527 row locks those
    DELETEs blocked for tens of minutes, eventually leaking zombie
    backends after their ssh harness died and stalling the database.

    Safer approach: detect any committed NC IE rows up-front with a
    SHORT-timed read; if any exist, SKIP these integration tests with a
    clear reason. The CI/dedicated-test-DB path stays clean (no rows ->
    no skip), and the live-prod path no longer risks lock contention.
    """
    cursor_check = db_conn.execute("SET LOCAL statement_timeout = '2s'")  # short fail-fast
    try:
        row = db_conn.execute(
            "SELECT 1 FROM cf.filing WHERE filing_fec_id LIKE 'NC-IE-%' LIMIT 1"
        ).fetchone()
    except Exception as exc:  # noqa: BLE001 - any failure (timeout, etc.) means we cannot guarantee isolation
        pytest.skip(
            f"Skipping NC IE integration test: cannot verify clean DB state ({exc!r}); "
            "run against a dedicated test database instead."
        )
    finally:
        # Restore the default timeout for the rest of the test.
        db_conn.execute("SET LOCAL statement_timeout = 0")
    if row is not None:
        pytest.skip(
            "Skipping NC IE integration test: production cf.filing already contains NC-IE-% "
            "rows whose record_hashes collide with this test's fixtures. Run against a "
            "dedicated test database (set CF_SCHEMA_TEST_DATABASE) for these assertions."
        )
    _ = cursor_check  # noqa: F841 — explicit reference so the linter does not strip the SET


def _count_ie_filings(conn: psycopg.Connection) -> int:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM cf.filing
            WHERE filing_name = 'Independent Expenditure Report'
            """,
        )
        row = cursor.fetchone()
    assert row is not None
    return row["count"]


def _select_ie_filings(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT f.filing_fec_id, f.filing_name, f.report_type,
                   f.amendment_indicator, f.coverage_start_date,
                   f.coverage_end_date, f.receipt_date, f.accepted_date,
                   f.source_record_id, f.committee_id
            FROM cf.filing f
            WHERE f.filing_name = 'Independent Expenditure Report'
            ORDER BY f.coverage_start_date
            """,
        )
        return list(cursor.fetchall())


def _select_source_record_evidence_for_filing(
    conn: psycopg.Connection,
    filing_fec_id: str,
) -> dict:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT sr.source_record_key,
                   sr.raw_fields ->> 'report_section_url' AS report_section_url
            FROM cf.filing f
            JOIN core.source_record sr
              ON sr.id = f.source_record_id
            WHERE f.filing_fec_id = %s
            LIMIT 1
            """,
            (filing_fec_id,),
        )
        row = cursor.fetchone()
    assert row is not None, f"Missing filing/source_record evidence for {filing_fec_id!r}"
    return row


def _select_stage1_guilford_report_section_url() -> str:
    payload = json.loads(_STAGE1_EXTRACTED_LINKS_FIXTURE.read_text(encoding="utf-8"))
    for row in payload["rows"]:
        report_section_url = row.get("report_section_url")
        if report_section_url and "CN=GUILFORD-ROCKINGHAM+ALLIANCE" in report_section_url:
            return str(report_section_url)
    raise AssertionError("Stage 1 extracted links fixture is missing the expected GUILFORD report_section_url")


def test_load_nc_ie_document_index_symbol_contract() -> None:
    from domains.campaign_finance.jurisdictions.states.NC.scraper.load import (
        load_nc_ie_document_index,
    )

    assert callable(load_nc_ie_document_index)
    sig = inspect.signature(load_nc_ie_document_index)
    param_names = list(sig.parameters.keys())
    assert param_names[0] == "conn"
    assert param_names[1] == "file_path"
    assert "data_source_id" in param_names
    assert "limit" in param_names
    assert sig.parameters["limit"].default is None


def test_load_nc_ie_document_index_contract_loads_fixture_rows(
    db_conn: psycopg.Connection,
) -> None:
    from domains.campaign_finance.jurisdictions.states.NC.scraper.load import (
        load_nc_ie_document_index,
    )

    data_source_id = ensure_nc_ie_document_index_data_source(db_conn)
    result = load_nc_ie_document_index(
        db_conn,
        _IE_DOCUMENT_INDEX_FIXTURE,
        data_source_id=data_source_id,
    )

    assert result.inserted == 3
    assert result.skipped == 0
    assert result.errors == 0
    assert _count_ie_filings(db_conn) == 3

    filings = _select_ie_filings(db_conn)
    assert len(filings) == 3
    assert all(f["filing_name"] == "Independent Expenditure Report" for f in filings)
    assert all(f["report_type"] == "Disclosure Report" for f in filings)
    assert all(f["source_record_id"] is not None for f in filings)
    assert all(f["committee_id"] is not None for f in filings)

    amended_row = next(f for f in filings if f["amendment_indicator"] == "A")
    assert amended_row["coverage_start_date"] == date(2026, 1, 1)
    assert amended_row["coverage_end_date"] == date(2026, 2, 14)

    original_rows = [f for f in filings if f["amendment_indicator"] == "N"]
    assert len(original_rows) == 2


def test_load_nc_ie_document_index_contract_accepts_no_id_sboe_rows(
    db_conn: psycopg.Connection,
) -> None:
    from domains.campaign_finance.jurisdictions.states.NC.scraper.load import (
        load_nc_ie_document_index,
    )

    data_source_id = ensure_nc_ie_document_index_data_source(db_conn)
    result = load_nc_ie_document_index(
        db_conn,
        _IE_DOCUMENT_INDEX_FIXTURE,
        data_source_id=data_source_id,
    )

    assert result.inserted == 3

    filings = _select_ie_filings(db_conn)
    committee_ids = {f["committee_id"] for f in filings}
    assert len(committee_ids) == 3, "Each 'No Id' committee name should resolve to a distinct committee"


def test_load_nc_ie_document_index_contract_is_idempotent(
    db_conn: psycopg.Connection,
) -> None:
    from domains.campaign_finance.jurisdictions.states.NC.scraper.load import (
        load_nc_ie_document_index,
    )

    data_source_id = ensure_nc_ie_document_index_data_source(db_conn)
    first_result = load_nc_ie_document_index(
        db_conn,
        _IE_DOCUMENT_INDEX_FIXTURE,
        data_source_id=data_source_id,
    )
    first_filings = _select_ie_filings(db_conn)
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, source_record_key, record_hash, raw_fields, pull_date
            FROM core.source_record
            WHERE id = ANY(%s)
            ORDER BY source_record_key
            """,
            ([row["source_record_id"] for row in first_filings],),
        )
        first_source_record_snapshot = list(cursor.fetchall())

    assert first_result.inserted == 3
    assert len(first_filings) == 3
    assert len(first_source_record_snapshot) == 3

    second_result = load_nc_ie_document_index(
        db_conn,
        _IE_DOCUMENT_INDEX_FIXTURE,
        data_source_id=data_source_id,
    )
    second_filings = _select_ie_filings(db_conn)
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT id, source_record_key, record_hash, raw_fields, pull_date
            FROM core.source_record
            WHERE id = ANY(%s)
            ORDER BY source_record_key
            """,
            ([row["source_record_id"] for row in second_filings],),
        )
        second_source_record_snapshot = list(cursor.fetchall())

    assert second_result.inserted == 0
    assert second_result.skipped == 3
    assert second_result.errors == 0
    assert _count_ie_filings(db_conn) == 3
    assert second_filings == first_filings
    assert second_source_record_snapshot == first_source_record_snapshot


def test_load_nc_ie_document_index_contract_repairs_partial_failures_with_existing_source_records(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from domains.campaign_finance.jurisdictions.states.NC.scraper import load_ie_document_index as ie_loader
    from domains.campaign_finance.jurisdictions.states.NC.scraper.load import (
        load_nc_ie_document_index,
    )

    data_source_id = ensure_nc_ie_document_index_data_source(db_conn)
    original_upsert_filing = ie_loader.upsert_filing
    upsert_call_count = 0

    def _fail_first_upsert(conn: psycopg.Connection, filing) -> object:
        nonlocal upsert_call_count
        upsert_call_count += 1
        if upsert_call_count == 1:
            raise RuntimeError("simulated filing upsert failure")
        return original_upsert_filing(conn, filing)

    monkeypatch.setattr(ie_loader, "upsert_filing", _fail_first_upsert)

    first_result = load_nc_ie_document_index(
        db_conn,
        _IE_DOCUMENT_INDEX_FIXTURE,
        data_source_id=data_source_id,
    )
    assert first_result.inserted == 2
    assert first_result.errors == 1
    assert _count_ie_filings(db_conn) == 2

    monkeypatch.setattr(ie_loader, "upsert_filing", original_upsert_filing)
    second_result = load_nc_ie_document_index(
        db_conn,
        _IE_DOCUMENT_INDEX_FIXTURE,
        data_source_id=data_source_id,
    )
    assert second_result.inserted == 1
    assert second_result.skipped == 2
    assert second_result.errors == 0
    assert _count_ie_filings(db_conn) == 3


def test_load_nc_ie_document_index_stage1_linkage_fixture_persists_report_section_url_without_identity_drift(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from domains.campaign_finance.jurisdictions.states.NC.scraper import load_ie_document_index as ie_loader
    from domains.campaign_finance.jurisdictions.states.NC.scraper.load import (
        load_nc_ie_document_index,
    )

    rows = list(parse_committee_docs(_STAGE1_LINKAGE_FIXTURE))
    assert len(rows) == 2
    row_with_data_link, row_without_data_link = rows
    stage1_report_section_url = _select_stage1_guilford_report_section_url()
    linkage_urls_by_row_key = {
        build_nc_committee_doc_linkage_key(row_with_data_link): [stage1_report_section_url],
        build_nc_committee_doc_linkage_key(row_without_data_link): [None],
    }
    monkeypatch.setattr(
        ie_loader,
        "fetch_ie_document_result_report_section_urls",
        lambda year: linkage_urls_by_row_key if year == 2026 else {},
        raising=False,
    )

    data_source_id = ensure_nc_ie_document_index_data_source(db_conn)
    result = load_nc_ie_document_index(
        db_conn,
        _STAGE1_LINKAGE_FIXTURE,
        data_source_id=data_source_id,
    )

    assert result.inserted == 2
    assert result.skipped == 0
    assert result.errors == 0

    with_link_hash = compute_record_hash(dict(row_with_data_link))
    without_link_hash = compute_record_hash(dict(row_without_data_link))
    with_link_evidence = _select_source_record_evidence_for_filing(
        db_conn,
        filing_fec_id=f"NC-IE-{with_link_hash}",
    )
    without_link_evidence = _select_source_record_evidence_for_filing(
        db_conn,
        filing_fec_id=f"NC-IE-{without_link_hash}",
    )

    assert with_link_evidence["source_record_key"] == with_link_hash
    assert with_link_evidence["report_section_url"] == stage1_report_section_url

    assert without_link_evidence["source_record_key"] == without_link_hash
    assert without_link_evidence["report_section_url"] is None
