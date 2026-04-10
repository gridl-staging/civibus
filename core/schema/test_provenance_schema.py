"""Integration test coverage for provenance schema entity-type constraints."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.schema_sql_runner import run_psql_command, run_psql_file


REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_ENTITIES_SQL = REPO_ROOT / "core" / "schema" / "entities.sql"
CORE_PROVENANCE_SQL = REPO_ROOT / "core" / "schema" / "provenance.sql"
TEST_DATABASE = os.getenv("PROVENANCE_SCHEMA_TEST_DATABASE", "civibus")

ALLOWED_ENTITY_TYPES = (
    "person",
    "organization",
    "address",
    "office",
    "electoral_division",
    "contest",
    "candidacy",
    "officeholding",
    "contact_point",
)


def _run_psql_command(database: str, sql: str, *, expect_tuples: bool = True) -> list[str] | str:
    return run_psql_command(
        database,
        sql,
        command_env_var="PROVENANCE_SCHEMA_PSQL_CMD",
        repo_root=REPO_ROOT,
        expect_tuples=expect_tuples,
    )


def _run_psql_file(database: str, sql_file: Path) -> None:
    run_psql_file(database, sql_file, command_env_var="PROVENANCE_SCHEMA_PSQL_CMD", repo_root=REPO_ROOT)


def _skip_if_no_database_access() -> None:
    try:
        _run_psql_command(TEST_DATABASE, "SELECT 1;")
    except Exception as exc:
        pytest.skip(f"Unable to connect to test database '{TEST_DATABASE}': {exc}")


@pytest.fixture(scope="session", autouse=True)
def _prepared_schema() -> None:
    _skip_if_no_database_access()
    _run_psql_command(TEST_DATABASE, "DROP SCHEMA IF EXISTS core CASCADE;")
    _run_psql_file(TEST_DATABASE, CORE_ENTITIES_SQL)
    _run_psql_file(TEST_DATABASE, CORE_PROVENANCE_SQL)


def _insert_data_source_and_source_record_sql() -> str:
    return """
        WITH inserted_source AS (
            INSERT INTO core.data_source (domain, jurisdiction, name, source_url)
            VALUES ('campaign_finance', 'states/nc', 'provenance-test-' || md5(random()::text), 'https://example.com/source')
            RETURNING id
        ), inserted_record AS (
            INSERT INTO core.source_record (data_source_id, source_record_key, raw_fields, pull_date)
            SELECT id, 'record-' || md5(random()::text), '{}'::jsonb, NOW()
            FROM inserted_source
            RETURNING id
        )
    """


@pytest.mark.parametrize("entity_type", ALLOWED_ENTITY_TYPES)
def test_entity_source_accepts_all_allowed_entity_types(entity_type: str) -> None:
    rows = _run_psql_command(
        TEST_DATABASE,
        f"""
        {_insert_data_source_and_source_record_sql()}
        INSERT INTO core.entity_source (entity_type, entity_id, source_record_id, extraction_role)
        SELECT '{entity_type}', uuid_generate_v4(), id, 'test_role'
        FROM inserted_record
        RETURNING entity_type;
        """,
    )
    assert rows == [entity_type]


@pytest.mark.parametrize("entity_type", ALLOWED_ENTITY_TYPES)
def test_field_provenance_accepts_all_allowed_entity_types(entity_type: str) -> None:
    rows = _run_psql_command(
        TEST_DATABASE,
        f"""
        {_insert_data_source_and_source_record_sql()}
        INSERT INTO core.field_provenance (
            entity_type,
            entity_id,
            field_name,
            field_value,
            source_record_id,
            first_seen,
            last_seen,
            is_current
        )
        SELECT '{entity_type}', uuid_generate_v4(), 'status', 'active', id, NOW(), NOW(), TRUE
        FROM inserted_record
        RETURNING entity_type;
        """,
    )
    assert rows == [entity_type]


@pytest.mark.parametrize(
    ("table_name", "insert_sql"),
    (
        (
            "entity_source",
            """
            INSERT INTO core.entity_source (entity_type, entity_id, source_record_id, extraction_role)
            SELECT 'invalid_type', uuid_generate_v4(), id, 'bad_type'
            FROM inserted_record;
            """,
        ),
        (
            "field_provenance",
            """
            INSERT INTO core.field_provenance (
                entity_type,
                entity_id,
                field_name,
                field_value,
                source_record_id,
                first_seen,
                last_seen,
                is_current
            )
            SELECT 'invalid_type', uuid_generate_v4(), 'status', 'invalid', id, NOW(), NOW(), TRUE
            FROM inserted_record;
            """,
        ),
    ),
)
def test_invalid_entity_type_rejected_by_check_constraint(table_name: str, insert_sql: str) -> None:
    assert table_name in {"entity_source", "field_provenance"}
    with pytest.raises(RuntimeError, match="violates check constraint"):
        _run_psql_command(
            TEST_DATABASE,
            f"""
            {_insert_data_source_and_source_record_sql()}
            {insert_sql}
            """,
        )


def test_field_provenance_current_row_uniqueness_constraint_rejects_two_current_rows() -> None:
    with pytest.raises(RuntimeError, match="duplicate key value violates unique constraint"):
        _run_psql_command(
            TEST_DATABASE,
            f"""
            {_insert_data_source_and_source_record_sql()}
            , inserted_entity AS (
                SELECT uuid_generate_v4() AS id FROM inserted_record
            )
            INSERT INTO core.field_provenance (
                entity_type,
                entity_id,
                field_name,
                field_value,
                source_record_id,
                first_seen,
                last_seen,
                is_current
            )
            SELECT
                'contest',
                inserted_entity.id,
                'status',
                value_payload.field_value,
                inserted_record.id,
                NOW(),
                NOW(),
                TRUE
            FROM inserted_record
            CROSS JOIN inserted_entity
            CROSS JOIN (VALUES ('scheduled'), ('certified')) AS value_payload(field_value);
            """,
        )
