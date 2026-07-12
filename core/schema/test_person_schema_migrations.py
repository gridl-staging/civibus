"""Contract tests for core.person bio-field migration artifacts."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PERSON_BIO_FIELDS_MIGRATION_FILE = REPO_ROOT / "core" / "schema" / "migrations" / "2026_04_30_person_bio_fields.sql"


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
    import re

    migration_sql = PERSON_BIO_FIELDS_MIGRATION_FILE.read_text(encoding="utf-8")
    add_column_clauses = re.findall(r"ADD\s+COLUMN\b", migration_sql, re.IGNORECASE)
    assert len(add_column_clauses) > 0, "Migration must contain at least one ADD COLUMN"
    add_column_if_not_exists = re.findall(r"ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\b", migration_sql, re.IGNORECASE)
    assert len(add_column_clauses) == len(add_column_if_not_exists), (
        f"All ADD COLUMN clauses must use IF NOT EXISTS; found {len(add_column_clauses)} "
        f"ADD COLUMN but only {len(add_column_if_not_exists)} with IF NOT EXISTS"
    )
