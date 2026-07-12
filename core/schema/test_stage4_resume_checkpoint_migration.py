"""Contract tests for Stage 4 resume checkpoint migration artifact."""

from __future__ import annotations

import re
from pathlib import Path

from domains.campaign_finance.ingest.bulk_stage4_loader import STAGE4_RESUME_IDENTITY_COLUMNS


REPO_ROOT = Path(__file__).resolve().parents[2]
STAGE4_RESUME_CHECKPOINT_MIGRATION_FILE = (
    REPO_ROOT / "core" / "schema" / "migrations" / "2026_07_09_stage4_resume_checkpoint.sql"
)


def _migration_sql() -> str:
    return STAGE4_RESUME_CHECKPOINT_MIGRATION_FILE.read_text(encoding="utf-8")


def _compact(sql: str) -> str:
    return " ".join(sql.lower().split())


def test_stage4_resume_checkpoint_migration_contract() -> None:
    assert STAGE4_RESUME_CHECKPOINT_MIGRATION_FILE.exists(), (
        "Missing in-place migration for Stage 4 resume checkpoints:"
        " core/schema/migrations/2026_07_09_stage4_resume_checkpoint.sql"
    )
    migration_sql = _migration_sql()
    compact_sql = _compact(migration_sql)
    identity_columns = ", ".join(STAGE4_RESUME_IDENTITY_COLUMNS)

    assert "domains/campaign_finance/schema/tables.sql" in migration_sql
    assert "create table if not exists cf.stage4_resume_checkpoint" in compact_sql
    assert "data_source_id uuid not null references core.data_source(id)" in compact_sql
    assert "cycle integer not null" in compact_sql
    assert "file_type text not null" in compact_sql
    assert "archive_fingerprint text not null" in compact_sql
    assert "archive_member_name text" in compact_sql
    assert "next_source_row_number bigint not null default 0" in compact_sql
    assert "constraint ck_stage4_resume_checkpoint_file_type check" in compact_sql
    assert "file_type in ('itcont')" in compact_sql
    assert "constraint ck_stage4_resume_checkpoint_next_source_row_number check" in compact_sql
    assert "next_source_row_number >= 0" in compact_sql
    assert "create unique index if not exists uq_stage4_resume_checkpoint_identity" in compact_sql
    assert f"on cf.stage4_resume_checkpoint ({identity_columns})" in compact_sql
    assert (
        "drop trigger if exists trg_stage4_resume_checkpoint_updated_at on cf.stage4_resume_checkpoint" in compact_sql
    )
    assert "create trigger trg_stage4_resume_checkpoint_updated_at" in compact_sql
    assert "execute function core.set_updated_at()" in compact_sql


def test_stage4_resume_checkpoint_migration_create_statements_are_idempotent() -> None:
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
