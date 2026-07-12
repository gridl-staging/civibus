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
CORE_ENTITY_RESOLUTION_SQL = REPO_ROOT / "core" / "schema" / "entity_resolution.sql"
CORE_ER_VIEWS_SQL = REPO_ROOT / "core" / "schema" / "er_views.sql"
WA_CONFIG_PATH = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "WA" / "config.yaml"
FL_CONFIG_PATH = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "FL" / "config.yaml"
FEC_FIELD_MAPPER_PATH = REPO_ROOT / "domains" / "campaign_finance" / "ingest" / "field_mapper.py"
TEST_DATABASE = os.getenv("CIVIC_SCHEMA_TEST_DATABASE", "civibus")

CIVIC_TABLES = [
    "candidacy",
    "contest",
    "contest_result",
    "election",
    "electoral_division",
    "filing_deadline",
    "office",
    "office_roster_link",
    "officeholding",
    "reporting_period",
]

EXPECTED_UNIQUE_INDEXES = [
    "uq_office_canonical_key",
    "uq_office_roster_link_pair",
    "uq_electoral_division_canonical_key",
    "uq_contest_canonical_key",
    "uq_contest_result_canonical",
    "uq_election_natural_key",
    "uq_filing_deadline_natural_key",
    "uq_reporting_period_natural_key",
    "uq_candidacy_canonical_key",
    "uq_officeholding_canonical_key",
    "uq_electoral_division_ocd_id",
]

EXPECTED_TRIGRAM_INDEXES = [
    "idx_office_name_trgm",
    "idx_contest_name_trgm",
]
EXPECTED_SPATIAL_INDEXES = [
    "idx_electoral_division_geometry",
]

EXPECTED_GIST_INDEXES = [
    "idx_electoral_division_geometry",
]
EXPECTED_ZCTA_DISTRICT_COLUMNS = [
    "zcta5|text|NO|",
    "state_fips|text|NO|",
    "cd_geoid|text|NO|",
    "district_number|text|NO|",
    "land_share|numeric|NO|",
    "source_url|text|NO|",
]
EXPECTED_ZCTA_DISTRICT_COMMENT = (
    "Approximate ZCTA5-to-119th-congressional-district mapping derived from the Census 2020-ZCTA "
    "relationship file for fundraising geography summaries; not a parcel- or geometry-level district assignment."
)

