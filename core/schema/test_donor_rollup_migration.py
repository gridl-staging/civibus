"""Contracts for the donor-search rollup migration."""

from __future__ import annotations

import re
from pathlib import Path

import psycopg


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = REPO_ROOT / "core" / "schema" / "migrations" / "2026_08_01_donor_search_rollup.sql"


def test_donor_search_rollup_relation_exists_after_db_reset(db_conn: psycopg.Connection) -> None:
    with db_conn.cursor() as cursor:
        cursor.execute("SELECT to_regclass('cf.donor_search_rollup')")
        relation = cursor.fetchone()

    assert relation == ("cf.donor_search_rollup",)


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
