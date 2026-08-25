from __future__ import annotations

from contextlib import ExitStack
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import NamedTuple
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from core.db import get_connection, try_insert_source_record
from core.types.python.models import SourceRecord, compute_record_hash, utc_now
from domains.campaign_finance.ingest.filing_loader import (
    generate_synthetic_committee_id,
    upsert_filing,
)
from domains.campaign_finance.jurisdictions._bulk_fixture_support import (
    BulkFixtureInterruption,
    bulk_fixture_entity_row_counts,
    bulk_fixture_row_counts,
    install_write_interrupt,
    seed_bulk_fixture,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper import load as nc_load_module
from domains.campaign_finance.jurisdictions.states.NC.scraper import load_ie_transactions as ie_tx_loader
from domains.campaign_finance.jurisdictions.states.NC.scraper.load import (
    LoadResult,
    ensure_nc_ie_document_index_data_source,
    load_nc_ie_document_index,
    load_nc_ie_transactions,
    resolve_nc_committee_bridge,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.load_support import (
    resolve_nc_ie_data_source_before_managed_load,
    set_nc_source_record_report_section_url,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.parse_ie_report_section import (
    NCIEReportRow,
    parse_ie_report_section_csv,
)
from domains.campaign_finance.types.models import Filing

pytestmark = pytest.mark.integration

_IE_DOCUMENT_INDEX_FIXTURE = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "nc_ie_document_index_known_answer.csv"
)
_KNOWN_ANSWER_DETAIL_FIXTURE = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "nc_ie_report_detail_known_answer.csv"
)
_KNOWN_REPORT_SECTION_URL = (
    "https://cf.ncsbe.gov/CFOrgLkup/ReportSection/?RID=229253&SID=No+Id"
    "&CN=ADVANCE+NORTH+CAROLINA&RN=2026+Independent+Expenditure+Report"
)


@pytest.fixture(autouse=True)
def _skip_when_prod_nc_ie_data_is_present(db_conn: psycopg.Connection) -> None:
    """Skip this integration test when prod NC IE data exists in the same DB.

    See test_load_ie_document_index for the full rationale. The earlier
    DELETE-based isolation caused row-lock contention with concurrent IRS
    527 ingest, leaving zombie pytest backends that stalled the database.
    """
    db_conn.execute("SET LOCAL statement_timeout = '2s'")
    try:
        row = db_conn.execute("SELECT 1 FROM cf.filing WHERE filing_fec_id LIKE 'NC-IE-%' LIMIT 1").fetchone()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Skipping NC IE integration test: cannot verify clean DB state ({exc!r})")
    finally:
        db_conn.execute("SET LOCAL statement_timeout = 0")
    if row is not None:
        pytest.skip(
            "Skipping NC IE integration test: production cf.filing already contains "
            "NC-IE-% rows whose record_hashes collide with this test's fixtures."
        )


_KNOWN_REPORT_DETAIL_URL = "https://cf.ncsbe.gov/CFOrgLkup/ReportDetail/?RID=229253&TP=EXP"
_KNOWN_REPORT_EXPORT_URL = (
    "https://cf.ncsbe.gov/CFOrgLkup/ExportDetailResults/?ReportID=229253&Type=EXP"
    "&Title=ADVANCE%20NORTH%20CAROLINA%20-%202026%20First%20Quarter"
)


def _seed_candidate(
    conn: psycopg.Connection,
    *,
    fec_candidate_id: str,
    name: str,
    office: str,
) -> UUID:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO cf.candidate (fec_candidate_id, name, office, state, district)
            VALUES (%s, %s, %s, 'NC', '01')
            RETURNING id
            """,
            (fec_candidate_id, name, office),
        )
        return cursor.fetchone()[0]


def _load_known_answer_filing(
    conn: psycopg.Connection,
    *,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[UUID, UUID]:
    from domains.campaign_finance.jurisdictions.states.NC.scraper import load_ie_document_index as ie_index_loader

    monkeypatch.setattr(
        ie_index_loader,
        "fetch_ie_document_result_report_section_urls",
        lambda _year: {},
    )

    data_source_id = ensure_nc_ie_document_index_data_source(conn)
    result = load_nc_ie_document_index(
        conn,
        _IE_DOCUMENT_INDEX_FIXTURE,
        data_source_id=data_source_id,
    )
    assert result.inserted == 1

    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT f.id AS filing_id, f.source_record_id
            FROM cf.filing f
            WHERE f.filing_fec_id LIKE 'NC-IE-%'
            LIMIT 1
            """
        )
        row = cursor.fetchone()

    assert row is not None
    set_nc_source_record_report_section_url(
        conn,
        source_record_id=row["source_record_id"],
        report_section_url=_KNOWN_REPORT_SECTION_URL,
    )
    return data_source_id, row["filing_id"]