EXPECTED_FOREIGN_KEYS = [
    ("office", "jurisdiction_id", "jurisdiction", "id"),
    ("office", "source_record_id", "source_record", "id"),
    ("office_roster_link", "office_id", "office", "id"),
    ("office_roster_link", "data_source_id", "data_source", "id"),
    ("electoral_division", "parent_id", "electoral_division", "id"),
    ("electoral_division", "source_record_id", "source_record", "id"),
    ("contest", "office_id", "office", "id"),
    ("contest", "election_id", "election", "id"),
    ("contest", "electoral_division_id", "electoral_division", "id"),
    ("contest", "source_record_id", "source_record", "id"),
    ("contest_result", "contest_id", "contest", "id"),
    ("contest_result", "source_record_id", "source_record", "id"),
    ("election", "office_id", "office", "id"),
    ("election", "electoral_division_id", "electoral_division", "id"),
    ("election", "source_record_id", "source_record", "id"),
    ("filing_deadline", "election_id", "election", "id"),
    ("filing_deadline", "office_id", "office", "id"),
    ("filing_deadline", "electoral_division_id", "electoral_division", "id"),
    ("filing_deadline", "source_record_id", "source_record", "id"),
    ("reporting_period", "election_id", "election", "id"),
    ("reporting_period", "source_record_id", "source_record", "id"),
    ("candidacy", "person_id", "person", "id"),
    ("candidacy", "contest_id", "contest", "id"),
    ("candidacy", "committee_id", "committee", "id"),
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
VICE_PRESIDENT_SEED_ID = "00000000-0000-4000-8000-000000000104"
HOUSE_DELEGATE_SEED_ID = "00000000-0000-4000-8000-000000000105"
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


def _index_definition(database: str, index_name: str) -> str | None:
    rows = _run_psql_command(
        database,
        f"SELECT indexdef FROM pg_indexes WHERE schemaname = 'civic' AND indexname = '{index_name}';",
    )
    return rows[0] if rows else None


def _column_format_type(database: str, table_name: str, column_name: str) -> str | None:
    rows = _run_psql_command(
        database,
        f"""
        SELECT format_type(a.atttypid, a.atttypmod)
        FROM pg_attribute AS a
        JOIN pg_class AS c ON c.oid = a.attrelid
        JOIN pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname = 'civic'
          AND c.relname = '{table_name}'
          AND a.attname = '{column_name}'
          AND a.attnum > 0
          AND NOT a.attisdropped;
        """,
    )
    return rows[0] if rows else None


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
    # Civic-domain self-referential and intra-domain FKs use 'civic' schema.
    # Cross-domain FKs resolve to core.* by default, except committee -> cf.committee.
    referenced_schema = (
        "cf"
        if referenced_table == "committee"
        else (
            "civic"
            if referenced_table
            in {
                "office",
                "office_roster_link",
                "electoral_division",
                "contest",
                "contest_result",
                "election",
                "filing_deadline",
                "reporting_period",
                "candidacy",
                "officeholding",
            }
            else "core"
        )
    )
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
                  AND ccu.table_schema = '{referenced_schema}'
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
    _run_psql_file(TEST_DATABASE, CORE_ENTITY_RESOLUTION_SQL)
    _run_psql_file(TEST_DATABASE, CORE_ER_VIEWS_SQL)
    _run_psql_command(
        TEST_DATABASE,
        """
        CREATE SCHEMA IF NOT EXISTS cf;
        CREATE TABLE IF NOT EXISTS cf.committee (
            id UUID PRIMARY KEY
        );
        """,
        expect_tuples=False,
    )
    _run_psql_file(TEST_DATABASE, SCHEMA_FILE)


def test_civic_schema_file_exists() -> None:
    assert SCHEMA_FILE.exists(), "domains/civics/schema/tables.sql must exist"


def test_civic_schema_tables_created() -> None:
    for table in CIVIC_TABLES:
        assert _table_exists(TEST_DATABASE, table), f"Missing civic.{table} table"


def test_zcta_district_reference_table_contract() -> None:
    assert _table_exists(TEST_DATABASE, "zcta_district")

    rows = _run_psql_command(
        TEST_DATABASE,
        """
        SELECT column_name || '|' || data_type || '|' || is_nullable || '|' || COALESCE(column_default, '')
        FROM information_schema.columns
        WHERE table_schema = 'civic'
          AND table_name = 'zcta_district'
          AND column_name IN ('zcta5', 'state_fips', 'cd_geoid', 'district_number', 'land_share', 'source_url')
        ORDER BY ordinal_position;
        """,
    )
    assert rows == EXPECTED_ZCTA_DISTRICT_COLUMNS
    assert _column_format_type(TEST_DATABASE, "zcta_district", "land_share") == "numeric(7,5)"

    comment_rows = _run_psql_command(
        TEST_DATABASE,
        """
        SELECT obj_description('civic.zcta_district'::regclass, 'pg_class');
        """,
    )
    assert comment_rows == [EXPECTED_ZCTA_DISTRICT_COMMENT]


def test_zcta_district_lookup_indexes() -> None:
    cd_geoid_index = _index_definition(TEST_DATABASE, "idx_zcta_district_cd_geoid")
    assert cd_geoid_index is not None
    assert "(cd_geoid)" in cd_geoid_index.lower()

    state_fips_index = _index_definition(TEST_DATABASE, "idx_zcta_district_state_fips")
    assert state_fips_index is not None
    assert "(state_fips)" in state_fips_index.lower()


def test_civic_schema_unique_indexes() -> None:
    for index_name in EXPECTED_UNIQUE_INDEXES:
        assert _index_exists(TEST_DATABASE, index_name), f"Missing index: {index_name}"


def test_civic_schema_office_roster_link_lookup_indexes() -> None:
    assert _index_exists(TEST_DATABASE, "idx_office_roster_link_office_id")
    assert _index_exists(TEST_DATABASE, "idx_office_roster_link_data_source_id")


def test_civic_schema_search_trgm_indexes() -> None:
    for index_name in EXPECTED_TRIGRAM_INDEXES:
        indexdef = _index_definition(TEST_DATABASE, index_name)
        assert indexdef is not None, f"Missing index: {index_name}"
        indexdef_lower = indexdef.lower()
        assert "using gin" in indexdef_lower, f"{index_name} must be a GIN index, got: {indexdef}"
        assert "gin_trgm_ops" in indexdef_lower, f"{index_name} must use gin_trgm_ops, got: {indexdef}"


def test_civic_schema_spatial_indexes() -> None:
    for index_name in EXPECTED_GIST_INDEXES:
        indexdef = _index_definition(TEST_DATABASE, index_name)
        assert indexdef is not None, f"Missing index: {index_name}"
        indexdef_lower = indexdef.lower()
        assert "using gist" in indexdef_lower, f"{index_name} must be a GIST index, got: {indexdef}"
        assert "(geometry)" in indexdef_lower, f"{index_name} must index geometry column, got: {indexdef}"
        assert "where (geometry is not null)" in indexdef_lower, (
            f"{index_name} must skip NULL geometry rows, got: {indexdef}"
        )


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


def test_electoral_division_geometry_column_contract() -> None:
    rows = _run_psql_command(
        TEST_DATABASE,
        """
        SELECT is_nullable, udt_name
        FROM information_schema.columns
        WHERE table_schema = 'civic'
          AND table_name = 'electoral_division'
          AND column_name = 'geometry';
        """,
    )
    assert rows
    is_nullable, udt_name = rows[0].split("|")
    assert is_nullable == "YES"
    assert udt_name == "geometry"

    geometry_type_rows = _run_psql_command(
        TEST_DATABASE,
        """
        SELECT postgis_typmod_type(a.atttypmod) || '|' || postgis_typmod_srid(a.atttypmod)
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'civic'
          AND c.relname = 'electoral_division'
          AND a.attname = 'geometry'
          AND a.attnum > 0
          AND NOT a.attisdropped;
        """,
    )
    assert geometry_type_rows == ["MultiPolygon|4326"]


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


def test_candidacy_mvp_column_contract() -> None:
    rows = _run_psql_command(
        TEST_DATABASE,
        """
        SELECT column_name || '|' || data_type || '|' || is_nullable || '|' || COALESCE(column_default, '')
        FROM information_schema.columns
        WHERE table_schema = 'civic'
          AND table_name = 'candidacy'
          AND column_name IN ('name_on_ballot', 'is_unexpired_term', 'raw_fields', 'committee_id')
        ORDER BY column_name;
        """,
    )
    assert rows == [
        "committee_id|uuid|YES|",
        "is_unexpired_term|boolean|NO|false",
        "name_on_ballot|text|YES|",
        "raw_fields|jsonb|NO|'{}'::jsonb",
    ]


def test_candidacy_mvp_lookup_indexes_are_partial() -> None:
    committee_index_definition = _index_definition(TEST_DATABASE, "idx_candidacy_committee_id")
    assert committee_index_definition is not None
    assert "where (committee_id is not null)" in committee_index_definition.lower()

    ballot_name_index_definition = _index_definition(TEST_DATABASE, "idx_candidacy_name_on_ballot")
    assert ballot_name_index_definition is not None
    assert "where (name_on_ballot is not null)" in ballot_name_index_definition.lower()


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


def test_contest_result_column_contract() -> None:
    rows = _run_psql_command(
        TEST_DATABASE,
        """
        SELECT column_name || '|' || data_type || '|' || is_nullable || '|' || COALESCE(column_default, '')
        FROM information_schema.columns
        WHERE table_schema = 'civic'
          AND table_name = 'contest_result'
          AND column_name IN (
            'contest_id',
            'candidate_name',
            'is_certified',
            'is_winner',
            'party',
            'source_record_id',
            'vote_pct',
            'votes'
          )
        ORDER BY column_name;
        """,
    )
    assert rows == [
        "candidate_name|text|NO|",
        "contest_id|uuid|NO|",
        "is_certified|boolean|NO|false",
        "is_winner|boolean|NO|false",
        "party|text|YES|",
        "source_record_id|uuid|NO|",
        "vote_pct|numeric|YES|",
        "votes|integer|NO|",
    ]


def test_contest_election_id_bridge_is_nullable_foreign_key() -> None:
    rows = _run_psql_command(
        TEST_DATABASE,
        """
        SELECT is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'civic'
          AND table_name = 'contest'
          AND column_name = 'election_id';
        """,
    )
    assert rows == ["YES"]
    assert _fk_exists(TEST_DATABASE, "contest", "election_id", "election", "id")


def test_electoral_division_geometry_column_format_type() -> None:
    assert _column_format_type(TEST_DATABASE, "electoral_division", "geometry") == "geometry(MultiPolygon,4326)"


def test_election_natural_key_distinguishes_special_elections() -> None:
    indexdef = _index_definition(TEST_DATABASE, "uq_election_natural_key")
    assert indexdef is not None
    assert "is_special" in indexdef


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
              || '|' || number_of_seats::text || '|' || is_elected::text
        FROM civic.office
        WHERE state IS NULL
          AND office_level = 'federal'
        ORDER BY id;
        """,
    )
    expected_rows = [
        f"{FEC_OFFICE_CODE_TO_SEED_ID['H']}|{FEC_OFFICE_CODE_TO_CANONICAL_NAME['H']}|federal||Representative|435|true",
        f"{FEC_OFFICE_CODE_TO_SEED_ID['S']}|{FEC_OFFICE_CODE_TO_CANONICAL_NAME['S']}|federal||Senator|100|true",
        f"{FEC_OFFICE_CODE_TO_SEED_ID['P']}|{FEC_OFFICE_CODE_TO_CANONICAL_NAME['P']}|federal||President|1|true",
        f"{VICE_PRESIDENT_SEED_ID}|us_vice_president|federal||Vice President|1|true",
        f"{HOUSE_DELEGATE_SEED_ID}|us_house_delegate|federal||Delegate|6|true",
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
