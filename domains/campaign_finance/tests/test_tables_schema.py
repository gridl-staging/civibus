"""Integration test coverage for campaign-finance SQL schema DDL."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.schema_sql_runner import (
    build_base_psql_command,
    run_psql_command,
    run_psql_file,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_FILE = REPO_ROOT / "domains" / "campaign_finance" / "schema" / "tables.sql"
CORE_ENTITIES_SQL = REPO_ROOT / "core" / "schema" / "entities.sql"
CORE_PROVENANCE_SQL = REPO_ROOT / "core" / "schema" / "provenance.sql"
TEST_DATABASE = os.getenv("CF_SCHEMA_TEST_DATABASE", "civibus")


CF_TABLES = [
    "committee",
    "candidate",
    "election",
    "filing",
    "transaction",
    "candidate_committee_link",
    "nc_committee_registry",
]

EXPECTED_FOREIGN_KEYS = [
    ("committee", "organization_id", "organization", "id"),
    ("committee", "source_record_id", "source_record", "id"),
    ("candidate", "person_id", "person", "id"),
    ("candidate", "principal_committee_id", "committee", "id"),
    ("candidate", "source_record_id", "source_record", "id"),
    ("election", "source_record_id", "source_record", "id"),
    ("filing", "committee_id", "committee", "id"),
    ("filing", "candidate_id", "candidate", "id"),
    ("filing", "election_id", "election", "id"),
    ("filing", "amended_from_filing_id", "filing", "id"),
    ("filing", "source_record_id", "source_record", "id"),
    ("transaction", "filing_id", "filing", "id"),
    ("transaction", "committee_id", "committee", "id"),
    ("transaction", "contributor_person_id", "person", "id"),
    ("transaction", "contributor_organization_id", "organization", "id"),
    ("transaction", "contributor_address_id", "address", "id"),
    ("transaction", "recipient_candidate_id", "candidate", "id"),
    ("transaction", "recipient_committee_id", "committee", "id"),
    ("transaction", "source_record_id", "source_record", "id"),
    ("transaction", "amended_by_transaction_id", "transaction", "id"),
    ("candidate_committee_link", "candidate_id", "candidate", "id"),
    ("candidate_committee_link", "committee_id", "committee", "id"),
    ("candidate_committee_link", "election_id", "election", "id"),
    ("candidate_committee_link", "source_record_id", "source_record", "id"),
    ("nc_committee_registry", "data_source_id", "data_source", "id"),
]


def _is_truthy(value: str | None) -> bool:
    return bool(value and value.strip().lower() in {"t", "true", "1"})


def _build_base_psql_command(database: str) -> list[str]:
    return build_base_psql_command(database, command_env_var="CF_SCHEMA_PSQL_CMD", repo_root=REPO_ROOT)


def test_build_base_psql_command_uses_resolved_compose_db_container(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CF_SCHEMA_PSQL_CMD", raising=False)
    monkeypatch.setattr("core.schema_sql_runner.shutil.which", lambda command: f"/usr/bin/{command}")
    monkeypatch.setattr(
        "core.schema_sql_runner.resolve_compose_service_container",
        lambda service_name, *, repo_root: "civibus_stage2-db-1",
    )

    assert _build_base_psql_command("civibus_test") == [
        "docker",
        "exec",
        "civibus_stage2-db-1",
        "psql",
        "-U",
        "civibus",
        "-d",
        "civibus_test",
    ]


def test_build_base_psql_command_falls_back_to_local_psql_when_no_compose_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CF_SCHEMA_PSQL_CMD", raising=False)

    def fake_which(command: str) -> str | None:
        if command == "docker":
            return "/usr/bin/docker"
        if command == "psql":
            return "/usr/bin/psql"
        return None

    monkeypatch.setattr("core.schema_sql_runner.shutil.which", fake_which)
    monkeypatch.setattr(
        "core.schema_sql_runner.resolve_compose_service_container",
        lambda service_name, *, repo_root: None,
    )

    assert _build_base_psql_command("civibus_test") == ["psql", "-d", "civibus_test"]


def _run_psql_command(database: str, sql: str, *, expect_tuples: bool = True) -> list[str] | str:
    return run_psql_command(
        database,
        sql,
        command_env_var="CF_SCHEMA_PSQL_CMD",
        repo_root=REPO_ROOT,
        expect_tuples=expect_tuples,
    )


def _run_psql_file(database: str, sql_file: Path) -> None:
    run_psql_file(database, sql_file, command_env_var="CF_SCHEMA_PSQL_CMD", repo_root=REPO_ROOT)


def _query_returns_expected_first_row(database: str, query: str, expected: str) -> bool:
    rows = _run_psql_command(database, query)
    return bool(rows) and rows[0] == expected


def _query_returns_truthy_first_row(database: str, query: str) -> bool:
    rows = _run_psql_command(database, query)
    return _is_truthy(rows[0] if rows else None)


def _assert_row_exists(
    database: str,
    query: str,
    expected: str,
    *,
    message: str,
) -> None:
    rows = _run_psql_command(database, query)
    assert rows, f"{message}: query returned no rows"
    assert rows[0] == expected, f"{message}: expected '{expected}', got '{rows[0]}'"


def _has_core_schema(database: str) -> bool:
    return _query_returns_expected_first_row(
        database,
        "SELECT count(*)::int FROM information_schema.schemata WHERE schema_name = 'core';",
        "1",
    )


def _load_core_if_needed(database: str) -> None:
    if _has_core_schema(database):
        return
    _run_psql_file(database, CORE_ENTITIES_SQL)
    _run_psql_file(database, CORE_PROVENANCE_SQL)


def _index_exists(database: str, index_name: str) -> bool:
    return _query_returns_expected_first_row(
        database,
        (f"SELECT COUNT(1)::int FROM pg_indexes WHERE schemaname = 'cf' AND indexname = '{index_name}';"),
        "1",
    )


def _table_exists(database: str, table_name: str) -> bool:
    return _query_returns_expected_first_row(
        database,
        (
            "SELECT COUNT(1)::int "
            "FROM information_schema.tables "
            f"WHERE table_schema = 'cf' AND table_name = '{table_name}';"
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
                WHERE tc.table_schema = 'cf'
                  AND tc.table_name = '{table_name}'
                  AND tc.constraint_type = 'FOREIGN KEY'
                  AND kcu.column_name = '{column_name}'
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
            " WHERE c.relnamespace = 'cf'::regnamespace"
            "   AND c.relname = '" + table_name + "'"
            "   AND p.proname = 'set_updated_at'"
            "   AND NOT t.tgisinternal"
            "   AND lower(pg_get_triggerdef(t.oid)) LIKE '%before update%'"
            "   AND pg_get_triggerdef(t.oid) LIKE '%core.set_updated_at%'"
            ")::text;"
        ),
    )


def _days_late_expression(database: str) -> str:
    expression = _run_psql_command(
        database,
        (
            "SELECT pg_get_expr(adbin, adrelid)::text"
            " FROM pg_attrdef a"
            " JOIN pg_attribute c ON a.adrelid = c.attrelid AND a.adnum = c.attnum"
            " WHERE c.attrelid = 'cf.filing'::regclass"
            " AND c.attname = 'days_late';"
        ),
        expect_tuples=False,
    )
    assert isinstance(expression, str)
    return expression


def _has_exclusion_constraint(database: str, table_name: str, constraint_name: str) -> bool:
    return _query_returns_truthy_first_row(
        database,
        (
            f"SELECT EXISTS ("
            f"  SELECT 1 FROM pg_constraint"
            f"  WHERE conrelid = '{table_name}'::regclass AND contype = 'x' AND conname = '{constraint_name}'"
            f")::text;"
        ),
    )


def _skip_if_no_database_access() -> None:
    try:
        _run_psql_command(TEST_DATABASE, "SELECT 1;")
    except Exception as exc:
        pytest.skip(f"Unable to connect to test database '{TEST_DATABASE}': {exc}")


# Production-shaped database names that this test fixture MUST refuse to
# drop the cf schema against. Without this guard, running `pytest` against
# the live Hetzner DB silently nuked production cf data (live incident
# 2026-04-26). The fixture below skips the schema-prep teardown when the
# target DB is one of these names; opt in to destructive setup by setting
# CF_SCHEMA_TEST_DATABASE to a dedicated test DB.
_PROTECTED_DATABASE_NAMES = frozenset({"civibus", "civibus_prod", "civibus_staging"})


@pytest.fixture(scope="session", autouse=True)
def _prepared_schema() -> None:
    _skip_if_no_database_access()
    if TEST_DATABASE in _PROTECTED_DATABASE_NAMES:
        pytest.skip(
            f"Refusing to DROP SCHEMA cf CASCADE against protected production database "
            f"{TEST_DATABASE!r}. Set CF_SCHEMA_TEST_DATABASE to a dedicated test "
            f"database to run schema-prep tests."
        )
    try:
        _load_core_if_needed(TEST_DATABASE)
    except Exception as exc:
        pytest.skip(f"Core schema is required but could not be prepared: {exc}")

    _run_psql_command(TEST_DATABASE, "DROP SCHEMA IF EXISTS cf CASCADE;")
    _run_psql_file(TEST_DATABASE, SCHEMA_FILE)


def test_cf_schema_tables_created():
    for table in CF_TABLES:
        assert _table_exists(TEST_DATABASE, table), f"Missing cf.{table} table"


def test_cf_schema_relationships_and_generated_columns():
    for table, column, ref_table, ref_column in EXPECTED_FOREIGN_KEYS:
        assert _fk_exists(TEST_DATABASE, table, column, ref_table, ref_column), (
            f"Missing FK {table}.{column} -> {ref_table}.{ref_column}"
        )

    assert _has_exclusion_constraint(
        TEST_DATABASE,
        "cf.candidate_committee_link",
        "candidate_committee_link_non_overlapping",
    ), "Missing non-overlap exclusion on candidate_committee_link"

    assert _index_exists(TEST_DATABASE, "uq_transaction_sub_id"), "Missing SUB_ID unique index"
    assert _index_exists(TEST_DATABASE, "uq_filing_transaction_identifier"), (
        "Missing amendment/linkage unique filing-transaction index"
    )
    assert _index_exists(TEST_DATABASE, "idx_committee_name_trgm"), "Missing committee name trigram index"

    days_late = "".join(_days_late_expression(TEST_DATABASE).lower().split())
    assert "greatest" in days_late
    assert "receipt_date" in days_late
    assert "due_date" in days_late


def test_transaction_back_ref_transaction_id_column_is_nullable_text():
    rows = _run_psql_command(
        TEST_DATABASE,
        """
        SELECT data_type || '|' || is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'cf'
          AND table_name = 'transaction'
          AND column_name = 'back_ref_transaction_id';
        """,
    )
    assert rows == ["text|YES"]


def test_cf_schema_updated_at_triggers():
    for table in CF_TABLES:
        assert _has_updated_at_trigger(TEST_DATABASE, table), (
            f"Missing BEFORE UPDATE core.set_updated_at() trigger on cf.{table}"
        )


def _insert_test_election(
    jurisdiction_code: str,
    district: str,
    cand_year: str,
    fec_year: str,
    period_start: str,
    period_end: str,
) -> None:
    _run_psql_command(
        TEST_DATABASE,
        f"INSERT INTO cf.election"
        f" (office, jurisdiction_type, jurisdiction_code,"
        f"  district, candidate_election_year, fec_election_year, valid_period)"
        f" VALUES ('H', 'federal', '{jurisdiction_code}',"
        f"  {district}, {cand_year}, {fec_year},"
        f"  daterange('{period_start}', '{period_end}', '[]'));",
    )


def _insert_committee(fec_committee_id: str, name: str) -> None:
    _run_psql_command(
        TEST_DATABASE,
        f"INSERT INTO cf.committee (fec_committee_id, name) VALUES ('{fec_committee_id}', '{name}');",
    )


def _insert_candidate(
    fec_candidate_id: str,
    name: str,
    *,
    office: str = "H",
    state: str = "ZZ",
    district: str = "01",
) -> None:
    _run_psql_command(
        TEST_DATABASE,
        "INSERT INTO cf.candidate (fec_candidate_id, name, office, state, district) "
        f"VALUES ('{fec_candidate_id}', '{name}', '{office}', '{state}', '{district}');",
    )


def _insert_filing_for_committee(
    filing_fec_id: str,
    committee_fec_id: str,
    *,
    amendment_indicator: str = "N",
) -> None:
    _run_psql_command(
        TEST_DATABASE,
        "INSERT INTO cf.filing (filing_fec_id, committee_id, amendment_indicator) "
        f"SELECT '{filing_fec_id}', cmte.id, '{amendment_indicator}' "
        f"FROM cf.committee cmte WHERE cmte.fec_committee_id = '{committee_fec_id}';",
    )


def _insert_candidate_committee_link(
    candidate_fec_id: str,
    committee_fec_id: str,
    valid_period_sql: str,
) -> None:
    _run_psql_command(
        TEST_DATABASE,
        f"""
        INSERT INTO cf.candidate_committee_link (
            candidate_id,
            committee_id,
            designation,
            valid_period
        )
        SELECT cand.id, cmte.id, NULL, {valid_period_sql}
        FROM cf.candidate cand
        JOIN cf.committee cmte
            ON cmte.fec_committee_id = '{committee_fec_id}'
        WHERE cand.fec_candidate_id = '{candidate_fec_id}';
        """,
    )


def test_election_unique_index_distinguishes_nulls_from_legal_values():
    _insert_test_election("NULL_SENTINEL_CASE", "NULL", "NULL", "NULL", "2024-01-01", "2024-12-31")

    with pytest.raises(RuntimeError, match="uq_election_canonical_key"):
        _insert_test_election("NULL_SENTINEL_CASE", "NULL", "NULL", "NULL", "2025-01-01", "2025-12-31")

    # district='' is distinct from district=NULL
    _insert_test_election("NULL_SENTINEL_CASE", "''", "NULL", "NULL", "2026-01-01", "2026-12-31")

    # fec_election_year=0 is distinct from fec_election_year=NULL
    _insert_test_election("NULL_SENTINEL_CASE", "NULL", "NULL", "0", "2027-01-01", "2027-12-31")

    _assert_row_exists(
        TEST_DATABASE,
        "SELECT count(*)::text FROM cf.election WHERE jurisdiction_code = 'NULL_SENTINEL_CASE';",
        "3",
        message="Expected NULL and legal sentinel-like election values to remain distinct",
    )


def test_transaction_memo_flag_requires_matching_code():
    _insert_committee("C90000002", "Memo Constraint Committee")
    _insert_filing_for_committee("MEMO_CONSTRAINT_FILING", "C90000002")

    with pytest.raises(RuntimeError, match="ck_transaction_memo_flag"):
        _run_psql_command(
            TEST_DATABASE,
            "INSERT INTO cf.transaction ("
            "filing_id, committee_id, transaction_type, amount, is_memo, amendment_indicator"
            ") "
            "SELECT filing.id, filing.committee_id, '15', 10.00, TRUE, 'N' "
            "FROM cf.filing filing WHERE filing.filing_fec_id = 'MEMO_CONSTRAINT_FILING';",
        )

    _run_psql_command(
        TEST_DATABASE,
        "INSERT INTO cf.transaction ("
        "filing_id, committee_id, transaction_type, amount, memo_code, is_memo, amendment_indicator"
        ") "
        "SELECT filing.id, filing.committee_id, '15', 10.00, 'X', TRUE, 'N' "
        "FROM cf.filing filing WHERE filing.filing_fec_id = 'MEMO_CONSTRAINT_FILING';",
    )

    _assert_row_exists(
        TEST_DATABASE,
        "SELECT count(*)::text FROM cf.transaction WHERE memo_code = 'X' AND is_memo = TRUE;",
        "1",
        message="Expected valid memo transactions to remain insertable",
    )


def test_candidate_committee_non_overlap_blocks_null_designation_overlap():
    _insert_committee("C90000001", "Null Designation Overlap Committee")
    _insert_candidate("H9ZZ00001", "Null Designation Overlap Candidate")
    _insert_candidate_committee_link(
        "H9ZZ00001",
        "C90000001",
        "daterange('2024-01-01', '2024-12-31', '[]')",
    )

    with pytest.raises(RuntimeError, match="candidate_committee_link_non_overlapping"):
        _insert_candidate_committee_link(
            "H9ZZ00001",
            "C90000001",
            "daterange('2024-06-01', '2025-03-31', '[]')",
        )


# ---------------------------------------------------------------------------
# NC Committee Registry storage contract tests
# ---------------------------------------------------------------------------

def _column_info(database: str, table: str, column: str) -> dict[str, str]:
    rows = _run_psql_command(
        database,
        f"""
        SELECT column_name || '|' || data_type || '|' || is_nullable
               || '|' || COALESCE(column_default, '')
        FROM information_schema.columns
        WHERE table_schema = 'cf'
          AND table_name = '{table}'
          AND column_name = '{column}';
        """,
    )
    if not rows:
        return {}
    parts = rows[0].split("|")
    return {
        "name": parts[0].strip() if len(parts) > 0 else "",
        "type": parts[1].strip() if len(parts) > 1 else "",
        "nullable": parts[2].strip() if len(parts) > 2 else "",
        "default": parts[3].strip() if len(parts) > 3 else "",
    }


def _nc_registry_column_info(column: str) -> dict[str, str]:
    return _column_info(TEST_DATABASE, "nc_committee_registry", column)


def _check_constraint_exists(database: str, table_name: str, constraint_name: str) -> bool:
    return _query_returns_truthy_first_row(
        database,
        f"""
        SELECT EXISTS (
            SELECT 1 FROM pg_constraint c
            JOIN pg_class r ON c.conrelid = r.oid
            WHERE r.relnamespace = 'cf'::regnamespace
              AND r.relname = '{table_name}'
              AND c.contype = 'c'
              AND c.conname = '{constraint_name}'
        )::text;
        """,
    )


def test_nc_registry_required_columns():
    for col in ("org_group_id", "sboe_id", "committee_name", "status_desc"):
        info = _nc_registry_column_info(col)
        assert info, f"Missing required column cf.nc_committee_registry.{col}"
        assert info["nullable"] == "NO", (
            f"cf.nc_committee_registry.{col} must be NOT NULL"
        )


def test_nc_registry_nullable_columns():
    for col in ("old_id", "candidate_name"):
        info = _nc_registry_column_info(col)
        assert info, f"Missing nullable column cf.nc_committee_registry.{col}"
        assert info["nullable"] == "YES", (
            f"cf.nc_committee_registry.{col} should be nullable"
        )


def test_nc_registry_org_group_id_is_integer():
    info = _nc_registry_column_info("org_group_id")
    assert info["type"] == "integer", (
        f"org_group_id should be integer, got {info['type']}"
    )


def test_nc_registry_unique_org_group_id():
    assert _index_exists(TEST_DATABASE, "uq_nc_committee_registry_org_group_id"), (
        "Missing unique index on org_group_id"
    )


def test_nc_registry_sboe_id_index():
    assert _index_exists(TEST_DATABASE, "idx_nc_committee_registry_sboe_id"), (
        "Missing lookup index on sboe_id"
    )


def test_nc_registry_status_desc_index():
    assert _index_exists(TEST_DATABASE, "idx_nc_committee_registry_status_desc"), (
        "Missing lookup index on status_desc"
    )


def test_nc_registry_lifecycle_timestamps():
    for col in ("first_seen_at", "last_seen_at"):
        info = _nc_registry_column_info(col)
        assert info, f"Missing lifecycle column {col}"
        assert "timestamp" in info["type"], (
            f"{col} should be timestamptz, got {info['type']}"
        )
        assert info["nullable"] == "NO", f"{col} must be NOT NULL"


def test_nc_registry_standard_timestamps():
    for col in ("created_at", "updated_at"):
        info = _nc_registry_column_info(col)
        assert info, f"Missing standard timestamp column {col}"
        assert info["nullable"] == "NO", f"{col} must be NOT NULL"
        assert "now()" in (info.get("default") or "").lower(), (
            f"{col} should default to NOW()"
        )


def test_nc_registry_monotonic_timestamp_check():
    assert _check_constraint_exists(
        TEST_DATABASE,
        "nc_committee_registry",
        "ck_nc_committee_registry_seen_order",
    ), "Missing monotonic timestamp check (last_seen_at >= first_seen_at)"


def test_nc_registry_data_source_fk():
    assert _fk_exists(
        TEST_DATABASE,
        "nc_committee_registry",
        "data_source_id",
        "data_source",
        "id",
    ), "Missing FK nc_committee_registry.data_source_id -> data_source.id"


def test_nc_registry_orchestrator_filter_columns():
    """Orchestrator's seed_progress_from_registry queries is_active and last_filing_date.

    Why: domains/campaign_finance/jurisdictions/states/NC/scraper/orchestrator_progress.py
    uses `WHERE (is_active OR last_filing_date >= window_start)` to select committees
    eligible for ingest. Both columns must exist on the production schema or the
    orchestrator fails immediately with `column "is_active" does not exist`.
    """
    is_active = _nc_registry_column_info("is_active")
    assert is_active, (
        "Missing cf.nc_committee_registry.is_active column required by NC orchestrator"
    )
    assert is_active["type"] == "boolean", (
        f"is_active should be boolean, got {is_active['type']}"
    )

    last_filing = _nc_registry_column_info("last_filing_date")
    assert last_filing, (
        "Missing cf.nc_committee_registry.last_filing_date column required by NC orchestrator"
    )
    assert last_filing["type"] == "date", (
        f"last_filing_date should be date, got {last_filing['type']}"
    )
    assert last_filing["nullable"] == "YES", (
        "last_filing_date should be nullable (no filing data yet for many committees)"
    )


def test_nc_registry_is_active_derived_from_status_desc():
    """is_active should be a generated column derived from status_desc.

    Why: status_desc is the authoritative committee state from CFOrgLkup discovery
    (values like 'ACTIVE (NON-EXEMPT)', 'CLOSED', 'INACTIVE'). Storing is_active as
    a generated column keeps the orchestrator filter in sync with discovery state
    without requiring the loader to know about orchestrator semantics (single source
    of truth: status_desc). Active rows are exactly those whose status_desc starts
    with 'ACTIVE'.
    """
    info = _nc_registry_column_info("is_active")
    assert info, "is_active column must exist"
    # Postgres reports generated columns via is_generated/generation_expression.
    rows = _run_psql_command(
        TEST_DATABASE,
        """
        SELECT is_generated, generation_expression
        FROM information_schema.columns
        WHERE table_schema = 'cf'
          AND table_name = 'nc_committee_registry'
          AND column_name = 'is_active';
        """,
    )
    assert rows and isinstance(rows, list), "is_active introspection returned no rows"
    parts = rows[0].split("|")
    is_generated = parts[0].strip()
    expression = parts[1].strip() if len(parts) > 1 else ""
    assert is_generated == "ALWAYS", (
        f"is_active should be GENERATED ALWAYS, got is_generated={is_generated!r}"
    )
    # The generation expression must reference status_desc and the ACTIVE prefix.
    assert "status_desc" in expression.lower(), (
        f"is_active generation expression must derive from status_desc; got: {expression!r}"
    )
    assert "active" in expression.lower(), (
        f"is_active generation expression must check the ACTIVE prefix; got: {expression!r}"
    )


def test_nc_registry_updated_at_trigger():
    assert _has_updated_at_trigger(TEST_DATABASE, "nc_committee_registry"), (
        "Missing BEFORE UPDATE core.set_updated_at() trigger on cf.nc_committee_registry"
    )


def test_nc_registry_insert_and_monotonic_constraint():
    _run_psql_command(
        TEST_DATABASE,
        """
        WITH seeded_data_source AS (
            INSERT INTO core.data_source (
                domain,
                jurisdiction,
                name,
                source_url,
                source_format
            )
            VALUES (
                'campaign_finance',
                'state/NC',
                'NC Registry Schema Monotonic Test Source',
                'https://cf.ncsbe.gov/CFOrgLkup/',
                'csv'
            )
            ON CONFLICT (domain, jurisdiction, name)
            DO UPDATE SET
                source_url = EXCLUDED.source_url,
                source_format = EXCLUDED.source_format
            RETURNING id
        )
        INSERT INTO cf.nc_committee_registry
            (org_group_id, sboe_id, committee_name, status_desc,
             data_source_id, first_seen_at, last_seen_at)
        SELECT 99999, 'STA-TEST1-C-001', 'Test Committee', 'ACTIVE (NON-EXEMPT)',
               seeded_data_source.id, NOW(), NOW()
        FROM seeded_data_source;
        """,
    )
    _assert_row_exists(
        TEST_DATABASE,
        "SELECT count(*)::text FROM cf.nc_committee_registry WHERE org_group_id = 99999;",
        "1",
        message="NC registry monotonic check test must insert exactly one seed row",
    )

    with pytest.raises(RuntimeError, match="ck_nc_committee_registry_seen_order"):
        _run_psql_command(
            TEST_DATABASE,
            """
            UPDATE cf.nc_committee_registry
            SET last_seen_at = first_seen_at - interval '1 day'
            WHERE org_group_id = 99999;
            """,
        )
