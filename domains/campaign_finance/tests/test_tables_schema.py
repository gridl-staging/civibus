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


@pytest.fixture(scope="session", autouse=True)
def _prepared_schema() -> None:
    _skip_if_no_database_access()
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
