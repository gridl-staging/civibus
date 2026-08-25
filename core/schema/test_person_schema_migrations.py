"""Contract tests for core.person bio-field migration artifacts."""

from __future__ import annotations

from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[2]
PERSON_BIO_FIELDS_MIGRATION_FILE = REPO_ROOT / "core" / "schema" / "migrations" / "2026_04_30_person_bio_fields.sql"
ENTITY_RESOLUTION_SCHEMA_FILE = REPO_ROOT / "core" / "schema" / "entity_resolution.sql"
PERSON_ABSORPTION_MIGRATION_FILE = REPO_ROOT / "core" / "schema" / "migrations" / "2026_08_24_person_absorption.sql"
PERSON_ABSORPTION_COLUMNS = [
    "absorbed_person_id",
    "canonical_person_id",
    "cluster_id",
    "merged_by",
    "absorbed_at",
    "absorbed_payload",
]


def test_person_bio_fields_migration_contract() -> None:
    assert PERSON_BIO_FIELDS_MIGRATION_FILE.exists(), (
        "Missing in-place migration for core.person bio fields: core/schema/migrations/2026_04_30_person_bio_fields.sql"
    )
    migration_sql = PERSON_BIO_FIELDS_MIGRATION_FILE.read_text(encoding="utf-8").lower()
    compact_sql = " ".join(migration_sql.split())

    assert "alter table core.person" in migration_sql
    assert "add column if not exists bio_text text" in migration_sql
    assert "add column if not exists bio_source_url text" in migration_sql
    assert "add column if not exists bio_license text" in migration_sql
    assert "add column if not exists bio_pulled_at timestamptz" in migration_sql
    assert (
        "check ( bio_license is null or bio_license in ('public_domain', 'licensed', 'restricted', 'unknown') )"
        in compact_sql
    )


def test_person_bio_fields_migration_all_add_columns_are_idempotent() -> None:
    migration_sql = PERSON_BIO_FIELDS_MIGRATION_FILE.read_text(encoding="utf-8")
    add_column_clauses = re.findall(r"ADD\s+COLUMN\b", migration_sql, re.IGNORECASE)
    assert len(add_column_clauses) > 0, "Migration must contain at least one ADD COLUMN"
    add_column_if_not_exists = re.findall(r"ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\b", migration_sql, re.IGNORECASE)
    assert len(add_column_clauses) == len(add_column_if_not_exists), (
        f"All ADD COLUMN clauses must use IF NOT EXISTS; found {len(add_column_clauses)} "
        f"ADD COLUMN but only {len(add_column_if_not_exists)} with IF NOT EXISTS"
    )


def _table_body(sql: str, table_name: str) -> str:
    match = re.search(
        rf"CREATE TABLE(?: IF NOT EXISTS)? {re.escape(table_name)} \((.*?)\n\);",
        sql,
        re.IGNORECASE | re.DOTALL,
    )
    assert match is not None, f"{table_name} table DDL not found"
    return match.group(1)


def _column_names(table_body: str) -> list[str]:
    names: list[str] = []
    for raw_line in table_body.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("--") or line.upper().startswith("CONSTRAINT"):
            continue
        names.append(line.split()[0].strip(","))
    return names


def _column_definition(table_body: str, column_name: str) -> str:
    for raw_line in table_body.splitlines():
        line = raw_line.strip().rstrip(",")
        if line.startswith(f"{column_name} "):
            return line
    raise AssertionError(f"{column_name} column DDL not found")


def _assert_person_absorption_contract(sql: str) -> None:
    table_body = _table_body(sql, "core.person_absorption")
    assert _column_names(table_body) == PERSON_ABSORPTION_COLUMNS
    assert re.search(r"\babsorbed_payload\s+JSONB\s+NOT\s+NULL\b", table_body, re.IGNORECASE)
    assert re.search(r"\babsorbed_person_id\s+UUID\s+PRIMARY\s+KEY\b", table_body, re.IGNORECASE)
    assert "REFERENCES" not in _column_definition(table_body, "absorbed_person_id").upper()
    assert re.search(
        r"\bcanonical_person_id\s+UUID\s+NOT\s+NULL\s+REFERENCES\s+core\.person\s*\(id\)", table_body, re.IGNORECASE
    )
    assert re.search(
        r"\bcluster_id\s+UUID\s+NOT\s+NULL\s+REFERENCES\s+core\.entity_cluster\s*\(id\)", table_body, re.IGNORECASE
    )


def test_person_absorption_reset_schema_contract() -> None:
    schema_sql = ENTITY_RESOLUTION_SCHEMA_FILE.read_text(encoding="utf-8")
    _assert_person_absorption_contract(schema_sql)
    assert "irreversible `person` tombstone" in schema_sql
    assert "pre-delete `core.person` row from `core/schema/entities.sql`" in schema_sql


def test_person_absorption_migration_contract() -> None:
    assert PERSON_ABSORPTION_MIGRATION_FILE.exists(), (
        "Missing migration: core/schema/migrations/2026_08_24_person_absorption.sql"
    )
    migration_sql = PERSON_ABSORPTION_MIGRATION_FILE.read_text(encoding="utf-8")
    _assert_person_absorption_contract(migration_sql)
    assert "CREATE TABLE IF NOT EXISTS core.person_absorption" in migration_sql
    assert "CONCURRENTLY" not in migration_sql.upper()
    for index_name in (
        "idx_person_absorption_canonical_person",
        "idx_person_absorption_cluster",
        "idx_person_absorption_absorbed_at",
    ):
        assert f"CREATE INDEX IF NOT EXISTS {index_name}" in migration_sql
