"""Contract tests for core.person bio-field migration artifacts."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PERSON_BIO_FIELDS_MIGRATION_FILE = (
    REPO_ROOT / "core" / "schema" / "migrations" / "2026_04_30_person_bio_fields.sql"
)


def test_person_bio_fields_migration_contract() -> None:
    assert PERSON_BIO_FIELDS_MIGRATION_FILE.exists(), (
        "Missing in-place migration for core.person bio fields:"
        " core/schema/migrations/2026_04_30_person_bio_fields.sql"
    )
    migration_sql = PERSON_BIO_FIELDS_MIGRATION_FILE.read_text(encoding="utf-8").lower()
    compact_sql = " ".join(migration_sql.split())

    assert "alter table core.person" in migration_sql
    assert "add column if not exists bio_text text" in migration_sql
    assert "add column if not exists bio_source_url text" in migration_sql
    assert "add column if not exists bio_license text" in migration_sql
    assert "add column if not exists bio_pulled_at timestamptz" in migration_sql
    assert "check ( bio_license is null or bio_license in ('public_domain', 'licensed', 'restricted', 'unknown') )" in compact_sql
