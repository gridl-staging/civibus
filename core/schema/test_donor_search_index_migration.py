"""Contract tests for donor-search index migration artifacts."""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DONOR_SEARCH_INDEX_MIGRATION_FILE = REPO_ROOT / "core" / "schema" / "migrations" / "2026_07_09_donor_search_index.sql"
CANONICAL_TABLES_FILE = REPO_ROOT / "domains" / "campaign_finance" / "schema" / "tables.sql"
DONOR_SEARCH_INDEX_NAMES = (
    "idx_transaction_contributor_name_lower_trgm",
    "idx_transaction_contributor_employer_lower_trgm",
    "idx_transaction_contributor_zip5",
)
DONOR_SEARCH_PARTIAL_INDEX_NAMES = (
    "idx_transaction_donor_search_name_receipt_trgm",
    "idx_transaction_donor_search_employer_receipt_trgm",
    "idx_transaction_donor_search_zip5_receipt",
)


def _migration_sql() -> str:
    return DONOR_SEARCH_INDEX_MIGRATION_FILE.read_text(encoding="utf-8")


def _compact(sql: str) -> str:
    return " ".join(sql.lower().split())


def test_donor_search_index_migration_contract() -> None:
    assert DONOR_SEARCH_INDEX_MIGRATION_FILE.exists(), (
        "Missing in-place migration for donor search indexes: core/schema/migrations/2026_07_09_donor_search_index.sql"
    )
    migration_sql = _migration_sql()
    compact_sql = _compact(migration_sql)

    assert "-- canonical reset-time schema: domains/campaign_finance/schema/tables.sql." in migration_sql.lower()
    assert "create extension if not exists pg_trgm" in compact_sql
    assert (
        "create index if not exists idx_transaction_contributor_name_lower_trgm"
        " on cf.transaction using gin (lower(contributor_name_raw) gin_trgm_ops)"
    ) in compact_sql
    assert (
        "create index if not exists idx_transaction_contributor_employer_lower_trgm"
        " on cf.transaction using gin (lower(contributor_employer) gin_trgm_ops)"
    ) in compact_sql
    assert (
        "create index if not exists idx_transaction_contributor_zip5 on cf.transaction (left(contributor_zip, 5))"
    ) in compact_sql
    assert (
        "create index if not exists idx_transaction_donor_search_name_receipt_trgm"
        " on cf.transaction using gin (lower(contributor_name_raw) gin_trgm_ops)"
    ) in compact_sql
    assert (
        "create index if not exists idx_transaction_donor_search_employer_receipt_trgm"
        " on cf.transaction using gin (lower(contributor_employer) gin_trgm_ops)"
    ) in compact_sql
    assert (
        "create index if not exists idx_transaction_donor_search_zip5_receipt"
        " on cf.transaction (left(contributor_zip, 5))"
    ) in compact_sql


def test_donor_search_index_migration_create_indexes_are_idempotent() -> None:
    migration_sql = _migration_sql()
    create_index_clauses = re.findall(r"CREATE\s+INDEX\b", migration_sql, re.IGNORECASE)
    create_index_if_not_exists = re.findall(
        r"CREATE\s+INDEX\s+IF\s+NOT\s+EXISTS\b",
        migration_sql,
        re.IGNORECASE,
    )

    assert create_index_clauses
    assert len(create_index_clauses) == len(create_index_if_not_exists)


def test_donor_search_indexes_are_in_canonical_schema_once() -> None:
    canonical_sql = CANONICAL_TABLES_FILE.read_text(encoding="utf-8")

    for index_name in DONOR_SEARCH_INDEX_NAMES + DONOR_SEARCH_PARTIAL_INDEX_NAMES:
        assert canonical_sql.count(index_name) == 1
