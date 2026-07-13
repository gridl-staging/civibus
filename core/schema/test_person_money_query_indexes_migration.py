"""Contract tests for the Stage 3 person-money query supporting migration.

Stage 3 measurement (docs/live-state/2026_07_12_live_query_convergence.md,
s25 warm probes on Fly civibus-db) proved the four person-money surfaces
do not require new cf.transaction or core.source_record indexes beyond
the Stage 1 canonical set. The dominant blocker was a plan-shape defect
in the canonical superseded-source anti-join owner, fixed by rewriting
``NOT_SUPERSEDED_SOURCE_RECORD_WHERE_SQL`` in
``api/contribution_insights_contract.py`` from a ``NOT EXISTS`` clause
(compiles to a repeatedly rescanned Materialize) to a hashed ``NOT IN``
sub-select (compiles to a single hashed SubPlan). That rewrite reuses the
existing Stage 1 partial index
``idx_source_record_superseded_id`` and lands the measured 78 s / 54 s
person-surface warm queries at 331 ms.

This migration file therefore adds no new indexes; it captures the
escalation-policy decision in the audit trail and idempotently drops the
624 MB exploratory ``idx_source_record_active_id_pull_date`` covering
index that an s18 Stage 3 session created on live while investigating
the ``latest_provenance`` path. That index was never in canonical
schema, does not benefit the person-money surfaces, and is not referenced
by any query owner.
"""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PERSON_MONEY_INDEX_MIGRATION_FILE = (
    REPO_ROOT / "core" / "schema" / "migrations" / "2026_07_12_person_money_query_indexes.sql"
)
CANONICAL_TABLES_FILE = REPO_ROOT / "domains" / "campaign_finance" / "schema" / "tables.sql"
EXPLORATORY_INDEX_NAME = "idx_source_record_active_id_pull_date"
CANONICAL_SUPERSEDED_INDEX_NAME = "idx_source_record_superseded_id"


def _migration_sql() -> str:
    return PERSON_MONEY_INDEX_MIGRATION_FILE.read_text(encoding="utf-8")


def _compact(sql: str) -> str:
    return " ".join(sql.lower().split())


def test_person_money_query_indexes_migration_contract() -> None:
    assert PERSON_MONEY_INDEX_MIGRATION_FILE.exists(), (
        "Missing in-place migration for Stage 3 person-money query fixes:"
        " core/schema/migrations/2026_07_12_person_money_query_indexes.sql"
    )
    migration_sql = _migration_sql()
    compact_sql = _compact(migration_sql)

    assert "-- canonical reset-time schema: domains/campaign_finance/schema/tables.sql." in migration_sql.lower()
    assert (f"drop index if exists core.{EXPLORATORY_INDEX_NAME}") in compact_sql
    assert "not_superseded_source_record_where_sql" in compact_sql
    assert CANONICAL_SUPERSEDED_INDEX_NAME in compact_sql


def test_person_money_query_indexes_migration_adds_no_new_index() -> None:
    """The escalation-policy outcome for Stage 3 is a query rewrite, not new
    indexes. If a future change needs one, extend the canonical schema and
    open a new migration — do not silently drop new CREATE INDEX statements
    into this file."""
    migration_sql = _migration_sql()

    create_index_clauses = re.findall(r"CREATE\s+INDEX\b", migration_sql, re.IGNORECASE)

    assert create_index_clauses == [], (
        "Stage 3 supporting migration must add no new indexes; measured"
        " Fly evidence in docs/live-state/2026_07_12_live_query_convergence.md"
        " showed the money surfaces land under 2000 ms via anti-join query"
        " rewrite alone. Unexpected CREATE INDEX clauses: "
        f"{create_index_clauses}"
    )


def test_stage3_exploratory_index_not_in_canonical_schema() -> None:
    """Guard: the 624 MB exploratory covering index must never leak into the
    canonical reset-time schema; a fresh DB rebuild must not resurrect it."""
    canonical_sql = CANONICAL_TABLES_FILE.read_text(encoding="utf-8")

    assert EXPLORATORY_INDEX_NAME not in canonical_sql