def test_load_py_entrypoint_delegates_to_load_ie_transactions_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = object()
    captured: dict[str, object] = {}

    def _fake_load(
        conn: psycopg.Connection,
        *,
        data_source_id: UUID,
        limit: int | None = None,
    ) -> object:
        captured["conn"] = conn
        captured["data_source_id"] = data_source_id
        captured["limit"] = limit
        return sentinel

    monkeypatch.setattr(ie_tx_loader, "load_nc_ie_transactions", _fake_load)
    fake_conn = object()
    result = nc_load_module.load_nc_ie_transactions(
        fake_conn,  # type: ignore[arg-type]
        data_source_id=UUID("00000000-0000-0000-0000-000000000123"),
        limit=7,
    )

    assert result is sentinel
    assert captured == {
        "conn": fake_conn,
        "data_source_id": UUID("00000000-0000-0000-0000-000000000123"),
        "limit": 7,
    }


def test_support_oppose_normalization_accepts_case_insensitive_tokens() -> None:
    assert ie_tx_loader._normalize_support_oppose("support") == "S"
    assert ie_tx_loader._normalize_support_oppose("OPPOSE") == "O"


def test_load_inserts_expected_rows(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_candidate(db_conn, fec_candidate_id="S0NC00001", name="GAILLIARD JAMES D", office="S")
    _seed_candidate(db_conn, fec_candidate_id="H0NC00002", name="PIERCE RODNEY D", office="H")
    _seed_candidate(db_conn, fec_candidate_id="H0NC00003", name="SMITH RAYMOND", office="H")
    data_source_id, filing_id = _load_known_answer_filing(db_conn, monkeypatch=monkeypatch)

    monkeypatch.setattr(
        ie_tx_loader,
        "fetch_ie_report_detail_export_csv",
        lambda _url: (
            _KNOWN_ANSWER_DETAIL_FIXTURE.read_text(encoding="utf-8"),
            _KNOWN_REPORT_DETAIL_URL,
            _KNOWN_REPORT_EXPORT_URL,
        ),
    )

    result = load_nc_ie_transactions(db_conn, data_source_id=data_source_id)

    assert result.inserted == 3
    assert result.skipped == 0
    assert result.errors == 0

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT transaction_type, transaction_date, amount, memo_text, support_oppose, recipient_candidate_id
            FROM cf.transaction
            WHERE filing_id = %s
            ORDER BY amount
            """,
            (filing_id,),
        )
        rows = list(cursor.fetchall())

    assert [row["amount"] for row in rows] == [
        Decimal("3798.00"),
        Decimal("4560.00"),
        Decimal("6642.00"),
    ]
    assert {row["transaction_type"] for row in rows} == {"Independent Expenditure"}
    assert {row["transaction_date"] for row in rows} == {date(2026, 2, 12)}
    assert {row["memo_text"] for row in rows} == {"RADIO AND DIGITAL ADS"}
    assert {row["support_oppose"] for row in rows} == {"S"}
    assert all(row["recipient_candidate_id"] is not None for row in rows)


def test_load_is_idempotent(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_source_id, filing_id = _load_known_answer_filing(db_conn, monkeypatch=monkeypatch)
    monkeypatch.setattr(
        ie_tx_loader,
        "fetch_ie_report_detail_export_csv",
        lambda _url: (
            _KNOWN_ANSWER_DETAIL_FIXTURE.read_text(encoding="utf-8"),
            _KNOWN_REPORT_DETAIL_URL,
            _KNOWN_REPORT_EXPORT_URL,
        ),
    )

    first_result = load_nc_ie_transactions(db_conn, data_source_id=data_source_id)
    with db_conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM cf.transaction WHERE filing_id = %s", (filing_id,))
        count_between_runs = cursor.fetchone()[0]

    assert first_result.inserted == 3
    assert first_result.skipped == 0
    assert first_result.errors == 0
    assert count_between_runs == 3

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute("SELECT filing_fec_id FROM cf.filing WHERE id = %s", (filing_id,))
        filing_row = cursor.fetchone()
        cursor.execute(
            """
            SELECT transaction_identifier, amount, transaction_date, source_record_id
            FROM cf.transaction
            WHERE filing_id = %s
            ORDER BY transaction_identifier
            """,
            (filing_id,),
        )
        first_rows = list(cursor.fetchall())
        cursor.execute(
            """
            SELECT id, source_record_key, record_hash, raw_fields, pull_date
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = ANY(%s)
              AND superseded_by IS NULL
            ORDER BY source_record_key
            """,
            (data_source_id, [row["transaction_identifier"] for row in first_rows]),
        )
        first_source_record_snapshot = list(cursor.fetchall())
    assert filing_row is not None
    assert len(first_rows) == 3
    assert [row["transaction_identifier"] for row in first_rows] == [
        f"nc-ie-transaction:{filing_row['filing_fec_id']}:0",
        f"nc-ie-transaction:{filing_row['filing_fec_id']}:1",
        f"nc-ie-transaction:{filing_row['filing_fec_id']}:2",
    ]
    assert [row["amount"] for row in first_rows] == [Decimal("3798.0000"), Decimal("4560.0000"), Decimal("6642.0000")]
    assert {row["transaction_date"] for row in first_rows} == {date(2026, 2, 12)}
    assert [row["source_record_key"] for row in first_source_record_snapshot] == [
        record["transaction_identifier"] for record in first_rows
    ]

    second_result = load_nc_ie_transactions(db_conn, data_source_id=data_source_id)
    with db_conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM cf.transaction WHERE filing_id = %s", (filing_id,))
        count_after_second_run = cursor.fetchone()[0]

    assert second_result.inserted == 0
    assert second_result.skipped == 3
    assert second_result.errors == 0
    assert count_after_second_run == count_between_runs

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT transaction_identifier, amount, transaction_date, source_record_id
            FROM cf.transaction
            WHERE filing_id = %s
            ORDER BY transaction_identifier
            """,
            (filing_id,),
        )
        second_rows = list(cursor.fetchall())
        cursor.execute(
            """
            SELECT id, source_record_key, record_hash, raw_fields, pull_date
            FROM core.source_record
            WHERE data_source_id = %s
              AND source_record_key = ANY(%s)
              AND superseded_by IS NULL
            ORDER BY source_record_key
            """,
            (data_source_id, [row["transaction_identifier"] for row in second_rows]),
        )
        second_source_record_snapshot = list(cursor.fetchall())
    assert second_rows == first_rows
    assert second_source_record_snapshot == first_source_record_snapshot


