"""Contract tests for candidate self-funding storage migration artifact."""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CANDIDATE_SELF_FUNDING_MIGRATION_FILE = (
    REPO_ROOT / "core" / "schema" / "migrations" / "2026_07_14_candidate_self_funding.sql"
)
SELF_FUNDING_COLUMNS = (
    "candidate_contrib",
    "candidate_loans",
    "candidate_loan_repay",
)


def _migration_sql() -> str:
    return CANDIDATE_SELF_FUNDING_MIGRATION_FILE.read_text(encoding="utf-8")


def _compact(sql: str) -> str:
    return " ".join(sql.lower().split())


def test_candidate_self_funding_migration_contract() -> None:
    assert CANDIDATE_SELF_FUNDING_MIGRATION_FILE.exists(), (
        "Missing additive migration for candidate self-funding storage:"
        " core/schema/migrations/2026_07_14_candidate_self_funding.sql"
    )

    migration_sql = _migration_sql()
    compact_sql = _compact(migration_sql)

    assert "-- canonical reset-time schema: domains/campaign_finance/schema/tables.sql." in migration_sql.lower()
    assert compact_sql.count("alter table cf.candidate") == 1
    assert compact_sql.count("add column if not exists") == len(SELF_FUNDING_COLUMNS)
    for column_name in SELF_FUNDING_COLUMNS:
        assert f"add column if not exists {column_name} numeric(14,2)" in compact_sql

    assert "net_self_funding" not in compact_sql


def test_candidate_self_funding_migration_add_columns_are_idempotent() -> None:
    migration_sql = _migration_sql()
    add_column_clauses = re.findall(r"ADD\s+COLUMN\b", migration_sql, re.IGNORECASE)
    add_column_if_not_exists = re.findall(
        r"ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\b",
        migration_sql,
        re.IGNORECASE,
    )

    assert add_column_clauses
    assert len(add_column_clauses) == len(add_column_if_not_exists)
