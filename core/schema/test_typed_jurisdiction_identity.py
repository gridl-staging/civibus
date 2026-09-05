from __future__ import annotations

from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[2]
FRESH_SCHEMA_FILE = REPO_ROOT / "core" / "schema" / "jurisdiction.sql"
MIGRATION_FILE = REPO_ROOT / "core" / "schema" / "migrations" / "2026_08_27_typed_jurisdiction_identity.sql"


def _compact(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").lower().split())


def test_fresh_jurisdiction_schema_owns_nullable_typed_identifiers() -> None:
    sql = _compact(FRESH_SCHEMA_FILE)

    assert "state_fips text" in sql
    assert "county_geoid text" in sql
    assert "place_geoid text" in sql
    assert "state_fips text not null" not in sql
    assert "county_geoid text not null" not in sql
    assert "place_geoid text not null" not in sql
    assert "state_fips ~ '^[0-9]{2}$'" in sql
    assert "county_geoid ~ '^[0-9]{5}$'" in sql
    assert "place_geoid ~ '^[0-9]{7}$'" in sql
    assert "jurisdiction_type = 'state'" in sql
    assert "jurisdiction_type in ('county', 'municipality')" in sql
    assert "jurisdiction_type = 'municipality'" in sql
    assert "'consolidated_city_county'" not in sql

    for column_name in ("state_fips", "county_geoid", "place_geoid"):
        assert re.search(
            rf"create unique index idx_jurisdiction_{column_name}_unique .* where {column_name} is not null",
            sql,
        )


def test_typed_identity_migration_is_atomic_idempotent_forward_delta() -> None:
    sql = _compact(MIGRATION_FILE)

    for column_name in ("state_fips", "county_geoid", "place_geoid"):
        assert f"add column if not exists {column_name} text" in sql
        assert f"create unique index if not exists idx_jurisdiction_{column_name}_unique" in sql
    assert "concurrently" not in sql
    assert "begin;" not in sql
    assert "commit;" not in sql


def test_typed_identity_migration_backfills_only_unambiguous_legacy_shapes() -> None:
    sql = _compact(MIGRATION_FILE)

    assert re.search(
        r"set state_fips = fips .* jurisdiction_type = 'state' .* fips ~ '\^\[0-9\]\{2\}\$'",
        sql,
    )
    assert re.search(
        r"set county_geoid = fips .* jurisdiction_type = 'county' .* fips ~ '\^\[0-9\]\{5\}\$'",
        sql,
    )
    assert re.search(
        r"set place_geoid = fips .* jurisdiction_type = 'municipality' .* fips ~ '\^\[0-9\]\{7\}\$'",
        sql,
    )
    assert "set place_geoid = fips" in sql
    assert "jurisdiction_type = 'municipality' and fips ~ '^[0-9]{5}$'" not in sql
