"""Integration test coverage for property-domain SQL schema DDL."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.schema_sql_runner import (
    build_base_psql_command,
    run_psql_command,
    run_psql_file,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_FILE = REPO_ROOT / "domains" / "property" / "schema" / "tables.sql"
CORE_ENTITIES_SQL = REPO_ROOT / "core" / "schema" / "entities.sql"
CORE_JURISDICTION_SQL = REPO_ROOT / "core" / "schema" / "jurisdiction.sql"
CORE_PROVENANCE_SQL = REPO_ROOT / "core" / "schema" / "provenance.sql"
CF_SCHEMA_SQL = REPO_ROOT / "domains" / "campaign_finance" / "schema" / "tables.sql"
TEST_DATABASE = os.getenv("PROP_SCHEMA_TEST_DATABASE", "civibus")

PROP_TABLES = ["assessment", "ownership", "parcel"]
PROP_INDEXES = [
    "idx_assessment_parcel",
    "idx_ownership_owner_address",
    "idx_ownership_owner_organization",
    "idx_ownership_owner_person",
    "idx_ownership_parcel",
    "idx_ownership_valid_period",
    "idx_parcel_jurisdiction",
    "idx_parcel_source_record",
    "uq_assessment_parcel_tax_year",
    "uq_parcel_pin",
    "uq_parcel_reid",
]
EXPECTED_FOREIGN_KEYS = [
    ("parcel", "jurisdiction_id", "jurisdiction", "id"),
    ("parcel", "source_record_id", "source_record", "id"),
    ("assessment", "parcel_id", "parcel", "id"),
    ("assessment", "source_record_id", "source_record", "id"),
    ("ownership", "parcel_id", "parcel", "id"),
    ("ownership", "owner_person_id", "person", "id"),
    ("ownership", "owner_organization_id", "organization", "id"),
    ("ownership", "owner_address_id", "address", "id"),
    ("ownership", "source_record_id", "source_record", "id"),
]


def _is_truthy(value: str | None) -> bool:
    return bool(value and value.strip().lower() in {"t", "true", "1"})


def _build_base_psql_command(database: str) -> list[str]:
    return build_base_psql_command(database, command_env_var="PROP_SCHEMA_PSQL_CMD", repo_root=REPO_ROOT)


def _run_psql_command(database: str, sql: str, *, expect_tuples: bool = True) -> list[str] | str:
    return run_psql_command(
        database,
        sql,
        command_env_var="PROP_SCHEMA_PSQL_CMD",
        repo_root=REPO_ROOT,
        expect_tuples=expect_tuples,
    )


def _run_psql_file(database: str, sql_file: Path) -> None:
    run_psql_file(database, sql_file, command_env_var="PROP_SCHEMA_PSQL_CMD", repo_root=REPO_ROOT)


def _query_returns_expected_first_row(database: str, query: str, expected: str) -> bool:
    rows = _run_psql_command(database, query)
    return bool(rows) and rows[0] == expected


def _query_returns_truthy_first_row(database: str, query: str) -> bool:
    rows = _run_psql_command(database, query)
    return _is_truthy(rows[0] if rows else None)


def _index_exists(database: str, index_name: str) -> bool:
    return _query_returns_expected_first_row(
        database,
        f"SELECT COUNT(1)::int FROM pg_indexes WHERE schemaname = 'prop' AND indexname = '{index_name}';",
        "1",
    )


def _fk_exists(database: str, table_name: str, column_name: str, referenced_table: str, referenced_column: str) -> bool:
    return _query_returns_truthy_first_row(
        database,
        f"""
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.constraint_schema = kcu.constraint_schema
                JOIN information_schema.constraint_column_usage ccu
                    ON tc.constraint_name = ccu.constraint_name
                    AND tc.constraint_schema = ccu.constraint_schema
                WHERE tc.table_schema = 'prop'
                  AND tc.table_name = '{table_name}'
                  AND tc.constraint_type = 'FOREIGN KEY'
                  AND kcu.column_name = '{column_name}'
                  AND ccu.table_schema = CASE
                        WHEN '{referenced_table}' IN ('parcel', 'assessment', 'ownership') THEN 'prop'
                        ELSE 'core'
                      END
                  AND ccu.table_name = '{referenced_table}'
                  AND ccu.column_name = '{referenced_column}'
            )::text;
        """,
    )


def _has_updated_at_trigger(database: str, table_name: str) -> bool:
    return _query_returns_truthy_first_row(
        database,
        (
            "SELECT EXISTS ("
            " SELECT 1"
            " FROM pg_trigger t"
            " JOIN pg_class c ON c.oid = t.tgrelid"
            " JOIN pg_proc p ON p.oid = t.tgfoid"
            " WHERE c.relnamespace = 'prop'::regnamespace"
            "   AND c.relname = '" + table_name + "'"
            "   AND p.proname = 'set_updated_at'"
            "   AND NOT t.tgisinternal"
            "   AND lower(pg_get_triggerdef(t.oid)) LIKE '%before update%'"
            "   AND pg_get_triggerdef(t.oid) LIKE '%core.set_updated_at%'"
            ")::text;"
        ),
    )


def _skip_if_no_database_access() -> None:
    try:
        _run_psql_command(TEST_DATABASE, "SELECT 1;")
    except Exception as exc:
        pytest.skip(f"Unable to connect to test database '{TEST_DATABASE}': {exc}")


# Same protection as domains/campaign_finance/tests/test_tables_schema.py:
# refuse to drop schemas against production-named databases. Without this
# guard, running pytest against the live Hetzner DB would silently nuke
# production prop/cf/core data.
_PROTECTED_DATABASE_NAMES = frozenset({"civibus", "civibus_prod", "civibus_staging"})


@pytest.fixture(scope="session", autouse=True)
def _prepared_schema() -> None:
    _skip_if_no_database_access()
    if TEST_DATABASE in _PROTECTED_DATABASE_NAMES:
        pytest.skip(
            f"Refusing to DROP SCHEMA prop/cf/core CASCADE against protected "
            f"production database {TEST_DATABASE!r}. Set the test-DB env var "
            f"to a dedicated test database to run schema-prep tests."
        )

    _run_psql_command(TEST_DATABASE, "DROP SCHEMA IF EXISTS prop CASCADE;")
    _run_psql_command(TEST_DATABASE, "DROP SCHEMA IF EXISTS cf CASCADE;")
    _run_psql_command(TEST_DATABASE, "DROP SCHEMA IF EXISTS core CASCADE;")

    _run_psql_file(TEST_DATABASE, CORE_ENTITIES_SQL)
    _run_psql_file(TEST_DATABASE, CORE_JURISDICTION_SQL)
    _run_psql_file(TEST_DATABASE, CORE_PROVENANCE_SQL)
    _run_psql_file(TEST_DATABASE, CF_SCHEMA_SQL)
    _run_psql_file(TEST_DATABASE, SCHEMA_FILE)


def test_property_schema_file_exists_for_stage3() -> None:
    assert SCHEMA_FILE.exists(), "domains/property/schema/tables.sql must exist for Stage 3"


def test_property_schema_creates_only_stage3_owned_tables() -> None:
    rows = _run_psql_command(
        TEST_DATABASE,
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'prop' ORDER BY table_name;",
    )
    assert rows == PROP_TABLES


def test_property_schema_indexes_foreign_keys_and_constraints() -> None:
    for index_name in PROP_INDEXES:
        assert _index_exists(TEST_DATABASE, index_name), f"Missing index: {index_name}"

    for table, column, referenced_table, referenced_column in EXPECTED_FOREIGN_KEYS:
        assert _fk_exists(TEST_DATABASE, table, column, referenced_table, referenced_column), (
            f"Missing FK prop.{table}.{column} -> {referenced_table}.{referenced_column}"
        )

    ownership_period_type = _run_psql_command(
        TEST_DATABASE,
        """
            SELECT data_type
            FROM information_schema.columns
            WHERE table_schema = 'prop' AND table_name = 'ownership' AND column_name = 'valid_period';
        """,
    )
    assert ownership_period_type == ["daterange"]

    ownership_precision_type = _run_psql_command(
        TEST_DATABASE,
        """
            SELECT udt_schema || '.' || udt_name
            FROM information_schema.columns
            WHERE table_schema = 'prop' AND table_name = 'ownership' AND column_name = 'date_precision';
        """,
    )
    assert ownership_precision_type == ["core.date_precision"]


def test_property_schema_updated_at_triggers() -> None:
    for table in PROP_TABLES:
        assert _has_updated_at_trigger(TEST_DATABASE, table), (
            f"Missing BEFORE UPDATE core.set_updated_at() trigger on prop.{table}"
        )
