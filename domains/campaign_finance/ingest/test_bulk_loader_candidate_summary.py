from __future__ import annotations

from datetime import date
from decimal import Decimal
from itertools import count
from threading import Event, Thread
from uuid import UUID

import pytest
from psycopg import Connection
from psycopg.rows import dict_row

from core.db import get_connection, insert_person
from core.types.python.models import Person
from domains.campaign_finance.ingest.bulk_loader import _update_candidate_summary
from domains.campaign_finance.ingest.candidate_summary_loader import update_candidate_person_link


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


def _get_test_connection() -> Connection:
    return get_connection()


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


def _insert_test_person(conn: Connection, canonical_name: str) -> UUID:
    person = Person(canonical_name=canonical_name)
    insert_person(conn, person)
    return person.id


def _fetch_candidate_person_id(conn: Connection, fec_candidate_id: str) -> UUID | None:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT person_id FROM cf.candidate WHERE fec_candidate_id = %s",
            (fec_candidate_id,),
        )
        row = cursor.fetchone()
    assert row is not None
    return row[0]


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
    setup_conn = _get_test_connection()
    newer_conn = _get_test_connection()
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
        older_conn = _get_test_connection()
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


def test_concurrent_stale_candidate_person_link_cannot_overwrite_spine_link() -> None:
    setup_conn = _get_test_connection()
    spine_conn = _get_test_connection()
    stale_update_started = Event()
    stale_update_finished = Event()
    worker_error: list[BaseException] = []
    fec_candidate_id = _insert_candidate(setup_conn)
    spine_person_id = _insert_test_person(setup_conn, "SPINE OFFICEHOLDER")
    stale_person_id = _insert_test_person(setup_conn, "FEC STALE CANDIDATE")
    setup_conn.commit()

    def _apply_stale_link() -> None:
        stale_conn = _get_test_connection()
        try:
            stale_conn.execute("BEGIN")
            stale_update_started.set()
            update_candidate_person_link(
                stale_conn,
                fec_candidate_id=fec_candidate_id,
                person_id=stale_person_id,
            )
            stale_conn.commit()
        except BaseException as error:
            worker_error.append(error)
            stale_conn.rollback()
        finally:
            stale_conn.close()
            stale_update_finished.set()

    try:
        spine_conn.execute("BEGIN")
        update_candidate_person_link(
            spine_conn,
            fec_candidate_id=fec_candidate_id,
            person_id=spine_person_id,
        )
        worker = Thread(target=_apply_stale_link, daemon=True)
        worker.start()

        assert stale_update_started.wait(timeout=1)
        assert not stale_update_finished.wait(timeout=0.2)
        spine_conn.commit()
        worker.join(timeout=2)

        assert stale_update_finished.is_set()
        assert worker_error == []
        assert _fetch_candidate_person_id(setup_conn, fec_candidate_id) == spine_person_id
    finally:
        spine_conn.rollback()
        setup_conn.execute("DELETE FROM cf.candidate WHERE fec_candidate_id = %s", (fec_candidate_id,))
        setup_conn.execute(
            "DELETE FROM core.person WHERE id = ANY(%s)",
            ([spine_person_id, stale_person_id],),
        )
        setup_conn.commit()
        spine_conn.close()
        setup_conn.close()


# The pre-fix loader repointed the link with an unconditional assignment inside
# `_upsert_candidate`'s `ON CONFLICT ... DO UPDATE`. Production ran a candidate-master
# load on 2026-07-28 with the congressional spine skipped by the refresh cadence gate,
# so that assignment stood with no repair owner behind it and 527 of 540 officeholders
# lost their money link. This pins the counterfactual: the old shape must still be shown
# to clobber, or the guard below is proving nothing.
_UNGUARDED_LEGACY_PERSON_LINK_SQL = """
    UPDATE cf.candidate
    SET person_id = %s
    WHERE fec_candidate_id = %s
"""


def test_masters_rerun_without_spine_repair_cannot_steal_an_established_link(
    db_conn: Connection,
) -> None:
    """A masters-only refresh must not move a spine-owned link to an FEC shadow person.

    Red half: the pre-fix unconditional assignment steals the link, which is the
    production defect. Green half: the guarded owner leaves it on the spine person.
    """
    fec_candidate_id = _insert_candidate(db_conn)
    spine_person_id = _insert_test_person(db_conn, "SPINE OFFICEHOLDER")
    shadow_person_id = _insert_test_person(db_conn, "FEC SHADOW CANDIDATE")

    update_candidate_person_link(
        db_conn,
        fec_candidate_id=fec_candidate_id,
        person_id=spine_person_id,
    )
    assert _fetch_candidate_person_id(db_conn, fec_candidate_id) == spine_person_id

    # Red: reproduce the deployed pre-fix behaviour and prove it breaks the link.
    db_conn.execute(_UNGUARDED_LEGACY_PERSON_LINK_SQL, (shadow_person_id, fec_candidate_id))
    assert _fetch_candidate_person_id(db_conn, fec_candidate_id) == shadow_person_id, (
        "counterfactual failed to reproduce the production defect, so the green assertion below would pass vacuously"
    )

    # Restore the spine-owned link, then re-run the same steal through the guard.
    db_conn.execute(_UNGUARDED_LEGACY_PERSON_LINK_SQL, (spine_person_id, fec_candidate_id))
    update_candidate_person_link(
        db_conn,
        fec_candidate_id=fec_candidate_id,
        person_id=shadow_person_id,
    )

    # Green: the established spine link survives a masters rerun with no spine job after it.
    assert _fetch_candidate_person_id(db_conn, fec_candidate_id) == spine_person_id


def test_masters_rerun_still_fills_an_empty_link(db_conn: Connection) -> None:
    """The guard must block a steal without blocking first-time linkage."""
    fec_candidate_id = _insert_candidate(db_conn)
    person_id = _insert_test_person(db_conn, "FIRST LINK CANDIDATE")

    assert _fetch_candidate_person_id(db_conn, fec_candidate_id) is None

    update_candidate_person_link(
        db_conn,
        fec_candidate_id=fec_candidate_id,
        person_id=person_id,
    )

    assert _fetch_candidate_person_id(db_conn, fec_candidate_id) == person_id


def test_unknown_candidate_person_link_raises_runtime_error(db_conn: Connection) -> None:
    person_id = _insert_test_person(db_conn, "UNMATCHED CANDIDATE")

    with pytest.raises(RuntimeError, match="Expected one candidate person link update"):
        update_candidate_person_link(
            db_conn,
            fec_candidate_id=_unique_fec_candidate_id(),
            person_id=person_id,
        )


def test_unknown_candidate_id_raises_runtime_error(db_conn: Connection) -> None:
    mapped_fields = _candidate_summary_fields(
        fec_candidate_id=_unique_fec_candidate_id(),
        total_receipts=Decimal("900.00"),
        summary_coverage_end_date=date(2024, 12, 31),
    )

    with pytest.raises(RuntimeError, match="Expected one candidate summary update"):
        _update_candidate_summary(db_conn, mapped_fields=mapped_fields)
