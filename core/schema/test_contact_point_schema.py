"""Integration test coverage for core.contact_point SQL schema DDL."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from conftest import _skip_or_fail_for_postgres_unavailable
from core.schema_sql_runner import (
    run_psql_command,
    run_psql_file,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_ENTITIES_SQL = REPO_ROOT / "core" / "schema" / "entities.sql"
CORE_PROVENANCE_SQL = REPO_ROOT / "core" / "schema" / "provenance.sql"
TEST_DATABASE = os.getenv("CONTACT_POINT_SCHEMA_TEST_DATABASE", "civibus")

CONTACT_POINT_COLUMNS = [
    "id",
    "type",
    "value_raw",
    "value_normalized",
    "role",
    "owner_type",
    "owner_id",
    "source_record_id",
    "last_verified_at",
    "is_preferred",
    "valid_period",
    "created_at",
    "updated_at",
]


def _run_psql_command(database: str, sql: str, *, expect_tuples: bool = True) -> list[str] | str:
    return run_psql_command(
        database,
        sql,
        command_env_var="CONTACT_POINT_SCHEMA_PSQL_CMD",
        repo_root=REPO_ROOT,
        expect_tuples=expect_tuples,
    )


def _run_psql_file(database: str, sql_file: Path) -> None:
    run_psql_file(database, sql_file, command_env_var="CONTACT_POINT_SCHEMA_PSQL_CMD", repo_root=REPO_ROOT)


def _query_returns_expected_first_row(database: str, query: str, expected: str) -> bool:
    rows = _run_psql_command(database, query)
    return bool(rows) and rows[0] == expected


def _query_returns_truthy_first_row(database: str, query: str) -> bool:
    rows = _run_psql_command(database, query)
    value = rows[0] if rows else None
    return bool(value and value.strip().lower() in {"t", "true", "1"})


def _skip_if_no_database_access() -> None:
    try:
        _run_psql_command(TEST_DATABASE, "SELECT 1;")
    except Exception as exc:
        _skip_or_fail_for_postgres_unavailable(f"Unable to connect to test database '{TEST_DATABASE}': {exc}")


@pytest.fixture(scope="session", autouse=True)
def _prepared_schema() -> None:
    _skip_if_no_database_access()
    _run_psql_command(TEST_DATABASE, "DROP SCHEMA IF EXISTS core CASCADE;")
    _run_psql_file(TEST_DATABASE, CORE_ENTITIES_SQL)
    _run_psql_file(TEST_DATABASE, CORE_PROVENANCE_SQL)


def test_contact_point_table_exists() -> None:
    assert _query_returns_expected_first_row(
        TEST_DATABASE,
        "SELECT COUNT(1)::int FROM information_schema.tables "
        "WHERE table_schema = 'core' AND table_name = 'contact_point';",
        "1",
    )


def test_contact_point_has_expected_columns() -> None:
    rows = _run_psql_command(
        TEST_DATABASE,
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'core' AND table_name = 'contact_point' "
        "ORDER BY ordinal_position;",
    )
    assert rows == CONTACT_POINT_COLUMNS


def test_contact_point_owner_type_check_constraint() -> None:
    """owner_type must be constrained to the ADR-specified set."""
    assert _query_returns_truthy_first_row(
        TEST_DATABASE,
        """
        SELECT EXISTS (
            SELECT 1 FROM pg_constraint c
            JOIN pg_class r ON c.conrelid = r.oid
            WHERE r.relnamespace = 'core'::regnamespace
              AND r.relname = 'contact_point'
              AND c.contype = 'c'
              AND pg_get_constraintdef(c.oid) LIKE '%owner_type%'
        )::text;
        """,
    )


def test_contact_point_natural_key_unique_index() -> None:
    """Named unique index enforces natural-key uniqueness."""
    assert _query_returns_expected_first_row(
        TEST_DATABASE,
        "SELECT COUNT(1)::int FROM pg_indexes "
        "WHERE schemaname = 'core' AND tablename = 'contact_point' "
        "AND indexname = 'uq_contact_point_natural_key';",
        "1",
    )


def test_contact_point_updated_at_trigger() -> None:
    """BEFORE UPDATE trigger using core.set_updated_at() must exist."""
    assert _query_returns_truthy_first_row(
        TEST_DATABASE,
        """
        SELECT EXISTS (
            SELECT 1 FROM pg_trigger t
            JOIN pg_class c ON c.oid = t.tgrelid
            JOIN pg_proc p ON p.oid = t.tgfoid
            WHERE c.relnamespace = 'core'::regnamespace
              AND c.relname = 'contact_point'
              AND p.proname = 'set_updated_at'
              AND NOT t.tgisinternal
              AND lower(pg_get_triggerdef(t.oid)) LIKE '%before update%'
              AND pg_get_triggerdef(t.oid) LIKE '%core.set_updated_at%'
        )::text;
        """,
    )


def test_contact_point_source_record_fk() -> None:
    """source_record_id must have a FK to core.source_record."""
    assert _query_returns_truthy_first_row(
        TEST_DATABASE,
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.constraint_schema = kcu.constraint_schema
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
                AND tc.constraint_schema = ccu.constraint_schema
            WHERE tc.table_schema = 'core'
              AND tc.table_name = 'contact_point'
              AND tc.constraint_type = 'FOREIGN KEY'
              AND kcu.column_name = 'source_record_id'
              AND ccu.table_name = 'source_record'
              AND ccu.column_name = 'id'
        )::text;
        """,
    )


def test_contact_point_valid_period_is_daterange() -> None:
    """valid_period column must be of type daterange."""
    rows = _run_psql_command(
        TEST_DATABASE,
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_schema = 'core' AND table_name = 'contact_point' "
        "AND column_name = 'valid_period';",
    )
    assert rows == ["daterange"]
