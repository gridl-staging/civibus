"""Integration tests for Schedule B loader (operating expenditures).

Tests verify the end-to-end ingest path: pipe-delimited parsing → committee
linking → filing/transaction upsert via try_row_without_savepoint. Each test
seeds its own committee fixture and cleans up afterward.

These tests are written before the loader implementation (TDD red phase).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from core.db import get_connection
from domains.campaign_finance.ingest.bulk_loader import ensure_fec_bulk_data_source
from domains.campaign_finance.ingest.schedule_b_loader import load_schedule_b
from domains.campaign_finance.ingest.schedule_b_parser import SCHEDULE_B_COLUMNS
from test_support.schedule_e import seed_schedule_e_committee

pytestmark = [pytest.mark.integration, pytest.mark.e2e]


def _unique_committee_fec_id() -> str:
    return f"C{uuid4().int % 100_000_000:08d}"


def _unique_file_num() -> str:
    return str(uuid4().int % 10_000_000)


def _unique_tran_id() -> str:
    return f"SB.{uuid4().hex[:10]}"


def _unique_sub_id() -> str:
    return str(uuid4().int % 10**19)


def _write_oppexp_file(tmp_path: Path, rows: list[dict[str, str]]) -> Path:
    """Write pipe-delimited oppexp rows (headerless, 25 fields)."""
    file_path = tmp_path / f"oppexp_{uuid4().hex[:8]}.txt"
    lines = []
    for row in rows:
        values = [row.get(col, "") or "" for col in SCHEDULE_B_COLUMNS]
        lines.append("|".join(values))
    file_path.write_text("\n".join(lines) + "\n", encoding="latin-1")
    return file_path


def _make_row(
    *,
    cmte_id: str,
    amndt_ind: str = "N",
    rpt_yr: str = "2024",
    rpt_tp: str = "Q3",
    image_num: str = "202410001234567890",
    line_num: str = "21B",
    form_tp_cd: str = "F3X",
    sched_tp_cd: str = "SB",
    name: str = "ACME CONSULTING LLC",
    city: str = "WASHINGTON",
    state: str = "DC",
    zip_code: str = "20001",
    transaction_dt: str = "09152024",
    transaction_amt: str = "5000.00",
    transaction_pgi: str = "G2024",
    purpose: str = "CONSULTING FEES",
    category: str = "006",
    category_desc: str = "OTHER",
    memo_cd: str = "",
    memo_text: str = "",
    entity_tp: str = "ORG",
    sub_id: str = "",
    file_num: str = "",
    tran_id: str = "",
    back_ref_tran_id: str = "",
) -> dict[str, str]:
    if not file_num:
        file_num = _unique_file_num()
    if not tran_id:
        tran_id = _unique_tran_id()
    if not sub_id:
        sub_id = _unique_sub_id()
    return {
        "CMTE_ID": cmte_id,
        "AMNDT_IND": amndt_ind,
        "RPT_YR": rpt_yr,
        "RPT_TP": rpt_tp,
        "IMAGE_NUM": image_num,
        "LINE_NUM": line_num,
        "FORM_TP_CD": form_tp_cd,
        "SCHED_TP_CD": sched_tp_cd,
        "NAME": name,
        "CITY": city,
        "STATE": state,
        "ZIP_CODE": zip_code,
        "TRANSACTION_DT": transaction_dt,
        "TRANSACTION_AMT": transaction_amt,
        "TRANSACTION_PGI": transaction_pgi,
        "PURPOSE": purpose,
        "CATEGORY": category,
        "CATEGORY_DESC": category_desc,
        "MEMO_CD": memo_cd,
        "MEMO_TEXT": memo_text,
        "ENTITY_TP": entity_tp,
        "SUB_ID": sub_id,
        "FILE_NUM": file_num,
        "TRAN_ID": tran_id,
        "BACK_REF_TRAN_ID": back_ref_tran_id,
    }


def _cleanup_schedule_b_test_data(
    conn: psycopg.Connection,
    committee_fec_ids: list[str],
    file_nums: list[str],
) -> None:
    with conn.cursor() as cur:
        if file_nums:
            cur.execute(
                """
                DELETE FROM cf.transaction
                WHERE filing_id IN (
                    SELECT id FROM cf.filing WHERE filing_fec_id = ANY(%s)
                )
                """,
                (file_nums,),
            )
            cur.execute(
                "DELETE FROM cf.filing WHERE filing_fec_id = ANY(%s)",
                (file_nums,),
            )
        if committee_fec_ids:
            cur.execute(
                """
                DELETE FROM core.source_record
                WHERE source_record_key LIKE 'schedule_b:%%'
                  AND source_record_key LIKE ANY(
                      SELECT '%%' || fec_committee_id || '%%'
                      FROM cf.committee WHERE fec_committee_id = ANY(%s)
                  )
                """,
                (committee_fec_ids,),
            )
            cur.execute(
                "DELETE FROM cf.committee WHERE fec_committee_id = ANY(%s)",
                (committee_fec_ids,),
            )
            cur.execute(
                "DELETE FROM core.organization WHERE identifiers ->> 'fec_committee_id' = ANY(%s)",
                (committee_fec_ids,),
            )
    conn.commit()


def _select_filing_by_fec_id(conn: psycopg.Connection, filing_fec_id: str) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM cf.filing WHERE filing_fec_id = %s LIMIT 1",
            (filing_fec_id,),
        )
        return cur.fetchone()


def _select_transactions_by_filing_fec_id(
    conn: psycopg.Connection,
    filing_fec_id: str,
) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT t.*
            FROM cf.transaction t
            JOIN cf.filing f ON f.id = t.filing_id
            WHERE f.filing_fec_id = %s
            ORDER BY t.transaction_identifier
            """,
            (filing_fec_id,),
        )
        return cur.fetchall()


