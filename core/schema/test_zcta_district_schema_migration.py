"""Contract tests for the civic.zcta_district migration artifact."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_FILE = REPO_ROOT / "core" / "schema" / "migrations" / "2026_07_07_zcta_district.sql"
EXPECTED_COLUMN_FRAGMENTS = [
    "zcta5 text primary key check (zcta5 ~ '^[0-9]{5}$')",
    "state_fips text not null check (state_fips ~ '^[0-9]{2}$')",
    "cd_geoid text not null check (cd_geoid ~ '^[0-9a-z]{4}$')",
    "district_number text not null check (char_length(district_number) = 2)",
    "land_share numeric(7,5) not null check (land_share >= 0 and land_share <= 1)",
    "source_url text not null",
]
EXPECTED_COMMENT_FRAGMENT = (
    "approximate zcta5-to-119th-congressional-district mapping derived from the census 2020-zcta "
    "relationship file for fundraising geography summaries; not a parcel- or geometry-level district assignment."
)


def test_zcta_district_migration_contract() -> None:
    sql = MIGRATION_FILE.read_text(encoding="utf-8").lower()
    compact_sql = " ".join(sql.split())

    assert MIGRATION_FILE.exists()
    assert "domains/civics/schema/tables.sql" in sql
    assert "create table if not exists civic.zcta_district" in compact_sql
    for column_fragment in EXPECTED_COLUMN_FRAGMENTS:
        assert column_fragment in compact_sql
    assert "create index if not exists idx_zcta_district_cd_geoid" in compact_sql
    assert "create index if not exists idx_zcta_district_state_fips" in compact_sql
    assert EXPECTED_COMMENT_FRAGMENT in compact_sql
