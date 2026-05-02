from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import psycopg
import pytest
from psycopg.rows import dict_row

from domains.campaign_finance.jurisdictions.states.NC.scraper import load as nc_load_module
from domains.campaign_finance.jurisdictions.states.NC.scraper import load_ie_transactions as ie_tx_loader
from domains.campaign_finance.jurisdictions.states.NC.scraper.load import (
    ensure_nc_ie_document_index_data_source,
    load_nc_ie_document_index,
    load_nc_ie_transactions,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.load_support import (
    set_nc_source_record_report_section_url,
)
from domains.campaign_finance.jurisdictions.states.NC.scraper.parse_ie_report_section import NCIEReportRow

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
        row = db_conn.execute(
            "SELECT 1 FROM cf.filing WHERE filing_fec_id LIKE 'NC-IE-%' LIMIT 1"
        ).fetchone()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(
            f"Skipping NC IE integration test: cannot verify clean DB state ({exc!r})"
        )
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
                    "support_or_oppose_raw": row.support_or_oppose_raw.lower()
                    if row.support_or_oppose_raw
                    else None
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
