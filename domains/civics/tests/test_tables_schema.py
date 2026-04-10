"""Integration test coverage for civic-domain SQL schema DDL."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from domains.campaign_finance.types.models import OfficeType
from core.schema_sql_runner import (
    build_base_psql_command,
    run_psql_command,
    run_psql_file,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_FILE = REPO_ROOT / "domains" / "civics" / "schema" / "tables.sql"
CORE_ENTITIES_SQL = REPO_ROOT / "core" / "schema" / "entities.sql"
CORE_JURISDICTION_SQL = REPO_ROOT / "core" / "schema" / "jurisdiction.sql"
CORE_PROVENANCE_SQL = REPO_ROOT / "core" / "schema" / "provenance.sql"
WA_CONFIG_PATH = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "WA" / "config.yaml"
FL_CONFIG_PATH = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "FL" / "config.yaml"
FEC_FIELD_MAPPER_PATH = REPO_ROOT / "domains" / "campaign_finance" / "ingest" / "field_mapper.py"
TEST_DATABASE = os.getenv("CIVIC_SCHEMA_TEST_DATABASE", "civibus")

CIVIC_TABLES = [
    "candidacy",
    "contest",
    "electoral_division",
    "office",
    "officeholding",
]

EXPECTED_UNIQUE_INDEXES = [
    "uq_office_canonical_key",
    "uq_electoral_division_canonical_key",
    "uq_contest_canonical_key",
    "uq_candidacy_canonical_key",
    "uq_officeholding_canonical_key",
    "uq_electoral_division_ocd_id",
]

EXPECTED_FOREIGN_KEYS = [
    ("office", "jurisdiction_id", "jurisdiction", "id"),
    ("office", "source_record_id", "source_record", "id"),
    ("electoral_division", "parent_id", "electoral_division", "id"),
    ("electoral_division", "source_record_id", "source_record", "id"),
    ("contest", "office_id", "office", "id"),
    ("contest", "electoral_division_id", "electoral_division", "id"),
    ("contest", "source_record_id", "source_record", "id"),
    ("candidacy", "person_id", "person", "id"),
    ("candidacy", "contest_id", "contest", "id"),
    ("candidacy", "source_record_id", "source_record", "id"),
    ("officeholding", "person_id", "person", "id"),
    ("officeholding", "office_id", "office", "id"),
    ("officeholding", "electoral_division_id", "electoral_division", "id"),
    ("officeholding", "source_record_id", "source_record", "id"),
]

FEC_OFFICE_CODE_TO_CANONICAL_NAME = {
    OfficeType.HOUSE.value: "us_house",
    OfficeType.SENATE.value: "us_senate",
    OfficeType.PRESIDENT.value: "us_president",
}
FEC_OFFICE_CODE_TO_SEED_ID = {
    OfficeType.HOUSE.value: "00000000-0000-4000-8000-000000000101",
    OfficeType.SENATE.value: "00000000-0000-4000-8000-000000000102",
    OfficeType.PRESIDENT.value: "00000000-0000-4000-8000-000000000103",
}
STATE_CODE_TO_FIPS = {"WA": "53", "FL": "12"}
STATE_CODES_WITH_STAGE4_OFFICE_SEEDS = tuple(STATE_CODE_TO_FIPS.keys())


def _load_office_levels_from_state_config(config_path: Path) -> set[str]:
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    office_levels: set[str] = set()
    for source_payload in payload.get("data_sources", []):
        coverage_payload = source_payload.get("coverage", {})
        for office_level in coverage_payload.get("office_levels", []):
            if isinstance(office_level, str) and office_level:
                office_levels.add(office_level)
    return office_levels


EXPECTED_OFFICE_LEVELS_BY_STATE = {
    "WA": _load_office_levels_from_state_config(WA_CONFIG_PATH),
    "FL": _load_office_levels_from_state_config(FL_CONFIG_PATH),
}


def _is_truthy(value: str | None) -> bool:
    return bool(value and value.strip().lower() in {"t", "true", "1"})


def _build_base_psql_command(database: str) -> list[str]:
    return build_base_psql_command(database, command_env_var="CIVIC_SCHEMA_PSQL_CMD", repo_root=REPO_ROOT)


def _run_psql_command(database: str, sql: str, *, expect_tuples: bool = True) -> list[str] | str:
    return run_psql_command(
        database,
        sql,
        command_env_var="CIVIC_SCHEMA_PSQL_CMD",
        repo_root=REPO_ROOT,
        expect_tuples=expect_tuples,
    )


def _run_psql_file(database: str, sql_file: Path) -> None:
    run_psql_file(database, sql_file, command_env_var="CIVIC_SCHEMA_PSQL_CMD", repo_root=REPO_ROOT)


def _query_returns_expected_first_row(database: str, query: str, expected: str) -> bool:
    rows = _run_psql_command(database, query)
    return bool(rows) and rows[0] == expected


def _query_returns_truthy_first_row(database: str, query: str) -> bool:
    rows = _run_psql_command(database, query)
    return _is_truthy(rows[0] if rows else None)


def _index_exists(database: str, index_name: str) -> bool:
    return _query_returns_expected_first_row(
        database,
        f"SELECT COUNT(1)::int FROM pg_indexes WHERE schemaname = 'civic' AND indexname = '{index_name}';",
        "1",
    )


def _table_exists(database: str, table_name: str) -> bool:
    return _query_returns_expected_first_row(
        database,
        (
            "SELECT COUNT(1)::int "
            "FROM information_schema.tables "
            f"WHERE table_schema = 'civic' AND table_name = '{table_name}';"
        ),
        "1",
    )


def _fk_exists(
    database: str,
    table_name: str,
    column_name: str,
    referenced_table: str,
    referenced_column: str,
) -> bool:
    # Civic-domain self-referential and intra-domain FKs use 'civic' schema;
    # cross-domain FKs (person, source_record, jurisdiction) use 'core' schema.
    return _query_returns_truthy_first_row(
        database,
        f"""
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.constraint_schema = kcu.constraint_schema
                JOIN information_schema.constraint_column_usage ccu
                    ON tc.constraint_name = ccu.constraint_name
                    AND tc.constraint_schema = ccu.constraint_schema
                WHERE tc.table_schema = 'civic'
                  AND tc.table_name = '{table_name}'
                  AND tc.constraint_type = 'FOREIGN KEY'
                  AND kcu.column_name = '{column_name}'
                  AND ccu.table_schema = CASE
                        WHEN '{referenced_table}' IN ('office', 'electoral_division', 'contest', 'candidacy', 'officeholding') THEN 'civic'
                        ELSE 'core'
                      END
                  AND ccu.table_name = '{referenced_table}'
                  AND ccu.column_name = '{referenced_column}'
            )::text;
        """,
    )


def _has_updated_at_trigger(database: str, table_name: str) -> bool:
    return _query_returns_truthy_first_row(
        database,
        (
            "SELECT EXISTS ("
            " SELECT 1"
            " FROM pg_trigger t"
            " JOIN pg_class c ON c.oid = t.tgrelid"
            " JOIN pg_proc p ON p.oid = t.tgfoid"
            " WHERE c.relnamespace = 'civic'::regnamespace"
            "   AND c.relname = '" + table_name + "'"
            "   AND p.proname = 'set_updated_at'"
            "   AND NOT t.tgisinternal"
            "   AND lower(pg_get_triggerdef(t.oid)) LIKE '%before update%'"
            "   AND pg_get_triggerdef(t.oid) LIKE '%core.set_updated_at%'"
            ")::text;"
        ),
    )


def _has_check_constraint_on_column(database: str, table_name: str, column_name: str) -> bool:
    return _query_returns_truthy_first_row(
        database,
        f"""
        SELECT EXISTS (
            SELECT 1 FROM pg_constraint c
            JOIN pg_class r ON c.conrelid = r.oid
            WHERE r.relnamespace = 'civic'::regnamespace
              AND r.relname = '{table_name}'
              AND c.contype = 'c'
              AND pg_get_constraintdef(c.oid) LIKE '%{column_name}%'
        )::text;
        """,
    )


def _skip_if_no_database_access() -> None:
    try:
        _run_psql_command(TEST_DATABASE, "SELECT 1;")
    except Exception as exc:
        pytest.skip(f"Unable to connect to test database '{TEST_DATABASE}': {exc}")


@pytest.fixture(scope="session", autouse=True)
def _prepared_schema() -> None:
    _skip_if_no_database_access()

    _run_psql_command(TEST_DATABASE, "DROP SCHEMA IF EXISTS civic CASCADE;")
    _run_psql_command(TEST_DATABASE, "DROP SCHEMA IF EXISTS core CASCADE;")

    _run_psql_file(TEST_DATABASE, CORE_ENTITIES_SQL)
    _run_psql_file(TEST_DATABASE, CORE_JURISDICTION_SQL)
    _run_psql_file(TEST_DATABASE, CORE_PROVENANCE_SQL)
    _run_psql_file(TEST_DATABASE, SCHEMA_FILE)


def test_civic_schema_file_exists() -> None:
    assert SCHEMA_FILE.exists(), "domains/civics/schema/tables.sql must exist"


def test_civic_schema_tables_created() -> None:
    for table in CIVIC_TABLES:
        assert _table_exists(TEST_DATABASE, table), f"Missing civic.{table} table"


def test_civic_schema_unique_indexes() -> None:
    for index_name in EXPECTED_UNIQUE_INDEXES:
        assert _index_exists(TEST_DATABASE, index_name), f"Missing index: {index_name}"


def test_civic_schema_foreign_keys() -> None:
    for table, column, referenced_table, referenced_column in EXPECTED_FOREIGN_KEYS:
        assert _fk_exists(TEST_DATABASE, table, column, referenced_table, referenced_column), (
            f"Missing FK civic.{table}.{column} -> {referenced_table}.{referenced_column}"
        )


def test_civic_schema_updated_at_triggers() -> None:
    for table in CIVIC_TABLES:
        assert _has_updated_at_trigger(TEST_DATABASE, table), (
            f"Missing BEFORE UPDATE core.set_updated_at() trigger on civic.{table}"
        )


def test_civic_schema_check_constraints() -> None:
    assert _has_check_constraint_on_column(TEST_DATABASE, "office", "office_level")
    assert _has_check_constraint_on_column(TEST_DATABASE, "electoral_division", "division_type")
    assert _has_check_constraint_on_column(TEST_DATABASE, "contest", "election_type")


def test_officeholding_valid_period_is_daterange() -> None:
    rows = _run_psql_command(
        TEST_DATABASE,
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_schema = 'civic' AND table_name = 'officeholding' "
        "AND column_name = 'valid_period';",
    )
    assert rows == ["daterange"]


def test_officeholding_date_precision_uses_core_enum() -> None:
    rows = _run_psql_command(
        TEST_DATABASE,
        """
            SELECT udt_schema || '.' || udt_name
            FROM information_schema.columns
            WHERE table_schema = 'civic' AND table_name = 'officeholding' AND column_name = 'date_precision';
        """,
    )
    assert rows == ["core.date_precision"]


def test_contest_candidate_list_incomplete_contract() -> None:
    rows = _run_psql_command(
        TEST_DATABASE,
        """
        SELECT
            is_nullable,
            column_default
        FROM information_schema.columns
        WHERE table_schema = 'civic'
          AND table_name = 'contest'
          AND column_name = 'candidate_list_incomplete';
        """,
    )
    assert rows
    is_nullable, column_default = rows[0].split("|")
    assert is_nullable == "NO"
    assert column_default in {"false", "FALSE"}


def test_office_status_columns_are_not_stored_in_table() -> None:
    rows = _run_psql_command(
        TEST_DATABASE,
        """
        SELECT COUNT(1)::int
        FROM information_schema.columns
        WHERE table_schema = 'civic'
          AND table_name = 'office'
          AND column_name IN ('no_officeholder', 'no_active_contest');
        """,
    )
    assert rows == ["0"]


def test_seeded_federal_offices_expand_hsp_with_deterministic_ids() -> None:
    field_mapper_text = FEC_FIELD_MAPPER_PATH.read_text(encoding="utf-8")
    assert '"office": _normalize_optional_text(row.get("CAND_OFFICE"))' in field_mapper_text
    assert set(FEC_OFFICE_CODE_TO_CANONICAL_NAME) == {office_type.value for office_type in OfficeType}

    rows = _run_psql_command(
        TEST_DATABASE,
        """
        SELECT id::text || '|' || name || '|' || office_level || '|' || COALESCE(state, '') || '|' || title
        FROM civic.office
        WHERE state IS NULL
          AND office_level = 'federal'
        ORDER BY id;
        """,
    )
    expected_rows = [
        f"{FEC_OFFICE_CODE_TO_SEED_ID['H']}|{FEC_OFFICE_CODE_TO_CANONICAL_NAME['H']}|federal||Representative",
        f"{FEC_OFFICE_CODE_TO_SEED_ID['S']}|{FEC_OFFICE_CODE_TO_CANONICAL_NAME['S']}|federal||Senator",
        f"{FEC_OFFICE_CODE_TO_SEED_ID['P']}|{FEC_OFFICE_CODE_TO_CANONICAL_NAME['P']}|federal||President",
    ]
    assert rows == expected_rows


def test_seeded_wa_and_fl_office_inventory_matches_verified_levels() -> None:
    rows = _run_psql_command(
        TEST_DATABASE,
        """
        SELECT state || '|' || name
        FROM civic.office
        WHERE state IN ('WA', 'FL')
        ORDER BY state, name;
        """,
    )
    observed_office_levels_by_state = {
        state: {row.split("|", maxsplit=1)[1] for row in rows if row.startswith(f"{state}|")}
        for state in STATE_CODES_WITH_STAGE4_OFFICE_SEEDS
    }
    assert observed_office_levels_by_state == EXPECTED_OFFICE_LEVELS_BY_STATE


def test_seeded_wa_and_fl_state_offices_link_to_state_jurisdictions() -> None:
    rows = _run_psql_command(
        TEST_DATABASE,
        """
        SELECT o.state || '|' || o.name || '|' || COALESCE(j.fips, '') || '|' || COALESCE(j.jurisdiction_type, '')
        FROM civic.office AS o
        LEFT JOIN core.jurisdiction AS j
          ON j.id = o.jurisdiction_id
        WHERE o.state IN ('WA', 'FL')
          AND o.office_level = 'state'
        ORDER BY o.state, o.name;
        """,
    )
    assert rows, "Expected seeded WA/FL state offices in civic.office"

    state_to_observed_fips: dict[str, set[str]] = {state: set() for state in STATE_CODE_TO_FIPS}
    for row in rows:
        state, _, fips, jurisdiction_type = row.split("|")
        assert fips, f"Expected non-null jurisdiction link for {state} office seed"
        assert jurisdiction_type == "state", f"Expected state jurisdiction_type for {state} office seed"
        state_to_observed_fips[state].add(fips)

    assert state_to_observed_fips == {state: {fips} for state, fips in STATE_CODE_TO_FIPS.items()}


def test_seeded_electoral_divisions_define_ocd_hierarchy_and_no_jurisdiction_conflation() -> None:
    division_rows = _run_psql_command(
        TEST_DATABASE,
        """
        SELECT child.name
               || '|'
               || child.division_type
               || '|'
               || COALESCE(child.state, '')
               || '|'
               || COALESCE(child.ocd_id, '')
               || '|'
               || child.is_container::text
               || '|'
               || COALESCE(parent.name, '')
        FROM civic.electoral_division AS child
        LEFT JOIN civic.electoral_division AS parent
          ON parent.id = child.parent_id
        WHERE child.name IN ('us', 'wa', 'fl')
        ORDER BY child.name;
        """,
    )
    assert division_rows == [
        "fl|statewide|FL|ocd-division/country:us/state:fl|false|us",
        "us|statewide||ocd-division/country:us|false|",
        "wa|statewide|WA|ocd-division/country:us/state:wa|false|us",
    ]

    container_rows = _run_psql_command(
        TEST_DATABASE,
        """
        SELECT name || '|' || division_type || '|' || is_container::text
        FROM civic.electoral_division
        WHERE name IN (
            'us_congressional_districts',
            'wa_state_senate_districts',
            'wa_state_house_districts',
            'wa_counties',
            'wa_municipalities',
            'wa_school_districts',
            'wa_special_districts',
            'fl_state_senate_districts',
            'fl_state_house_districts',
            'fl_counties',
            'fl_municipalities',
            'fl_school_districts',
            'fl_special_districts'
        )
        ORDER BY name;
        """,
    )
    assert len(container_rows) == 13
    assert all(row.endswith("|true") for row in container_rows)

    jurisdiction_rows = _run_psql_command(
        TEST_DATABASE,
        """
        SELECT state || '|' || fips || '|' || jurisdiction_type
        FROM core.jurisdiction
        ORDER BY state;
        """,
    )
    assert jurisdiction_rows == ["FL|12|state", "WA|53|state"]
