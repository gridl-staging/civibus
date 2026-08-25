from __future__ import annotations

import csv
import inspect
import json
from collections import Counter
from contextlib import ExitStack
from datetime import date, datetime, timezone
from pathlib import Path
from typing import NamedTuple
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from core.db import get_connection
from core.types.python.models import compute_record_hash
from domains.campaign_finance.ingest.filing_loader import generate_synthetic_committee_id
from domains.campaign_finance.jurisdictions._bulk_fixture_support import (
    BulkFixtureInterruption,
    bulk_fixture_entity_row_counts,
    bulk_fixture_row_counts,
    install_write_interrupt,
    seed_bulk_fixture,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.load import (
    LoadResult,
    ensure_nc_ie_document_index_data_source,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.load_support import (
    resolve_nc_ie_data_source_before_managed_load,
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
    / "reference"
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
        row = db_conn.execute("SELECT 1 FROM cf.filing WHERE filing_fec_id LIKE 'NC-IE-%' LIMIT 1").fetchone()
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


# --- Stage 4: the persistence loop commits each completed batch mid-loop ------
#
# `_EXPECTED_DURABLE_BATCH_ROWS` is a frozen literal, deliberately NOT read from
# `ie_index_loader._COMMIT_BATCH_ROWS`. The falsifiability probe for these specimens
# monkeypatches that module constant above the fixture size; an expectation derived from
# the live constant would move with the probe and they could never go red.

_EXPECTED_DURABLE_BATCH_ROWS = 1_000
_NC_BULK_ROW_COUNT = _EXPECTED_DURABLE_BATCH_ROWS + 1
# Rows whose persistence raises, so the loop counts them as errors and must still advance
# the boundary: they opened a transaction just like a successful row did.
_NC_ERRORED_ROWS = 3
# Every row shares one committee, and the loader writes no contributor person or address
# rows, so a completed load's whole entity footprint is that one committee.
_NC_LOADED_COMMITTEE_ROWS = 1


class NCDocIndexBulkFixture(NamedTuple):
    """One synthetic NC committee-document CSV and the identities it writes."""

    committee_docs_path: Path
    run_suffix: str
    committee_sboe_id: str
    source_record_keys: list[str]

    @property
    def committee_fec_id(self) -> str:
        return generate_synthetic_committee_id("NC", self.committee_sboe_id)


def _write_nc_ie_document_index_fixture(tmp_path: Path, *, row_count: int) -> NCDocIndexBulkFixture:
    """Write a committee-document CSV whose every row is a distinct IE candidate.

    All rows share one per-run SBoE id and committee name so the load resolves a single
    committee, while each row carries a distinct ``Image`` token — and therefore a
    distinct whole-row hash, which is both the row's ``source_record_key`` and the
    identity its ``filing_fec_id`` is built from. That is what lets the fixture cross
    ``ie_index_loader._COMMIT_BATCH_ROWS`` and still be cleaned up by its own scoped keys.
    """
    if row_count < 1:
        raise ValueError(f"row_count must be >= 1, got {row_count}")

    run_suffix = uuid4().hex[:12]
    committee_sboe_id = f"NCDOC{run_suffix}"
    committee_docs_path = tmp_path / f"nc_ie_bounded_{run_suffix}_committee_docs.csv"

    with _IE_DOCUMENT_INDEX_FIXTURE.open(encoding="utf-8", newline="") as sample_file:
        reader = csv.DictReader(sample_file)
        fieldnames = list(reader.fieldnames or [])
        base_row = next(row for row in reader if row["Doc Name"] == "Independent Expenditure Report")

    rows: list[dict[str, str]] = []
    for index in range(row_count):
        row = dict(base_row)
        row["Committee Name"] = f"NC Bounded Commit Test Committee {run_suffix}"
        row["SBoE ID"] = committee_sboe_id
        row["Year"] = str(datetime.now(timezone.utc).year)
        row["Image"] = f"IMAGE-{run_suffix}-{index}"
        rows.append(row)

    with committee_docs_path.open("w", encoding="utf-8", newline="") as fixture_file:
        writer = csv.DictWriter(fixture_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Derived by re-parsing the file the loader will read, so the keys cannot drift from
    # the ones a real load writes.
    source_record_keys = [compute_record_hash(dict(row)) for row in parse_committee_docs(committee_docs_path)]
    return NCDocIndexBulkFixture(
        committee_docs_path=committee_docs_path,
        run_suffix=run_suffix,
        committee_sboe_id=committee_sboe_id,
        source_record_keys=source_record_keys,
    )


def _nc_fixture_filing_count(fixture: NCDocIndexBulkFixture) -> int:
    """Count the filings linked to this fixture's source records, independently observed."""
    observer_conn = get_connection()
    try:
        with observer_conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM cf.filing
                WHERE source_record_id IN (
                    SELECT id FROM core.source_record WHERE source_record_key = ANY(%s)
                )
                """,
                (fixture.source_record_keys,),
            )
            return cursor.fetchone()[0]
    finally:
        observer_conn.close()


def _seed_nc_doc_index_fixture(
    resources: ExitStack,
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> tuple[NCDocIndexBulkFixture, psycopg.Connection, UUID]:
    """Write the fixture, hand it to the shared seeding contract, and open the loader's connection.

    The data source is resolved through the same helper production uses, so the loader
    receives an IDLE connection and owns its own commit boundary.
    """
    fixture = _write_nc_ie_document_index_fixture(tmp_path, row_count=_NC_BULK_ROW_COUNT)
    seed_bulk_fixture(resources, db_conn, fixture, expected_unique_source_record_keys=_NC_BULK_ROW_COUNT)
    loader_conn = get_connection()
    resources.callback(loader_conn.close)
    data_source_id = resolve_nc_ie_data_source_before_managed_load(loader_conn)
    assert loader_conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
    return fixture, loader_conn, data_source_id


def test_load_nc_ie_document_index_commits_batch_mid_loop(
    db_conn: psycopg.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An interrupt on row 1,001 leaves exactly the first 1,000 rows durable.

    Before Stage 4 the persistence loop committed once, at the end of the job, so this
    interruption discarded every row and an independent connection saw zero.
    """
    from domains.campaign_finance.jurisdictions.states.NC.scraper import load_ie_document_index as ie_index_loader

    with ExitStack() as resources:
        fixture, loader_conn, data_source_id = _seed_nc_doc_index_fixture(resources, db_conn, tmp_path)
        row_counts = install_write_interrupt(
            monkeypatch,
            ie_index_loader,
            "_load_nc_ie_document_index_row",
            raise_after_writes=_EXPECTED_DURABLE_BATCH_ROWS,
        )

        with pytest.raises(BulkFixtureInterruption):
            ie_index_loader.load_nc_ie_document_index(
                loader_conn,
                fixture.committee_docs_path,
                data_source_id=data_source_id,
            )
        loader_conn.rollback()

        assert row_counts["writes"] == _NC_BULK_ROW_COUNT
        source_record_count, _ = bulk_fixture_row_counts(fixture)
        assert source_record_count == _EXPECTED_DURABLE_BATCH_ROWS
        assert _nc_fixture_filing_count(fixture) == _EXPECTED_DURABLE_BATCH_ROWS

        # The bridge organisation and committee behind those filings are part of the
        # fixture's footprint too; the stack's cleanup deletes them and re-reads this
        # same count, so a cleanup that stops covering them fails this specimen.
        assert bulk_fixture_entity_row_counts(fixture) == {
            "person": 0,
            "organization": _NC_LOADED_COMMITTEE_ROWS,
            "address": 0,
            "committee": _NC_LOADED_COMMITTEE_ROWS,
        }


def test_load_nc_ie_document_index_batch_boundary_advances_on_errored_rows(
    db_conn: psycopg.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rows whose persistence raises still advance the commit boundary.

    Three rows fail before writing anything, so the loop counts them as errors. The
    boundary counts iterated rows rather than persisted ones, so it still fires on
    iteration 1,000 — with only 997 rows written by then. Counting persisted rows instead
    would push the first commit three rows later, past the interrupt, and leave nothing
    durable.
    """
    from domains.campaign_finance.jurisdictions.states.NC.scraper import load_ie_document_index as ie_index_loader

    with ExitStack() as resources:
        fixture, loader_conn, data_source_id = _seed_nc_doc_index_fixture(resources, db_conn, tmp_path)
        expected_durable_rows = _EXPECTED_DURABLE_BATCH_ROWS - _NC_ERRORED_ROWS
        real_load_row = ie_index_loader._load_nc_ie_document_index_row
        attempts = Counter[str]()

        def _failing_then_interrupting_row_load(conn, **kwargs):
            attempts["rows"] += 1
            if attempts["rows"] <= _NC_ERRORED_ROWS:
                raise ValueError("synthetic NC IE doc-index row failure")
            if attempts["rows"] > _NC_BULK_ROW_COUNT - 1:
                raise BulkFixtureInterruption("nc ie doc-index batch interruption")
            return real_load_row(conn, **kwargs)

        monkeypatch.setattr(
            ie_index_loader,
            "_load_nc_ie_document_index_row",
            _failing_then_interrupting_row_load,
        )

        with pytest.raises(BulkFixtureInterruption):
            ie_index_loader.load_nc_ie_document_index(
                loader_conn,
                fixture.committee_docs_path,
                data_source_id=data_source_id,
            )
        loader_conn.rollback()

        assert attempts["rows"] == _NC_BULK_ROW_COUNT
        source_record_count, _ = bulk_fixture_row_counts(fixture)
        assert source_record_count == expected_durable_rows
        assert _nc_fixture_filing_count(fixture) == expected_durable_rows


def test_cli_ie_document_index_load_hands_the_loader_an_idle_connection() -> None:
    """`run_nc_refresh`'s doc-index arm must resolve the data source *before* the loader.

    The data-source lookup opens a transaction. Running it after ownership is sampled —
    the ordering this repo shipped before Stage 4 — makes the loader read INTRANS, treat
    an outer caller as the transaction owner, and turn its 1,000-row commit boundary into
    a no-op, so an interrupted bulk load loses every completed batch.
    """
    from domains.campaign_finance.jurisdictions.states.NC.scraper import cli

    observed_transaction_status: list[object] = []

    def _recording_loader(conn, _file_path, *, data_source_id, limit):
        observed_transaction_status.append(conn.info.transaction_status)
        assert data_source_id is not None
        assert limit is None
        return LoadResult(inserted=0, skipped=0, quarantined=0, superseded=0, errors=0, elapsed_seconds=0.0)

    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(cli, "load_nc_ie_document_index", _recording_loader)
        connection = get_connection()
        try:
            cli._load_ie_document_index_data(connection, _IE_DOCUMENT_INDEX_FIXTURE, limit=None)
        finally:
            connection.rollback()
            connection.close()

    assert observed_transaction_status == [psycopg.pq.TransactionStatus.IDLE]
