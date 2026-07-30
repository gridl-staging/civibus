from __future__ import annotations

from datetime import date
from decimal import Decimal
from itertools import count
from threading import Event, Thread

import pytest
from psycopg import Connection
from psycopg.rows import dict_row

from core.db import get_connection
from domains.campaign_finance.ingest.bulk_loader import _update_candidate_summary


pytestmark = pytest.mark.integration

_SUMMARY_COLUMNS = (
    "total_receipts",
    "total_disbursements",
    "cash_on_hand",
    "candidate_contrib",
    "candidate_loans",
    "candidate_loan_repay",
)

_FEC_ID_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_FEC_ID_NUMERIC_SUFFIX_SPACE = 100_000
_candidate_id_sequence = count()


def _unique_fec_candidate_id() -> str:
    sequence_number = next(_candidate_id_sequence)
    namespace_number, numeric_suffix = divmod(
        sequence_number,
        _FEC_ID_NUMERIC_SUFFIX_SPACE,
    )
    cycle_digit, state_number = divmod(namespace_number, len(_FEC_ID_ALPHABET) ** 2)
    if cycle_digit > 9:
        raise RuntimeError("Candidate test ID sequence exhausted")
    first_state_digit, second_state_digit = divmod(
        state_number,
        len(_FEC_ID_ALPHABET),
    )
    state_digits = _FEC_ID_ALPHABET[first_state_digit] + _FEC_ID_ALPHABET[second_state_digit]
    return f"H{cycle_digit}{state_digits}{numeric_suffix:05d}"


def test_candidate_id_sequence_does_not_repeat_at_modulus_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(globals(), "_candidate_id_sequence", count())

    candidate_ids = {_unique_fec_candidate_id() for _ in range(100_001)}

    assert len(candidate_ids) == 100_001


