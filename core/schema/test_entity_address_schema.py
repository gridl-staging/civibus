from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.range import DateRange


pytestmark = pytest.mark.integration

_LEGACY_VALID_FROM_COLUMN = "valid_from"
_LEGACY_VALID_TO_COLUMN = "valid_to"
_LEGACY_CURRENT_INDEX_PREDICATE = "valid_to IS NULL"


def _insert_address(db_conn: psycopg.Connection) -> UUID:
    address_id = uuid4()
    db_conn.execute(
        """
        INSERT INTO core.address (id, raw_address, city, state, zip5)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (address_id, f"{address_id} MAIN ST, DURHAM, NC 27701", "DURHAM", "NC", "27701"),
    )
    return address_id


def _insert_entity_address_with_period(
    db_conn: psycopg.Connection,
    shared_key: tuple[str, UUID, UUID, str],
    start: date,
    end: date | None,
) -> None:
    db_conn.execute(
        """
        INSERT INTO core.entity_address (
            entity_type,
            entity_id,
            address_id,
            address_role,
            valid_period
        )
        VALUES (%s, %s, %s, %s, daterange(%s, %s, '[)'))
        """,
        (*shared_key, start, end),
    )


def _count_entity_address_rows(
    db_conn: psycopg.Connection,
    shared_key: tuple[str, UUID, UUID, str],
) -> int:
    return db_conn.execute(
        """
        SELECT COUNT(*)
        FROM core.entity_address
        WHERE entity_type = %s
          AND entity_id = %s
          AND address_id = %s
          AND address_role = %s
        """,
        shared_key,
    ).fetchone()[0]


def test_entity_address_has_valid_period_column(db_conn: psycopg.Connection) -> None:
    address_id = _insert_address(db_conn)
    entity_id = uuid4()

    valid_period = db_conn.execute(
        """
        INSERT INTO core.entity_address (
            entity_type,
            entity_id,
            address_id,
            address_role,
            valid_period
        )
        VALUES (%s, %s, %s, %s, daterange(%s, NULL, '[)'))
        RETURNING valid_period
        """,
        ("person", entity_id, address_id, "mailing", date(2020, 1, 1)),
    ).fetchone()[0]

    column_names = {
        row[0]
        for row in db_conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'core'
              AND table_name = 'entity_address'
            """,
        ).fetchall()
    }

    assert valid_period == DateRange(date(2020, 1, 1), None, "[)")
    assert "valid_period" in column_names
    assert _LEGACY_VALID_FROM_COLUMN not in column_names
    assert _LEGACY_VALID_TO_COLUMN not in column_names


def test_entity_address_has_date_precision_column(db_conn: psycopg.Connection) -> None:
    address_id = _insert_address(db_conn)

    explicit_precision = db_conn.execute(
        """
        INSERT INTO core.entity_address (
            entity_type,
            entity_id,
            address_id,
            address_role,
            date_precision
        )
        VALUES (%s, %s, %s, %s, %s)
        RETURNING date_precision
        """,
        ("person", uuid4(), address_id, "mailing", "month"),
    ).fetchone()[0]

    default_precision = db_conn.execute(
        """
        INSERT INTO core.entity_address (
            entity_type,
            entity_id,
            address_id,
            address_role
        )
        VALUES (%s, %s, %s, %s)
        RETURNING date_precision
        """,
        ("person", uuid4(), address_id, "mailing"),
    ).fetchone()[0]

    assert explicit_precision == "month"
    assert default_precision == "day"


def test_entity_address_rejects_null_address_role(db_conn: psycopg.Connection) -> None:
    address_id = _insert_address(db_conn)

    with pytest.raises(psycopg.errors.NotNullViolation):
        db_conn.execute(
            """
            INSERT INTO core.entity_address (
                entity_type,
                entity_id,
                address_id,
                address_role
            )
            VALUES (%s, %s, %s, %s)
            """,
            ("person", uuid4(), address_id, None),
        )


def test_entity_address_rejects_overlapping_periods(db_conn: psycopg.Connection) -> None:
    address_id = _insert_address(db_conn)
    entity_id = uuid4()
    shared_key = ("person", entity_id, address_id, "mailing")

    _insert_entity_address_with_period(db_conn, shared_key, date(2020, 1, 1), date(2021, 1, 1))

    with pytest.raises((psycopg.errors.ExclusionViolation, psycopg.errors.UniqueViolation)):
        _insert_entity_address_with_period(db_conn, shared_key, date(2020, 6, 1), None)


def test_entity_address_allows_non_overlapping_periods(db_conn: psycopg.Connection) -> None:
    address_id = _insert_address(db_conn)
    entity_id = uuid4()
    shared_key = ("person", entity_id, address_id, "mailing")

    _insert_entity_address_with_period(db_conn, shared_key, date(2020, 1, 1), date(2021, 1, 1))
    _insert_entity_address_with_period(db_conn, shared_key, date(2021, 1, 1), None)

    assert _count_entity_address_rows(db_conn, shared_key) == 2


def test_entity_address_current_index_uses_upper_inf(db_conn: psycopg.Connection) -> None:
    _insert_address(db_conn)

    index_definition = db_conn.execute(
        """
        SELECT indexdef
        FROM pg_indexes
        WHERE schemaname = 'core'
          AND tablename = 'entity_address'
          AND indexname = 'idx_entity_address_current'
        """,
    ).fetchone()[0]

    assert "upper_inf(valid_period)" in index_definition
    assert _LEGACY_CURRENT_INDEX_PREDICATE not in index_definition