@pytest.fixture
def db_conn() -> Iterator[psycopg.Connection]:
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def data_source_id(db_conn: psycopg.Connection) -> UUID:
    ds_id = ensure_fec_bulk_data_source(db_conn)
    db_conn.commit()
    return ds_id


class TestScheduleBFilingPersistence:
    def test_basic_ingest_creates_filing(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        committee = seed_schedule_e_committee(db_conn, _unique_committee_fec_id(), "OppExp PAC")
        file_num = _unique_file_num()
        rows = [_make_row(cmte_id=committee.fec_committee_id, file_num=file_num)]
        oppexp_path = _write_oppexp_file(tmp_path, rows)

        try:
            result = load_schedule_b(
                db_conn,
                oppexp_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            assert result.inserted == 1
            assert result.errors == 0

            filing = _select_filing_by_fec_id(db_conn, file_num)
            assert filing is not None
            assert filing["committee_id"] == committee.id
            assert filing["report_type"] == "schedule_b"
            assert filing["source_record_id"] is not None
        finally:
            _cleanup_schedule_b_test_data(
                db_conn,
                [committee.fec_committee_id],
                [file_num],
            )

    def test_missing_committee_counts_as_error(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        nonexistent_cmte_id = _unique_committee_fec_id()
        file_num = _unique_file_num()
        rows = [_make_row(cmte_id=nonexistent_cmte_id, file_num=file_num)]
        oppexp_path = _write_oppexp_file(tmp_path, rows)

        result = load_schedule_b(
            db_conn,
            oppexp_path,
            cycle=2024,
            data_source_id=data_source_id,
            batch_size=100,
        )
        assert result.inserted == 0
        assert result.errors == 1

        filing = _select_filing_by_fec_id(db_conn, file_num)
        assert filing is None


class TestScheduleBTransactionPersistence:
    def test_transaction_type_is_expenditure_itemized(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        committee = seed_schedule_e_committee(db_conn, _unique_committee_fec_id(), "TxnType PAC")
        file_num = _unique_file_num()
        rows = [_make_row(cmte_id=committee.fec_committee_id, file_num=file_num)]
        oppexp_path = _write_oppexp_file(tmp_path, rows)

        try:
            load_schedule_b(
                db_conn,
                oppexp_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            txns = _select_transactions_by_filing_fec_id(db_conn, file_num)
            assert len(txns) == 1
            assert txns[0]["transaction_type"] == "Expenditure (Itemized)"
        finally:
            _cleanup_schedule_b_test_data(
                db_conn,
                [committee.fec_committee_id],
                [file_num],
            )

    def test_payee_stored_as_contributor_name_raw(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        committee = seed_schedule_e_committee(db_conn, _unique_committee_fec_id(), "Payee PAC")
        file_num = _unique_file_num()
        rows = [
            _make_row(
                cmte_id=committee.fec_committee_id,
                file_num=file_num,
                name="MEGACORP SERVICES INC",
            ),
        ]
        oppexp_path = _write_oppexp_file(tmp_path, rows)

        try:
            load_schedule_b(
                db_conn,
                oppexp_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            txns = _select_transactions_by_filing_fec_id(db_conn, file_num)
            assert len(txns) == 1
            assert txns[0]["contributor_name_raw"] == "MEGACORP SERVICES INC"
        finally:
            _cleanup_schedule_b_test_data(
                db_conn,
                [committee.fec_committee_id],
                [file_num],
            )

    def test_contributor_entity_ids_are_null(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        committee = seed_schedule_e_committee(db_conn, _unique_committee_fec_id(), "NoEntity PAC")
        file_num = _unique_file_num()
        rows = [_make_row(cmte_id=committee.fec_committee_id, file_num=file_num)]
        oppexp_path = _write_oppexp_file(tmp_path, rows)

        try:
            load_schedule_b(
                db_conn,
                oppexp_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            txns = _select_transactions_by_filing_fec_id(db_conn, file_num)
            assert len(txns) == 1
            assert txns[0]["contributor_person_id"] is None
            assert txns[0]["contributor_organization_id"] is None
        finally:
            _cleanup_schedule_b_test_data(
                db_conn,
                [committee.fec_committee_id],
                [file_num],
            )

    def test_amount_and_date_populated(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        committee = seed_schedule_e_committee(db_conn, _unique_committee_fec_id(), "Amount PAC")
        file_num = _unique_file_num()
        rows = [
            _make_row(
                cmte_id=committee.fec_committee_id,
                file_num=file_num,
                transaction_amt="12345.67",
                transaction_dt="03152025",
            ),
        ]
        oppexp_path = _write_oppexp_file(tmp_path, rows)

        try:
            load_schedule_b(
                db_conn,
                oppexp_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            txns = _select_transactions_by_filing_fec_id(db_conn, file_num)
            assert len(txns) == 1
            assert txns[0]["amount"] == Decimal("12345.67")
            assert txns[0]["transaction_date"] == date(2025, 3, 15)
        finally:
            _cleanup_schedule_b_test_data(
                db_conn,
                [committee.fec_committee_id],
                [file_num],
            )


class TestScheduleBMemoFields:
    def test_memo_code_and_text_preserved(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        committee = seed_schedule_e_committee(db_conn, _unique_committee_fec_id(), "Memo PAC")
        file_num = _unique_file_num()
        rows = [
            _make_row(
                cmte_id=committee.fec_committee_id,
                file_num=file_num,
                memo_cd="X",
                memo_text="SEE ATTACHED SCHEDULE",
            ),
        ]
        oppexp_path = _write_oppexp_file(tmp_path, rows)

        try:
            load_schedule_b(
                db_conn,
                oppexp_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            txns = _select_transactions_by_filing_fec_id(db_conn, file_num)
            assert len(txns) == 1
            assert txns[0]["memo_code"] == "X"
            assert txns[0]["memo_text"] == "SEE ATTACHED SCHEDULE"
        finally:
            _cleanup_schedule_b_test_data(
                db_conn,
                [committee.fec_committee_id],
                [file_num],
            )

    def test_empty_memo_fields_are_null(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        committee = seed_schedule_e_committee(db_conn, _unique_committee_fec_id(), "NoMemo PAC")
        file_num = _unique_file_num()
        rows = [
            _make_row(
                cmte_id=committee.fec_committee_id,
                file_num=file_num,
                memo_cd="",
                memo_text="",
            ),
        ]
        oppexp_path = _write_oppexp_file(tmp_path, rows)

        try:
            load_schedule_b(
                db_conn,
                oppexp_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            txns = _select_transactions_by_filing_fec_id(db_conn, file_num)
            assert len(txns) == 1
            assert txns[0]["memo_code"] is None
            assert txns[0]["memo_text"] is None
        finally:
            _cleanup_schedule_b_test_data(
                db_conn,
                [committee.fec_committee_id],
                [file_num],
            )


class TestScheduleBBackRef:
    def test_back_ref_transaction_id_preserved(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        committee = seed_schedule_e_committee(db_conn, _unique_committee_fec_id(), "BackRef PAC")
        file_num = _unique_file_num()
        rows = [
            _make_row(
                cmte_id=committee.fec_committee_id,
                file_num=file_num,
                back_ref_tran_id="SA11AI.5678",
            ),
        ]
        oppexp_path = _write_oppexp_file(tmp_path, rows)

        try:
            load_schedule_b(
                db_conn,
                oppexp_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            txns = _select_transactions_by_filing_fec_id(db_conn, file_num)
            assert len(txns) == 1
            assert txns[0]["back_ref_transaction_id"] == "SA11AI.5678"
        finally:
            _cleanup_schedule_b_test_data(
                db_conn,
                [committee.fec_committee_id],
                [file_num],
            )

    def test_empty_back_ref_is_null(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        committee = seed_schedule_e_committee(db_conn, _unique_committee_fec_id(), "NoBackRef PAC")
        file_num = _unique_file_num()
        rows = [
            _make_row(
                cmte_id=committee.fec_committee_id,
                file_num=file_num,
                back_ref_tran_id="",
            ),
        ]
        oppexp_path = _write_oppexp_file(tmp_path, rows)

        try:
            load_schedule_b(
                db_conn,
                oppexp_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            txns = _select_transactions_by_filing_fec_id(db_conn, file_num)
            assert len(txns) == 1
            assert txns[0]["back_ref_transaction_id"] is None
        finally:
            _cleanup_schedule_b_test_data(
                db_conn,
                [committee.fec_committee_id],
                [file_num],
            )


class TestScheduleBIdempotency:
    def test_idempotent_reingest(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        committee = seed_schedule_e_committee(db_conn, _unique_committee_fec_id(), "Idempotent PAC")
        file_num = _unique_file_num()
        tran_id = _unique_tran_id()
        rows = [
            _make_row(
                cmte_id=committee.fec_committee_id,
                file_num=file_num,
                tran_id=tran_id,
            ),
        ]
        oppexp_path = _write_oppexp_file(tmp_path, rows)

        try:
            result_1 = load_schedule_b(
                db_conn,
                oppexp_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            assert result_1.inserted == 1

            result_2 = load_schedule_b(
                db_conn,
                oppexp_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            assert result_2.inserted == 0
            assert result_2.skipped >= 1

            txns = _select_transactions_by_filing_fec_id(db_conn, file_num)
            assert len(txns) == 1
        finally:
            _cleanup_schedule_b_test_data(
                db_conn,
                [committee.fec_committee_id],
                [file_num],
            )


class TestScheduleBAmendment:
    def test_amendment_indicator_normalized(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        committee = seed_schedule_e_committee(db_conn, _unique_committee_fec_id(), "Amndt PAC")
        file_num = _unique_file_num()
        rows = [
            _make_row(
                cmte_id=committee.fec_committee_id,
                file_num=file_num,
                amndt_ind="A1",
            ),
        ]
        oppexp_path = _write_oppexp_file(tmp_path, rows)

        try:
            load_schedule_b(
                db_conn,
                oppexp_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            filing = _select_filing_by_fec_id(db_conn, file_num)
            assert filing is not None
            assert filing["amendment_indicator"] == "A"

            txns = _select_transactions_by_filing_fec_id(db_conn, file_num)
            assert len(txns) == 1
            assert txns[0]["amendment_indicator"] == "A"
        finally:
            _cleanup_schedule_b_test_data(
                db_conn,
                [committee.fec_committee_id],
                [file_num],
            )

    def test_empty_amendment_indicator_defaults_to_n(
        self,
        db_conn: psycopg.Connection,
        data_source_id: UUID,
        tmp_path: Path,
    ) -> None:
        committee = seed_schedule_e_committee(db_conn, _unique_committee_fec_id(), "EmptyAmndt PAC")
        file_num = _unique_file_num()
        rows = [
            _make_row(
                cmte_id=committee.fec_committee_id,
                file_num=file_num,
                amndt_ind="",
            ),
        ]
        oppexp_path = _write_oppexp_file(tmp_path, rows)

        try:
            load_schedule_b(
                db_conn,
                oppexp_path,
                cycle=2024,
                data_source_id=data_source_id,
                batch_size=100,
            )
            filing = _select_filing_by_fec_id(db_conn, file_num)
            assert filing is not None
            assert filing["amendment_indicator"] == "N"
        finally:
            _cleanup_schedule_b_test_data(
                db_conn,
                [committee.fec_committee_id],
                [file_num],
            )