def test_load_skips_missing_report_section_without_transactions(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_source_id, filing_id = _load_known_answer_filing(db_conn, monkeypatch=monkeypatch)
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            UPDATE core.source_record
            SET raw_fields = raw_fields - 'report_section_url'
            WHERE id = (
                SELECT source_record_id
                FROM cf.filing
                WHERE id = %s
            )
            """,
            (filing_id,),
        )

    result = load_nc_ie_transactions(db_conn, data_source_id=data_source_id)

    assert result.inserted == 0
    assert result.skipped == 1
    assert result.errors == 0

    with db_conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM cf.transaction WHERE filing_id = %s", (filing_id,))
        assert cursor.fetchone()[0] == 0


def test_load_known_answer_total(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_source_id, filing_id = _load_known_answer_filing(db_conn, monkeypatch=monkeypatch)
    monkeypatch.setattr(
        ie_tx_loader,
        "fetch_ie_report_detail_export_csv",
        lambda _url: (
            _KNOWN_ANSWER_DETAIL_FIXTURE.read_text(encoding="utf-8"),
            _KNOWN_REPORT_DETAIL_URL,
            _KNOWN_REPORT_EXPORT_URL,
        ),
    )

    result = load_nc_ie_transactions(db_conn, data_source_id=data_source_id)
    assert result.inserted == 3

    with db_conn.cursor() as cursor:
        cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM cf.transaction WHERE filing_id = %s", (filing_id,))
        assert cursor.fetchone()[0] == Decimal("15000.00")


def test_load_normalizes_support_oppose_case_at_persistence(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_source_id, filing_id = _load_known_answer_filing(db_conn, monkeypatch=monkeypatch)
    monkeypatch.setattr(
        ie_tx_loader,
        "fetch_ie_report_detail_export_csv",
        lambda _url: (
            _KNOWN_ANSWER_DETAIL_FIXTURE.read_text(encoding="utf-8"),
            _KNOWN_REPORT_DETAIL_URL,
            _KNOWN_REPORT_EXPORT_URL,
        ),
    )
    original_parse = ie_tx_loader.parse_ie_report_section_csv

    def _parse_with_lowercase_declaration(
        csv_text: str,
        *,
        spender_committee_name: str,
        source_filing_url: str,
        report_detail_url: str | None = None,
        report_export_url: str | None = None,
    ) -> list[NCIEReportRow]:
        rows = original_parse(
            csv_text,
            spender_committee_name=spender_committee_name,
            source_filing_url=source_filing_url,
            report_detail_url=report_detail_url,
            report_export_url=report_export_url,
        )
        return [
            row.model_copy(
                update={
                    "support_or_oppose_raw": row.support_or_oppose_raw.lower() if row.support_or_oppose_raw else None
                }
            )
            for row in rows
        ]

    monkeypatch.setattr(ie_tx_loader, "parse_ie_report_section_csv", _parse_with_lowercase_declaration)
    result = load_nc_ie_transactions(db_conn, data_source_id=data_source_id)

    assert result.inserted == 3
    assert result.skipped == 0
    assert result.errors == 0
    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT support_oppose
            FROM cf.transaction
            WHERE filing_id = %s
            ORDER BY transaction_identifier
            """,
            (filing_id,),
        )
        rows = list(cursor.fetchall())
    assert [row["support_oppose"] for row in rows] == ["S", "S", "S"]


