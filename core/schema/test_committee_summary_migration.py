"""Contract tests for committee-summary storage migration artifact."""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
COMMITTEE_SUMMARY_MIGRATION_FILE = REPO_ROOT / "core" / "schema" / "migrations" / "2026_07_07_committee_summary.sql"


def _migration_sql() -> str:
    return COMMITTEE_SUMMARY_MIGRATION_FILE.read_text(encoding="utf-8")


def _compact(sql: str) -> str:
    return " ".join(sql.lower().split())


def test_committee_summary_migration_contract() -> None:
    assert COMMITTEE_SUMMARY_MIGRATION_FILE.exists(), (
        "Missing in-place migration for committee summary storage:"
        " core/schema/migrations/2026_07_07_committee_summary.sql"
    )
    migration_sql = _migration_sql()
    compact_sql = _compact(migration_sql)

    assert "domains/campaign_finance/schema/tables.sql" in migration_sql
    assert "create table if not exists cf.committee_summary" in compact_sql
    assert "committee_id uuid not null references cf.committee(id)" in compact_sql
    assert "source_record_id uuid references core.source_record(id)" in compact_sql
    assert "constraint ck_committee_summary_coverage_order check" in compact_sql
    assert "coverage_start_date <= coverage_end_date" in compact_sql
    assert "create unique index if not exists uq_committee_summary_committee_cycle" in compact_sql
    assert "on cf.committee_summary (committee_id, cycle)" in compact_sql
    assert "drop trigger if exists trg_committee_summary_updated_at on cf.committee_summary" in compact_sql
    assert "create trigger trg_committee_summary_updated_at" in compact_sql
    assert "execute function core.set_updated_at()" in compact_sql


def test_committee_summary_migration_create_statements_are_idempotent() -> None:
    migration_sql = _migration_sql()
    create_table_clauses = re.findall(r"CREATE\s+TABLE\b", migration_sql, re.IGNORECASE)
    create_table_if_not_exists = re.findall(r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\b", migration_sql, re.IGNORECASE)
    create_index_clauses = re.findall(r"CREATE\s+(?:UNIQUE\s+)?INDEX\b", migration_sql, re.IGNORECASE)
    create_index_if_not_exists = re.findall(
        r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+IF\s+NOT\s+EXISTS\b",
        migration_sql,
        re.IGNORECASE,
    )

    assert create_table_clauses
    assert len(create_table_clauses) == len(create_table_if_not_exists)
    assert create_index_clauses
    assert len(create_index_clauses) == len(create_index_if_not_exists)
