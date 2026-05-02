"""Integration contract tests for civic.contest_result schema and constraints."""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

import psycopg
import pytest

from domains.civics.types import ContestResult


pytestmark = pytest.mark.integration


def _seed_office_and_contest(conn: psycopg.Connection) -> UUID:
    office_id = uuid4()
    contest_id = uuid4()
    conn.execute(
        """
        INSERT INTO civic.office (id, name, office_level, state)
        VALUES (%s, %s, 'state', 'NC')
        """,
        (office_id, f"contest_result_test_office_{uuid4().hex[:10]}"),
    )
    conn.execute(
        """
        INSERT INTO civic.contest (id, name, election_type, office_id, number_of_seats)
        VALUES (%s, %s, 'general', %s, 2)
        """,
        (contest_id, f"Contest Result Test Contest {uuid4().hex[:10]}", office_id),
    )
    return contest_id


def _row_mapping_from_cursor(cursor: psycopg.Cursor[tuple[object, ...]], row: tuple[object, ...]) -> dict[str, object]:
    assert cursor.description is not None
    return {column.name: value for column, value in zip(cursor.description, row, strict=True)}


def test_contest_result_allows_multi_seat_winners_enforces_natural_key_and_model_contract(
    db_conn: psycopg.Connection,
) -> None:
    contest_id = _seed_office_and_contest(db_conn)
    election_date = date(2024, 11, 5)

    db_conn.execute(
        """
        INSERT INTO civic.contest_result (
            id,
            contest_id,
            candidate_name_on_ballot,
            election_date,
            is_winner
        )
        VALUES (%s, %s, %s, %s, %s), (%s, %s, %s, %s, %s)
        """,
        (
            uuid4(),
            contest_id,
            "ALEX ALPHA",
            election_date,
            True,
            uuid4(),
            contest_id,
            "BLAIR BETA",
            election_date,
            True,
        ),
    )

    winner_count = db_conn.execute(
        """
        SELECT COUNT(*)::int
        FROM civic.contest_result
        WHERE contest_id = %s AND election_date = %s AND is_winner = TRUE
        """,
        (contest_id, election_date),
    ).fetchone()
    assert winner_count is not None
    assert winner_count[0] == 2

    db_conn.execute("SAVEPOINT contest_result_unique_violation")
    try:
        with pytest.raises(psycopg.errors.UniqueViolation):
            db_conn.execute(
                """
                INSERT INTO civic.contest_result (
                    id,
                    contest_id,
                    candidate_name_on_ballot,
                    election_date,
                    is_winner
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    uuid4(),
                    contest_id,
                    "ALEX ALPHA",
                    election_date,
                    False,
                ),
            )
    finally:
        db_conn.execute("ROLLBACK TO SAVEPOINT contest_result_unique_violation")
        db_conn.execute("RELEASE SAVEPOINT contest_result_unique_violation")

    with db_conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT *
            FROM civic.contest_result
            WHERE contest_id = %s AND candidate_name_on_ballot = %s AND election_date = %s
            """,
            (contest_id, "ALEX ALPHA", election_date),
        )
        row = cursor.fetchone()
        assert row is not None
        result = ContestResult.model_validate(_row_mapping_from_cursor(cursor, row))

    assert result.contest_id == contest_id
    assert result.candidate_name_on_ballot == "ALEX ALPHA"
    assert result.election_date == election_date
    assert result.is_winner is True
    assert result.source_record_id is None
    assert isinstance(result.id, UUID)
