"""Contract tests for civic schema migration artifacts."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
GEOMETRY_MIGRATION_FILE = (
    REPO_ROOT / "domains" / "civics" / "schema" / "migrations" / "2026_04_27_electoral_division_geometry.sql"
)
OFFICE_ROSTER_LINK_MIGRATION_FILE = (
    REPO_ROOT / "domains" / "civics" / "schema" / "migrations" / "2026_04_28_office_roster_link.sql"
)
CANDIDACY_MVP_COLUMNS_MIGRATION_FILE = (
    REPO_ROOT / "domains" / "civics" / "schema" / "migrations" / "2026_04_30_candidacy_mvp_columns.sql"
)
CONTEST_RESULT_MIGRATION_FILE = (
    REPO_ROOT / "domains" / "civics" / "schema" / "migrations" / "2026_04_30_contest_result_table.sql"
)


def test_electoral_division_geometry_migration_contract() -> None:
    assert GEOMETRY_MIGRATION_FILE.exists(), (
        "Missing in-place migration for civic.electoral_division.geometry:"
        " domains/civics/schema/migrations/2026_04_27_electoral_division_geometry.sql"
    )
    migration_sql = GEOMETRY_MIGRATION_FILE.read_text(encoding="utf-8").lower()

    assert "alter table civic.electoral_division" in migration_sql
    assert "add column if not exists geometry geometry(multipolygon, 4326)" in migration_sql
    assert "create index if not exists idx_electoral_division_geometry" in migration_sql
    assert "using gist (geometry)" in migration_sql
    assert "where geometry is not null" in migration_sql


def test_office_roster_link_migration_contract() -> None:
    assert OFFICE_ROSTER_LINK_MIGRATION_FILE.exists(), (
        "Missing in-place migration for civic.office_roster_link:"
        " domains/civics/schema/migrations/2026_04_28_office_roster_link.sql"
    )
    migration_sql = OFFICE_ROSTER_LINK_MIGRATION_FILE.read_text(encoding="utf-8").lower()

    assert "create table if not exists civic.office_roster_link" in migration_sql
    assert "office_id uuid not null references civic.office(id)" in migration_sql
    assert "data_source_id uuid not null references core.data_source(id)" in migration_sql
    assert "constraint uq_office_roster_link_pair unique (office_id, data_source_id)" in migration_sql
    assert "create index if not exists idx_office_roster_link_office_id" in migration_sql
    assert "create index if not exists idx_office_roster_link_data_source_id" in migration_sql
    assert "create trigger trg_office_roster_link_updated_at" in migration_sql
    assert "execute function core.set_updated_at()" in migration_sql


def test_candidacy_mvp_columns_migration_contract() -> None:
    assert CANDIDACY_MVP_COLUMNS_MIGRATION_FILE.exists(), (
        "Missing in-place migration for civic.candidacy MVP columns:"
        " domains/civics/schema/migrations/2026_04_30_candidacy_mvp_columns.sql"
    )
    migration_sql = CANDIDACY_MVP_COLUMNS_MIGRATION_FILE.read_text(encoding="utf-8").lower()

    assert "alter table civic.candidacy" in migration_sql
    assert "add column if not exists name_on_ballot text" in migration_sql
    assert "add column if not exists is_unexpired_term boolean not null default false" in migration_sql
    assert "add column if not exists raw_fields jsonb not null default '{}'::jsonb" in migration_sql
    assert "add column if not exists committee_id uuid references cf.committee(id)" in migration_sql
    assert "create index if not exists idx_candidacy_committee_id" in migration_sql
    assert "create index if not exists idx_candidacy_name_on_ballot" in migration_sql


def test_contest_result_table_migration_contract() -> None:
    assert CONTEST_RESULT_MIGRATION_FILE.exists(), (
        "Missing in-place migration for civic.contest_result:"
        " domains/civics/schema/migrations/2026_04_30_contest_result_table.sql"
    )
    migration_sql = CONTEST_RESULT_MIGRATION_FILE.read_text(encoding="utf-8").lower()

    assert "drop table if exists civic.contest_result" in migration_sql
    assert "create table civic.contest_result" in migration_sql
    assert "contest_id" in migration_sql and "references civic.contest(id)" in migration_sql
    assert "candidate_name" in migration_sql and "text not null" in migration_sql
    assert "party" in migration_sql
    assert "votes" in migration_sql and "check (votes >= 0)" in migration_sql
    assert "vote_pct" in migration_sql and "numeric(6,2)" in migration_sql
    assert "is_certified" in migration_sql and "boolean not null default false" in migration_sql
    assert "is_winner" in migration_sql and "boolean not null default false" in migration_sql
    assert "source_record_id" in migration_sql and "references core.source_record(id)" in migration_sql
    assert "constraint uq_contest_result_canonical unique (contest_id, source_record_id, candidate_name)" in migration_sql
    assert "create index idx_contest_result_contest_id on civic.contest_result (contest_id);" in migration_sql
    assert "create index idx_contest_result_source_record_id on civic.contest_result (source_record_id);" in migration_sql
    assert "drop trigger if exists trg_contest_result_updated_at on civic.contest_result;" in migration_sql
    assert "create trigger trg_contest_result_updated_at" in migration_sql
    assert "before update on civic.contest_result" in migration_sql
    assert "for each row execute function core.set_updated_at();" in migration_sql
