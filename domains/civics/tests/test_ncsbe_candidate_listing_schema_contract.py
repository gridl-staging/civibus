"""Schema contract for pm_pre_a civic.candidacy columns required by Stage 1."""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PM_PRE_A_MIGRATION_FILES = [
    REPO_ROOT / "domains" / "civics" / "schema" / "migrations" / "2026_04_27_electoral_division_geometry.sql",
    REPO_ROOT / "domains" / "civics" / "schema" / "migrations" / "2026_04_28_entity_source_civic_types.sql",
    REPO_ROOT / "domains" / "civics" / "schema" / "migrations" / "2026_04_28_office_roster_link.sql",
]
REQUIRED_CANDIDACY_COLUMNS = ["name_on_ballot", "is_unexpired_term", "raw_fields", "committee_id"]


@pytest.mark.integration
def test_pm_pre_a_migration_files_exist_on_disk() -> None:
    missing = [str(path.relative_to(REPO_ROOT)) for path in PM_PRE_A_MIGRATION_FILES if not path.exists()]
    assert not missing, f"Missing required civics migration files for Stage 1 schema contract: {missing}"


@pytest.mark.integration
def test_candidacy_columns_required_by_pm_pre_a_exist(db_conn: psycopg.Connection) -> None:
    rows = db_conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'civic'
          AND table_name = 'candidacy'
        """
    ).fetchall()
    existing_columns = {row[0] for row in rows}
    missing_columns = [column for column in REQUIRED_CANDIDACY_COLUMNS if column not in existing_columns]

    assert not missing_columns, (
        "Missing pm_pre_a-required civic.candidacy columns: "
        f"{missing_columns}. Reapply civics schema migrations after make db-reset."
    )
