"""Contracts for the donor-search rollup migration."""

from __future__ import annotations

import re
from pathlib import Path

import psycopg


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = REPO_ROOT / "core" / "schema" / "migrations" / "2026_08_01_donor_search_rollup.sql"
IDENTITY_VARIANT_MIGRATION_PATH = (
    REPO_ROOT / "core" / "schema" / "migrations" / "2026_08_03_donor_search_rollup_identity_variants.sql"
)


def test_donor_search_rollup_relation_exists_after_db_reset(db_conn: psycopg.Connection) -> None:
    with db_conn.cursor() as cursor:
        cursor.execute("SELECT to_regclass('cf.donor_search_rollup')")
        relation = cursor.fetchone()

    assert relation == ("cf.donor_search_rollup",)


def test_donor_search_rollup_owns_non_null_representative_transaction_id(
    db_conn: psycopg.Connection,
) -> None:
    column = db_conn.execute(
        """
        SELECT data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'cf'
          AND table_name = 'donor_search_rollup'
          AND column_name = 'representative_transaction_id'
        """
    ).fetchone()

    assert column == ("uuid", "NO")


def test_donor_search_rollup_identity_variant_relation_exists_after_db_reset(
    db_conn: psycopg.Connection,
) -> None:
    columns = db_conn.execute(
        """
        SELECT column_name, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'cf'
          AND table_name = 'donor_search_rollup_identity_variant'
        ORDER BY ordinal_position
        """
    ).fetchall()
    indexes = db_conn.execute(
        """
        SELECT indexname
        FROM pg_indexes
        WHERE schemaname = 'cf'
          AND tablename = 'donor_search_rollup_identity_variant'
        ORDER BY indexname
        """
    ).fetchall()

    assert columns == [
        ("donor_key", "NO"),
        ("contributor_name_raw", "NO"),
        ("contributor_employer", "NO"),
        ("contributor_occupation", "NO"),
        ("contributor_city", "NO"),
        ("contributor_state", "NO"),
        ("contributor_zip", "NO"),
    ]
    assert indexes == [
        ("donor_search_rollup_identity_variant_unique",),
        ("idx_donor_search_rollup_identity_variant_identity_tuple",),
    ]


def test_donor_search_rollup_migration_is_idempotent_and_indexed() -> None:
    migration_sql = MIGRATION_PATH.read_text(encoding="utf-8")
    compact_sql = " ".join(migration_sql.lower().split())

    create_tables = re.findall(r"create\s+table\b", migration_sql, re.IGNORECASE)
    idempotent_tables = re.findall(r"create\s+table\s+if\s+not\s+exists\b", migration_sql, re.IGNORECASE)
    create_indexes = re.findall(r"create\s+(?:unique\s+)?index\b", migration_sql, re.IGNORECASE)
    idempotent_indexes = re.findall(
        r"create\s+(?:unique\s+)?index\s+if\s+not\s+exists\b",
        migration_sql,
        re.IGNORECASE,
    )

    assert create_tables and len(create_tables) == len(idempotent_tables)
    assert create_indexes and len(create_indexes) == len(idempotent_indexes)
    assert "create table if not exists cf.donor_search_rollup" in compact_sql
    assert "create table if not exists cf.donor_search_rollup_provenance" in compact_sql
    assert "using gin (search_text gin_trgm_ops)" in compact_sql
    assert "primary key" in compact_sql


def test_donor_search_rollup_identity_variant_migration_is_idempotent_and_indexed() -> None:
    migration_sql = IDENTITY_VARIANT_MIGRATION_PATH.read_text(encoding="utf-8")
    compact_sql = " ".join(migration_sql.lower().split())

    assert "create table if not exists cf.donor_search_rollup_identity_variant" in compact_sql
    assert "constraint donor_search_rollup_identity_variant_unique unique" in compact_sql
    assert "create index if not exists idx_donor_search_rollup_identity_variant_identity_tuple" in compact_sql
    assert "delete from cf.donor_search_rollup_provenance" in compact_sql