def test_load_candidate_linkage_requires_exact_single_match(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_candidate(db_conn, fec_candidate_id="H0NC00002", name="PIERCE RODNEY D", office="H")
    _seed_candidate(db_conn, fec_candidate_id="H0NC99999", name="PIERCE RODNEY D", office="H")
    data_source_id, filing_id = _load_known_answer_filing(db_conn, monkeypatch=monkeypatch)

    unmatched_csv = """EXPENDITURES
Date,Name,Street 1,Street 2,City,State,Full Zip,Country Name,Outside US Postal Code,Profession,Employer Name,Purpose Type Code,Purpose,Candidate,Office Sought,Declaration,Amount,Expenditure Type Desc,Account Abbr,Form Of Payment Desc,Description,Amount1,Sum To Date
02/13/2026,INTERSECT MEDIA,443 REESE DRIVE,,WILLOW SPRING,NC,27592,United States,,,,,DIGITAL ADS,UNMATCHED CANDIDATE,Senate,Support,100.0000,Independent Expenditure,,Electronic Funds Transfer,,100.0000,100.0000
02/13/2026,INTERSECT MEDIA,443 REESE DRIVE,,WILLOW SPRING,NC,27592,United States,,,,,DIGITAL ADS,PIERCE RODNEY D,House,Support,200.0000,Independent Expenditure,,Electronic Funds Transfer,,200.0000,300.0000
"""
    monkeypatch.setattr(
        ie_tx_loader,
        "fetch_ie_report_detail_export_csv",
        lambda _url: (unmatched_csv, _KNOWN_REPORT_DETAIL_URL, _KNOWN_REPORT_EXPORT_URL),
    )
    result = load_nc_ie_transactions(db_conn, data_source_id=data_source_id)

    assert result.inserted == 2
    assert result.skipped == 0
    assert result.errors == 0

    with db_conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT t.recipient_candidate_id, sr.raw_fields ->> 'target_name' AS target_name
            FROM cf.transaction t
            JOIN core.source_record sr
              ON sr.id = t.source_record_id
            WHERE t.filing_id = %s
            ORDER BY t.amount
            """,
            (filing_id,),
        )
        rows = list(cursor.fetchall())

    assert [row["target_name"] for row in rows] == ["UNMATCHED CANDIDATE", "PIERCE RODNEY D"]
    assert all(row["recipient_candidate_id"] is None for row in rows)


# --- Stage 4: the work-item loop commits each completed batch mid-loop --------
#
# `_EXPECTED_DURABLE_BATCH_ROWS` is a frozen literal, deliberately NOT read from
# `ie_tx_loader._COMMIT_BATCH_ROWS`. The falsifiability probe for this specimen
# monkeypatches that module constant above the fixture size; an expectation derived from
# the live constant would move with the probe and the specimen could never go red.

_EXPECTED_DURABLE_BATCH_ROWS = 1_000
_NC_BULK_WORK_ITEM_COUNT = _EXPECTED_DURABLE_BATCH_ROWS + 1
# Every seeded work item shares one committee, and the loader writes no contributor
# person or address rows, so a completed load's whole entity footprint is that committee.
_NC_LOADED_COMMITTEE_ROWS = 1
_NC_BULK_REPORT_SECTION_URL = "https://cf.ncsbe.gov/CFOrgLkup/ReportSection/?RID=999999&SID=Batch"
_NC_BULK_REPORT_DETAIL_URL = "https://cf.ncsbe.gov/CFOrgLkup/ReportDetail/?RID=999999&TP=EXP"
_NC_BULK_REPORT_EXPORT_URL = "https://cf.ncsbe.gov/CFOrgLkup/ExportDetailResults/?ReportID=999999&Type=EXP"


def _single_row_detail_export_csv() -> str:
    """Return the known-answer detail export trimmed to its first expenditure row.

    One row per filing keeps 1,001 work items cheap while still driving the real parse,
    source-record, and transaction writes for every one of them.
    """
    banner, header, first_row = _KNOWN_ANSWER_DETAIL_FIXTURE.read_text(encoding="utf-8").splitlines()[:3]
    return "\n".join([banner, header, first_row]) + "\n"


class NCIEBulkFixture(NamedTuple):
    """One synthetic NC IE committee, its filing work items, and everything they write."""

    run_suffix: str
    committee_native_id: str
    committee_name: str
    filing_fec_ids: list[str]
    source_record_keys: list[str]

    @property
    def committee_fec_id(self) -> str:
        return generate_synthetic_committee_id("NC", self.committee_native_id)


def _build_nc_ie_bulk_fixture(*, work_item_count: int) -> NCIEBulkFixture:
    """Derive every identity the specimen will write, before touching the database.

    The filing source-record keys are this module's own; the transaction source-record
    keys are computed with the loader's own `_build_source_record_key`, so they cannot
    drift from the keys a real load writes and cleanup cannot miss them.
    """
    run_suffix = uuid4().hex[:12]
    filing_fec_ids = [f"NC-IE-{run_suffix}{index:04d}" for index in range(work_item_count)]
    detail_rows = parse_ie_report_section_csv(
        _single_row_detail_export_csv(),
        spender_committee_name=f"NC Bounded Commit Test Committee {run_suffix}",
        source_filing_url=_NC_BULK_REPORT_SECTION_URL,
        report_detail_url=_NC_BULK_REPORT_DETAIL_URL,
        report_export_url=_NC_BULK_REPORT_EXPORT_URL,
    )
    source_record_keys = [f"nc-ie-doc:{run_suffix}:{index}" for index in range(work_item_count)]
    source_record_keys += [
        ie_tx_loader._build_source_record_key(filing_fec_id=filing_fec_id, row=row)
        for filing_fec_id in filing_fec_ids
        for row in detail_rows
    ]
    return NCIEBulkFixture(
        run_suffix=run_suffix,
        committee_native_id=f"NCIE{run_suffix}",
        committee_name=f"NC Bounded Commit Test Committee {run_suffix}",
        filing_fec_ids=filing_fec_ids,
        source_record_keys=source_record_keys,
    )


def _commit_nc_ie_filing_work_items(fixture: NCIEBulkFixture, *, data_source_id: UUID) -> None:
    """Commit the committee and one IE filing per work item on an independent connection.

    Committed rather than left in the caller's transaction because the loader under test
    runs on its own connection and only sees what another connection made durable.
    """
    seed_conn = get_connection()
    try:
        committee_id = resolve_nc_committee_bridge(
            seed_conn,
            fixture.committee_native_id,
            committee_name=fixture.committee_name,
        )
        for index, filing_fec_id in enumerate(fixture.filing_fec_ids):
            raw_fields = {
                "source_record_key": fixture.source_record_keys[index],
                "report_section_url": _NC_BULK_REPORT_SECTION_URL,
            }
            source_record_id = try_insert_source_record(
                seed_conn,
                SourceRecord(
                    data_source_id=data_source_id,
                    source_record_key=fixture.source_record_keys[index],
                    raw_fields=raw_fields,
                    pull_date=utc_now(),
                    record_hash=compute_record_hash(raw_fields),
                ),
            )
            assert source_record_id is not None
            upsert_filing(
                seed_conn,
                Filing(
                    filing_fec_id=filing_fec_id,
                    committee_id=committee_id,
                    filing_name="Independent Expenditure Report",
                    amendment_indicator="N",
                    source_record_id=source_record_id,
                ),
            )
        seed_conn.commit()
    finally:
        seed_conn.close()


def _assert_nc_ie_fixture_owns_selected_batch(
    selected_filing_ids: list[str],
    fixture_filing_ids: list[str],
) -> None:
    """Fail explicitly when foreign DB rows would consume this specimen's batch."""
    assert set(selected_filing_ids) == set(fixture_filing_ids), (
        "fixture does not own the selected work-item batch: "
        f"selected={len(selected_filing_ids)}, fixture={len(fixture_filing_ids)}, "
        f"foreign={set(selected_filing_ids) - set(fixture_filing_ids)}"
    )


def test_nc_ie_bulk_fixture_selection_precondition_rejects_foreign_work_items() -> None:
    fixture = _build_nc_ie_bulk_fixture(work_item_count=2)
    selected_filing_ids = ["NC-IE-foreign", fixture.filing_fec_ids[0]]

    with pytest.raises(AssertionError, match="fixture does not own the selected work-item batch"):
        _assert_nc_ie_fixture_owns_selected_batch(selected_filing_ids, fixture.filing_fec_ids)


def test_load_nc_ie_transactions_commits_batch_mid_loop(
    db_conn: psycopg.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An interrupt on work item 1,001 leaves the first 1,000 work items' rows durable.

    Before Stage 4 the work-item loop committed once, at the end of the job, so this
    interruption discarded every transaction and an independent connection saw zero.
    """
    with ExitStack() as resources:
        fixture = _build_nc_ie_bulk_fixture(work_item_count=_NC_BULK_WORK_ITEM_COUNT)
        seed_bulk_fixture(
            resources,
            db_conn,
            fixture,
            expected_unique_source_record_keys=len(fixture.source_record_keys),
        )

        loader_conn = get_connection()
        resources.callback(loader_conn.close)
        data_source_id = resolve_nc_ie_data_source_before_managed_load(loader_conn)
        _commit_nc_ie_filing_work_items(fixture, data_source_id=data_source_id)

        selected_work_items = ie_tx_loader._select_ie_filing_work_items(
            loader_conn,
            limit=_NC_BULK_WORK_ITEM_COUNT,
        )
        _assert_nc_ie_fixture_owns_selected_batch(
            [work_item.filing_fec_id for work_item in selected_work_items],
            fixture.filing_fec_ids,
        )
        loader_conn.rollback()

        monkeypatch.setattr(
            ie_tx_loader,
            "fetch_ie_report_detail_export_csv",
            lambda _url: (
                _single_row_detail_export_csv(),
                _NC_BULK_REPORT_DETAIL_URL,
                _NC_BULK_REPORT_EXPORT_URL,
            ),
        )
        work_item_counts = install_write_interrupt(
            monkeypatch,
            ie_tx_loader,
            "_load_filing_transactions",
            raise_after_writes=_EXPECTED_DURABLE_BATCH_ROWS,
        )

        # The loader owns its own commits only if it starts IDLE, which is what the
        # data-source resolution above preserves.
        assert loader_conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
        with pytest.raises(BulkFixtureInterruption):
            load_nc_ie_transactions(loader_conn, data_source_id=data_source_id, limit=None)
        loader_conn.rollback()

        assert work_item_counts["writes"] == _NC_BULK_WORK_ITEM_COUNT
        source_record_count, transaction_count = bulk_fixture_row_counts(fixture)
        # Every seeded filing source record is durable; only the first full batch of
        # work items also wrote a transaction source record and a transaction.
        assert source_record_count == _NC_BULK_WORK_ITEM_COUNT + _EXPECTED_DURABLE_BATCH_ROWS
        assert transaction_count == _EXPECTED_DURABLE_BATCH_ROWS

        # The bridge organisation and committee behind those filings are part of the
        # fixture's footprint too; the stack's cleanup deletes them and re-reads this
        # same count, so a cleanup that stops covering them fails this specimen.
        assert bulk_fixture_entity_row_counts(fixture) == {
            "person": 0,
            "organization": _NC_LOADED_COMMITTEE_ROWS,
            "address": 0,
            "committee": _NC_LOADED_COMMITTEE_ROWS,
        }


def test_cli_ie_transactions_load_hands_the_loader_an_idle_connection() -> None:
    """`run_nc_refresh`'s ie-transactions arm must resolve the data source *before* the loader.

    Same ordering contract as the doc-index arm: a data-source lookup left open makes the
    loader read INTRANS and silently drop its 1,000-item commit boundary.
    """
    import argparse

    from domains.campaign_finance.jurisdictions.states.NC.scraper import cli

    observed_transaction_status: list[object] = []

    def _recording_loader(conn, *, data_source_id, limit):
        observed_transaction_status.append(conn.info.transaction_status)
        assert data_source_id is not None
        assert limit == 3
        return LoadResult(inserted=0, skipped=0, quarantined=0, superseded=0, errors=0, elapsed_seconds=0.0)

    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(cli, "load_nc_ie_transactions", _recording_loader)
        connection = get_connection()
        try:
            cli._load_input_data(
                connection,
                None,
                argparse.Namespace(data_type="ie-transactions", limit=3),
            )
        finally:
            connection.rollback()
            connection.close()

    assert observed_transaction_status == [psycopg.pq.TransactionStatus.IDLE]