def _insert_candidate(conn: Connection) -> str:
    candidate_id = _unique_fec_candidate_id()
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO cf.candidate (fec_candidate_id, name, office)
            VALUES (%s, %s, %s)
            """,
            (candidate_id, f"Candidate {candidate_id}", "H"),
        )
    return candidate_id


def _candidate_summary_fields(
    *,
    fec_candidate_id: str,
    total_receipts: Decimal,
    summary_coverage_end_date: date | None,
) -> dict[str, object]:
    return {
        "fec_candidate_id": fec_candidate_id,
        "total_receipts": total_receipts,
        "total_disbursements": total_receipts + Decimal("10.00"),
        "cash_on_hand": total_receipts + Decimal("20.00"),
        "candidate_contrib": total_receipts + Decimal("30.00"),
        "candidate_loans": total_receipts + Decimal("40.00"),
        "candidate_loan_repay": total_receipts + Decimal("50.00"),
        "summary_coverage_end_date": summary_coverage_end_date,
    }


def _fetch_candidate_summary(conn: Connection, fec_candidate_id: str) -> dict[str, object]:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """
            SELECT total_receipts,
                   total_disbursements,
                   cash_on_hand,
                   candidate_contrib,
                   candidate_loans,
                   candidate_loan_repay,
                   summary_coverage_end_date
            FROM cf.candidate
            WHERE fec_candidate_id = %s
            """,
            (fec_candidate_id,),
        )
        row = cursor.fetchone()
    assert row is not None
    return dict(row)


def _assert_stored_summary_matches(
    conn: Connection,
    *,
    expected_fields: dict[str, object],
) -> None:
    stored_summary = _fetch_candidate_summary(conn, str(expected_fields["fec_candidate_id"]))
    for column_name in _SUMMARY_COLUMNS:
        assert stored_summary[column_name] == expected_fields[column_name]
    assert stored_summary["summary_coverage_end_date"] == expected_fields["summary_coverage_end_date"]


def test_newest_coverage_survives_older_summary(db_conn: Connection) -> None:
    fec_candidate_id = _insert_candidate(db_conn)
    newest_summary = _candidate_summary_fields(
        fec_candidate_id=fec_candidate_id,
        total_receipts=Decimal("1234.56"),
        summary_coverage_end_date=date(2024, 12, 31),
    )
    older_summary = _candidate_summary_fields(
        fec_candidate_id=fec_candidate_id,
        total_receipts=Decimal("9876.54"),
        summary_coverage_end_date=date(2022, 12, 31),
    )

    _update_candidate_summary(db_conn, mapped_fields=newest_summary)
    _update_candidate_summary(db_conn, mapped_fields=older_summary)

    _assert_stored_summary_matches(db_conn, expected_fields=newest_summary)


def test_later_month_survives_earlier_month_same_year(db_conn: Connection) -> None:
    fec_candidate_id = _insert_candidate(db_conn)
    december_summary = _candidate_summary_fields(
        fec_candidate_id=fec_candidate_id,
        total_receipts=Decimal("2500.00"),
        summary_coverage_end_date=date(2024, 12, 31),
    )
    june_summary = _candidate_summary_fields(
        fec_candidate_id=fec_candidate_id,
        total_receipts=Decimal("1500.00"),
        summary_coverage_end_date=date(2024, 6, 30),
    )

    _update_candidate_summary(db_conn, mapped_fields=december_summary)
    _update_candidate_summary(db_conn, mapped_fields=june_summary)

    _assert_stored_summary_matches(db_conn, expected_fields=december_summary)


def test_older_then_newer_accepts_newer_summary(db_conn: Connection) -> None:
    fec_candidate_id = _insert_candidate(db_conn)
    older_summary = _candidate_summary_fields(
        fec_candidate_id=fec_candidate_id,
        total_receipts=Decimal("100.00"),
        summary_coverage_end_date=date(2022, 12, 31),
    )
    newer_summary = _candidate_summary_fields(
        fec_candidate_id=fec_candidate_id,
        total_receipts=Decimal("200.00"),
        summary_coverage_end_date=date(2024, 12, 31),
    )

    _update_candidate_summary(db_conn, mapped_fields=older_summary)
    _update_candidate_summary(db_conn, mapped_fields=newer_summary)

    _assert_stored_summary_matches(db_conn, expected_fields=newer_summary)


def test_null_stored_coverage_accepts_dated_summary(db_conn: Connection) -> None:
    fec_candidate_id = _insert_candidate(db_conn)
    null_coverage_summary = _candidate_summary_fields(
        fec_candidate_id=fec_candidate_id,
        total_receipts=Decimal("300.00"),
        summary_coverage_end_date=None,
    )
    dated_summary = _candidate_summary_fields(
        fec_candidate_id=fec_candidate_id,
        total_receipts=Decimal("400.00"),
        summary_coverage_end_date=date(2024, 12, 31),
    )

    _update_candidate_summary(db_conn, mapped_fields=null_coverage_summary)
    _update_candidate_summary(db_conn, mapped_fields=dated_summary)

    _assert_stored_summary_matches(db_conn, expected_fields=dated_summary)


def test_equal_coverage_date_accepts_corrected_summary(db_conn: Connection) -> None:
    fec_candidate_id = _insert_candidate(db_conn)
    original_summary = _candidate_summary_fields(
        fec_candidate_id=fec_candidate_id,
        total_receipts=Decimal("500.00"),
        summary_coverage_end_date=date(2024, 12, 31),
    )
    corrected_summary = _candidate_summary_fields(
        fec_candidate_id=fec_candidate_id,
        total_receipts=Decimal("600.00"),
        summary_coverage_end_date=date(2024, 12, 31),
    )

    _update_candidate_summary(db_conn, mapped_fields=original_summary)
    _update_candidate_summary(db_conn, mapped_fields=corrected_summary)

    _assert_stored_summary_matches(db_conn, expected_fields=corrected_summary)


def test_dated_stored_coverage_rejects_null_incoming_summary(db_conn: Connection) -> None:
    fec_candidate_id = _insert_candidate(db_conn)
    dated_summary = _candidate_summary_fields(
        fec_candidate_id=fec_candidate_id,
        total_receipts=Decimal("700.00"),
        summary_coverage_end_date=date(2024, 12, 31),
    )
    null_coverage_summary = _candidate_summary_fields(
        fec_candidate_id=fec_candidate_id,
        total_receipts=Decimal("800.00"),
        summary_coverage_end_date=None,
    )

    _update_candidate_summary(db_conn, mapped_fields=dated_summary)
    _update_candidate_summary(db_conn, mapped_fields=null_coverage_summary)

    _assert_stored_summary_matches(db_conn, expected_fields=dated_summary)


def test_concurrent_older_summary_cannot_overwrite_newer_summary() -> None:
    setup_conn = get_connection()
    newer_conn = get_connection()
    older_update_started = Event()
    older_update_finished = Event()
    worker_error: list[BaseException] = []
    fec_candidate_id = _insert_candidate(setup_conn)
    setup_conn.commit()
    newer_summary = _candidate_summary_fields(
        fec_candidate_id=fec_candidate_id,
        total_receipts=Decimal("1000.00"),
        summary_coverage_end_date=date(2026, 12, 31),
    )
    older_summary = _candidate_summary_fields(
        fec_candidate_id=fec_candidate_id,
        total_receipts=Decimal("2000.00"),
        summary_coverage_end_date=date(2024, 12, 31),
    )

    def _apply_older_summary() -> None:
        older_conn = get_connection()
        try:
            older_conn.execute("BEGIN")
            older_update_started.set()
            _update_candidate_summary(older_conn, mapped_fields=older_summary)
            older_conn.commit()
        except BaseException as error:
            worker_error.append(error)
            older_conn.rollback()
        finally:
            older_conn.close()
            older_update_finished.set()

    try:
        newer_conn.execute("BEGIN")
        _update_candidate_summary(newer_conn, mapped_fields=newer_summary)
        worker = Thread(target=_apply_older_summary, daemon=True)
        worker.start()

        assert older_update_started.wait(timeout=1)
        assert not older_update_finished.wait(timeout=0.2)
        newer_conn.commit()
        worker.join(timeout=2)

        assert older_update_finished.is_set()
        assert worker_error == []
        _assert_stored_summary_matches(setup_conn, expected_fields=newer_summary)
    finally:
        newer_conn.rollback()
        setup_conn.execute("DELETE FROM cf.candidate WHERE fec_candidate_id = %s", (fec_candidate_id,))
        setup_conn.commit()
        newer_conn.close()
        setup_conn.close()


def test_unknown_candidate_id_raises_runtime_error(db_conn: Connection) -> None:
    mapped_fields = _candidate_summary_fields(
        fec_candidate_id=_unique_fec_candidate_id(),
        total_receipts=Decimal("900.00"),
        summary_coverage_end_date=date(2024, 12, 31),
    )

    with pytest.raises(RuntimeError, match="Expected one candidate summary update"):
        _update_candidate_summary(db_conn, mapped_fields=mapped_fields)
