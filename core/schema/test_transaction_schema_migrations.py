"""Contract tests for cf.transaction contributor entity-type migration artifacts."""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TRANSACTION_ENTITY_TYPE_MIGRATION_FILE = (
    REPO_ROOT / "core" / "schema" / "migrations" / "2026_07_07_transaction_entity_type.sql"
)


def _migration_sql() -> str:
    assert TRANSACTION_ENTITY_TYPE_MIGRATION_FILE.exists(), (
        "Missing in-place migration for cf.transaction contributor_entity_type:"
        " core/schema/migrations/2026_07_07_transaction_entity_type.sql"
    )
    return TRANSACTION_ENTITY_TYPE_MIGRATION_FILE.read_text(encoding="utf-8")


def test_transaction_entity_type_migration_contract() -> None:
    migration_sql = _migration_sql().lower()
    compact_sql = " ".join(migration_sql.split())

    assert "domains/campaign_finance/schema/tables.sql" in migration_sql
    assert "alter table cf.transaction" in migration_sql
    assert "add column if not exists contributor_entity_type text" in migration_sql
    assert (
        "create index if not exists idx_transaction_committee_date on cf.transaction (committee_id, transaction_date)"
    ) in compact_sql
    assert "drop index if exists cf.idx_transaction_committee_lookup" in compact_sql


def test_transaction_entity_type_migration_add_columns_and_indexes_are_idempotent() -> None:
    migration_sql = _migration_sql()
    add_column_clauses = re.findall(r"ADD\s+COLUMN\b", migration_sql, re.IGNORECASE)
    add_column_if_not_exists = re.findall(
        r"ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\b",
        migration_sql,
        re.IGNORECASE,
    )
    create_index_clauses = re.findall(r"CREATE\s+INDEX\b", migration_sql, re.IGNORECASE)
    create_index_if_not_exists = re.findall(
        r"CREATE\s+INDEX\s+IF\s+NOT\s+EXISTS\b",
        migration_sql,
        re.IGNORECASE,
    )

    assert add_column_clauses, "Migration must contain at least one ADD COLUMN"
    assert len(add_column_clauses) == len(add_column_if_not_exists), (
        f"All ADD COLUMN clauses must use IF NOT EXISTS; found {len(add_column_clauses)} "
        f"ADD COLUMN but only {len(add_column_if_not_exists)} with IF NOT EXISTS"
    )
    assert create_index_clauses, "Migration must contain at least one CREATE INDEX"
    assert len(create_index_clauses) == len(create_index_if_not_exists), (
        f"All CREATE INDEX clauses must use IF NOT EXISTS; found {len(create_index_clauses)} "
        f"CREATE INDEX but only {len(create_index_if_not_exists)} with IF NOT EXISTS"
    )
