
from __future__ import annotations

import os
import sys
import time
import types
from pathlib import Path
from typing import TYPE_CHECKING

import psycopg
import pytest

if TYPE_CHECKING:
    pass

_REEXEC_SENTINEL_ENV_VAR = "CIVIBUS_PYTEST_REEXEC"
_POSTGRES_UNAVAILABLE_PREFIX = "Unable to connect to PostgreSQL at "
_DB_CONNECTION_STARTUP_RETRY_ATTEMPTS = 10
_DB_CONNECTION_STARTUP_RETRY_DELAY_SECONDS = 1.0
_postgres_unavailable_error_message: str | None = None
_STAGE1_BOOTSTRAP_DRIFT_PREFIX = "Stage 1 bootstrap contract drift detected. Missing canaries: "
_CONTEST_RESULT_CANARY_PREFIX = "civic.contest_result."
_REPO_ROOT = Path(__file__).resolve().parent
_CIVICS_SCHEMA_PATH = _REPO_ROOT / "domains" / "civics" / "schema" / "tables.sql"
_CIVICS_CANDIDACY_MIGRATION_PATH = (
    _REPO_ROOT / "domains" / "civics" / "schema" / "migrations" / "2026_04_30_candidacy_mvp_columns.sql"
)
_ENTITY_RESOLUTION_SCHEMA_PATH = _REPO_ROOT / "core" / "schema" / "entity_resolution.sql"
_PERSON_BIO_MIGRATION_PATH = _REPO_ROOT / "core" / "schema" / "migrations" / "2026_04_30_person_bio_fields.sql"
_COMMITTEE_SUMMARY_DERIVED_MIGRATION_PATH = (
    _REPO_ROOT / "core" / "schema" / "migrations" / "2026_07_12_committee_summary_derived_aggregates.sql"
)
_ENTITY_SOURCE_CIVIC_TYPES_MIGRATION_PATH = (
    _REPO_ROOT / "core" / "schema" / "migrations" / "2026_07_13_entity_source_civic_types.sql"
)
_ER_VIEWS_SCHEMA_PATH = _REPO_ROOT / "core" / "schema" / "er_views.sql"
_CONTEST_SECTION_START = "-- Contest"
_CONTEST_SECTION_END = "-- Contest Result"
_CONTEST_RESULT_SECTION_START = "-- Contest Result"
_CONTEST_RESULT_SECTION_END = "-- Filing Deadline"
_CONTEST_RESULT_TRIGGER_START = "CREATE TRIGGER trg_contest_result_updated_at"
_CONTEST_RESULT_TRIGGER_END = "CREATE TRIGGER trg_election_updated_at"
_MATCH_DECISION_SECTION_START = "-- Match Decision"
_MATCH_DECISION_SECTION_END = "-- Entity Cluster"
_CONTEST_RESULT_CANARY_REPAIR_SQL = {
    "civic.uq_contest_result_canonical": """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_indexes
                WHERE schemaname = 'civic'
                  AND indexname = 'uq_contest_result_canonical'
            ) AND NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'uq_contest_result_canonical'
            ) THEN
                EXECUTE 'DROP INDEX civic.uq_contest_result_canonical';
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'uq_contest_result_canonical'
            ) THEN
                ALTER TABLE civic.contest_result
                ADD CONSTRAINT uq_contest_result_canonical
                UNIQUE (contest_id, source_record_id, candidate_name);
            END IF;
        END $$;
    """,
    "civic.contest_result.candidate_name": """
        ALTER TABLE civic.contest_result
        ADD COLUMN IF NOT EXISTS candidate_name TEXT NOT NULL DEFAULT ''
    """,
    "civic.contest_result.party": """
        ALTER TABLE civic.contest_result
        ADD COLUMN IF NOT EXISTS party TEXT
    """,
    "civic.contest_result.votes": """
        ALTER TABLE civic.contest_result
        ADD COLUMN IF NOT EXISTS votes INTEGER NOT NULL DEFAULT 0 CHECK (votes >= 0)
    """,
    "civic.contest_result.vote_pct": """
        ALTER TABLE civic.contest_result
        ADD COLUMN IF NOT EXISTS vote_pct NUMERIC(6,2) CHECK (
            vote_pct IS NULL OR (vote_pct >= 0 AND vote_pct <= 100)
        )
    """,
    "civic.contest_result.is_certified": """
        ALTER TABLE civic.contest_result
        ADD COLUMN IF NOT EXISTS is_certified BOOLEAN NOT NULL DEFAULT FALSE
    """,
    "civic.trg_contest_result_updated_at": """
        DROP TRIGGER IF EXISTS trg_contest_result_updated_at ON civic.contest_result;
        CREATE TRIGGER trg_contest_result_updated_at
            BEFORE UPDATE ON civic.contest_result
            FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """,
}
_CANDIDACY_CANARY_KEYS = frozenset(
    {
        "civic.candidacy.name_on_ballot",
        "civic.candidacy.is_unexpired_term",
        "civic.candidacy.raw_fields",
        "civic.candidacy.committee_id",
        "civic.idx_candidacy_committee_id",
        "civic.idx_candidacy_name_on_ballot",
    }
)
_PERSON_BIO_CANARY_KEYS = frozenset(
    {
        "core.person.bio_text",
        "core.person.bio_source_url",
        "core.person.bio_license",
        "core.person.bio_pulled_at",
    }
)
_COMMITTEE_SUMMARY_DERIVED_CANARY_PREFIX = "cf.committee_summary."
_ENTITY_SOURCE_CIVIC_TYPES_CANARY_KEYS = frozenset(
    {
        "core.entity_source.entity_type.election",
        "core.field_provenance.entity_type.election",
    }
)
_GRAPH_CANARY = "ag_catalog.ag_graph.civibus"

_repo_root_path = str(_REPO_ROOT)
if _repo_root_path in sys.path:
    sys.path.remove(_repo_root_path)
sys.path.insert(0, _repo_root_path)

# Test sessions can inherit another repo's `scripts` package on PYTHONPATH.
_scripts_module = sys.modules.get("scripts")
_scripts_module_file = getattr(_scripts_module, "__file__", None)
if _scripts_module_file is not None and not Path(_scripts_module_file).resolve().is_relative_to(_REPO_ROOT):
    del sys.modules["scripts"]
if "scripts" not in sys.modules:
    _repo_scripts_module = types.ModuleType("scripts")
    _repo_scripts_module.__path__ = [str(_REPO_ROOT / "scripts")]  # type: ignore[attr-defined]
    sys.modules["scripts"] = _repo_scripts_module

# --- Parked-jurisdiction quarantine (federal-first v1, see PRIORITIES.md) ---
# State/city campaign-finance pipelines are FROZEN until post-v1, so their
# ~2,500 tests are excluded from default collection to keep `make test` and CI
# focused on active code. Only per-state/city SUBDIRECTORIES are ignored:
# shared helpers directly under jurisdictions/states/ (load_utils.py etc.) are
# live federal-ingest dependencies and their colocated tests must keep running.
# Escape hatch: CIVIBUS_INCLUDE_PARKED=1 (used by `make test-parked`).
# Contract-tested in tests/test_parked_suite_exclusion.py.
_PARKED_JURISDICTION_PARENTS = (
    _REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states",
    _REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "cities",
)
if not os.environ.get("CIVIBUS_INCLUDE_PARKED"):
    collect_ignore = [
        str(child) for parent in _PARKED_JURISDICTION_PARENTS for child in sorted(parent.iterdir()) if child.is_dir()
    ]


def _reexec_pytest_under_project_python_if_needed() -> None:
    """Re-exec under uv-managed Python 3.12+ if the current interpreter is older."""
    if sys.version_info >= (3, 12):
        return
    if os.environ.get(_REEXEC_SENTINEL_ENV_VAR) == "1":
        return

    os.environ[_REEXEC_SENTINEL_ENV_VAR] = "1"
    reexec_command = [
        "uv",
        "run",
        "--extra",
        "dev",
        "--extra",
        "entity-resolution",
        "pytest",
        *sys.argv[1:],
    ]
    os.execvp("uv", reexec_command)


_reexec_pytest_under_project_python_if_needed()

# Module-level imports for patchability in tests/test_conftest_db_fixtures.py.
from core.db import get_connection  # noqa: E402
from core.graph import age_post_connect, ensure_graph  # noqa: E402
from test_support.bootstrap_canaries import _collect_missing_stage1_canaries  # noqa: E402


# Process-env test defaults for the fail-closed api.main import (module-level
# `app = create_app()` demands API keys + rate-limit env). These lived in
# api/conftest.py, which only loads when api/ is collected — a scoped run like
# `pytest tests` (batman merge validation) crashed at import. The root conftest
# loads for every run, so it is the single owner; api/conftest.py re-reads the
# values it needs from the environment.
_TEST_ENV_DEFAULTS = {
    "CIVIBUS_API_KEYS": "test-suite-default-key",
    "CIVIBUS_RATE_LIMIT_REQUESTS": "100",
    "CIVIBUS_RATE_LIMIT_WINDOW_SECONDS": "60",
}

for _env_var_name, _env_var_value in _TEST_ENV_DEFAULTS.items():
    os.environ.setdefault(_env_var_name, _env_var_value)


def _require_postgres_password() -> None:
    """Default DB-backed tests to the standard local development password."""
    os.environ.setdefault("POSTGRES_PASSWORD", "civibus_dev")


def _connection_or_skip(*, post_connect=None) -> psycopg.Connection:
    """Try to connect with retries; skip or fail if PostgreSQL is unavailable."""
    global _postgres_unavailable_error_message
    if _postgres_unavailable_error_message is not None:
        _skip_or_fail_for_postgres_unavailable(_postgres_unavailable_error_message)

    last_connection_error: RuntimeError | None = None
    for attempt_index in range(_DB_CONNECTION_STARTUP_RETRY_ATTEMPTS):
        try:
            connection = get_connection(post_connect=post_connect)
            _postgres_unavailable_error_message = None
            return connection
        except RuntimeError as error:
            if not str(error).startswith(_POSTGRES_UNAVAILABLE_PREFIX):
                raise
            last_connection_error = error
            if attempt_index == _DB_CONNECTION_STARTUP_RETRY_ATTEMPTS - 1:
                break
            time.sleep(_DB_CONNECTION_STARTUP_RETRY_DELAY_SECONDS)

    assert last_connection_error is not None
    _postgres_unavailable_error_message = str(last_connection_error)
    _skip_or_fail_for_postgres_unavailable(_postgres_unavailable_error_message)


def _skip_or_fail_for_postgres_unavailable(message: str) -> None:
    if os.environ.get("CIVIBUS_REQUIRE_DB") == "1":
        pytest.fail(message)
    pytest.skip(message)


def _schema_section_sql(*, schema_text: str, start_marker: str, end_marker: str) -> str:
    start_index = schema_text.find(start_marker)
    if start_index < 0:
        raise RuntimeError(f"Missing start marker in civics schema: {start_marker}")
    end_index = schema_text.find(end_marker, start_index)
    if end_index < 0:
        raise RuntimeError(f"Missing end marker in civics schema: {end_marker}")
    return schema_text[start_index:end_index].strip()


def _contest_result_bootstrap_sql() -> str:
    schema_text = _CIVICS_SCHEMA_PATH.read_text(encoding="utf-8")
    contest_section = _schema_section_sql(
        schema_text=schema_text,
        start_marker=_CONTEST_SECTION_START,
        end_marker=_CONTEST_SECTION_END,
    )
    contest_result_section = _schema_section_sql(
        schema_text=schema_text,
        start_marker=_CONTEST_RESULT_SECTION_START,
        end_marker=_CONTEST_RESULT_SECTION_END,
    )
    contest_result_trigger = _schema_section_sql(
        schema_text=schema_text,
        start_marker=_CONTEST_RESULT_TRIGGER_START,
        end_marker=_CONTEST_RESULT_TRIGGER_END,
    )
    return "\n".join(
        [
            "CREATE SCHEMA IF NOT EXISTS core;",
            "CREATE TABLE IF NOT EXISTS core.source_record (id UUID PRIMARY KEY);",
            """
            CREATE OR REPLACE FUNCTION core.set_updated_at()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                NEW.updated_at := NOW();
                RETURN NEW;
            END;
            $$;
            """.strip(),
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_type t
                    JOIN pg_namespace n ON n.oid = t.typnamespace
                    WHERE n.nspname = 'core'
                      AND t.typname = 'date_precision'
                ) THEN
                    CREATE TYPE core.date_precision AS ENUM ('day', 'month', 'quarter', 'year', 'approximate');
                END IF;
            END $$;
            """.strip(),
            "CREATE SCHEMA IF NOT EXISTS civic;",
            contest_section,
            contest_result_section,
            "DROP TRIGGER IF EXISTS trg_contest_result_updated_at ON civic.contest_result;",
            contest_result_trigger,
        ]
    )


def _match_decision_bootstrap_sql() -> str:
    """Build targeted SQL to repair only core.match_decision from canonical ER schema."""
    schema_text = _ENTITY_RESOLUTION_SCHEMA_PATH.read_text(encoding="utf-8")
    match_decision_section = _schema_section_sql(
        schema_text=schema_text,
        start_marker=_MATCH_DECISION_SECTION_START,
        end_marker=_MATCH_DECISION_SECTION_END,
    )
    return "\n".join(
        [
            "CREATE SCHEMA IF NOT EXISTS core;",
            match_decision_section,
        ]
    )


def _bootstrap_missing_contest_result_from_canonical_schema(connection: psycopg.Connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('civic.contest_result') IS NOT NULL")
        relation_exists = bool(cursor.fetchone()[0])
        if not relation_exists:
            cursor.execute(_contest_result_bootstrap_sql())
            return

        cursor.execute(
            """
            SELECT
                EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'civic'
                      AND table_name = 'contest_result'
                      AND column_name = 'party'
                ),
                EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'uq_contest_result_canonical'
                ),
                EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'civic'
                      AND table_name = 'contest_result'
                      AND column_name = 'candidate_name_on_ballot'
                )
            """
        )
        has_party_column, has_canonical_constraint, has_legacy_ballot_column = cursor.fetchone()
        if has_party_column and has_canonical_constraint and not has_legacy_ballot_column:
            return

        cursor.execute("DROP TABLE IF EXISTS civic.contest_result CASCADE")
        cursor.execute(_contest_result_bootstrap_sql())


def _relation_exists(connection: psycopg.Connection, relation_name: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s) IS NOT NULL", (relation_name,))
        row = cursor.fetchone()
    return bool(row and row[0])


def _type_exists(connection: psycopg.Connection, schema_name: str, type_name: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_type t
                JOIN pg_namespace n ON n.oid = t.typnamespace
                WHERE n.nspname = %s
                  AND t.typname = %s
            )
            """,
            (schema_name, type_name),
        )
        row = cursor.fetchone()
    return bool(row and row[0])


def _can_repair_officeholding_date_precision(connection: psycopg.Connection) -> bool:
    """Repair only when both target table and enum type already exist."""
    has_officeholding_table = _relation_exists(connection, "civic.officeholding")
    has_date_precision_type = _type_exists(connection, "core", "date_precision")
    return has_officeholding_table and has_date_precision_type


def _can_repair_candidate_committee_link_date_precision(connection: psycopg.Connection) -> bool:
    """Repair only when both target table and enum type already exist."""
    has_link_table = _relation_exists(connection, "cf.candidate_committee_link")
    has_date_precision_type = _type_exists(connection, "core", "date_precision")
    return has_link_table and has_date_precision_type


def _ensure_core_date_precision_type(connection: psycopg.Connection) -> None:
    with connection.cursor() as cursor:
        _execute_stage1_canary_repair(
            connection,
            cursor,
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_type t
                    JOIN pg_namespace n ON n.oid = t.typnamespace
                    WHERE n.nspname = 'core'
                      AND t.typname = 'date_precision'
                ) THEN
                    EXECUTE 'CREATE TYPE core.date_precision AS ENUM (''day'', ''month'', ''quarter'', ''year'', ''approximate'')';
                END IF;
            END $$;
            """,
        )


def _execute_stage1_canary_repair(
    connection: psycopg.Connection,
    cursor: psycopg.Cursor,
    repair_sql: str,
) -> None:
    """Execute one canary repair and clear transaction state if savepoint cleanup fails."""
    try:
        cursor.execute("SAVEPOINT stage1_canary_repair")
        try:
            cursor.execute(repair_sql)
        except psycopg.Error:
            cursor.execute("ROLLBACK TO SAVEPOINT stage1_canary_repair")
        finally:
            cursor.execute("RELEASE SAVEPOINT stage1_canary_repair")
    except psycopg.Error:
        connection.rollback()


def _bootstrap_missing_stage1_canaries(connection: psycopg.Connection, *, missing_canaries: list[str]) -> None:
    if _CANDIDACY_CANARY_KEYS & set(missing_canaries):
        with connection.cursor() as cursor:
            _execute_stage1_canary_repair(
                connection, cursor, _CIVICS_CANDIDACY_MIGRATION_PATH.read_text(encoding="utf-8")
            )
    if _PERSON_BIO_CANARY_KEYS & set(missing_canaries):
        with connection.cursor() as cursor:
            _execute_stage1_canary_repair(connection, cursor, _PERSON_BIO_MIGRATION_PATH.read_text(encoding="utf-8"))
    if any(canary.startswith(_COMMITTEE_SUMMARY_DERIVED_CANARY_PREFIX) for canary in missing_canaries):
        with connection.cursor() as cursor:
            _execute_stage1_canary_repair(
                connection,
                cursor,
                _COMMITTEE_SUMMARY_DERIVED_MIGRATION_PATH.read_text(encoding="utf-8"),
            )
    if _ENTITY_SOURCE_CIVIC_TYPES_CANARY_KEYS & set(missing_canaries):
        with connection.cursor() as cursor:
            _execute_stage1_canary_repair(
                connection,
                cursor,
                _ENTITY_SOURCE_CIVIC_TYPES_MIGRATION_PATH.read_text(encoding="utf-8"),
            )
    if "civic.officeholding.date_precision" in missing_canaries:
        _ensure_core_date_precision_type(connection)
    if _GRAPH_CANARY in missing_canaries:
        try:
            age_post_connect(connection)
            ensure_graph(connection)
        except psycopg.Error:
            connection.rollback()
    with connection.cursor() as cursor:
        for missing_canary in missing_canaries:
            if not (
                missing_canary.startswith(_CONTEST_RESULT_CANARY_PREFIX)
                or missing_canary == "civic.trg_contest_result_updated_at"
                or missing_canary == "civic.uq_contest_result_canonical"
            ):
                continue
            repair_sql = _CONTEST_RESULT_CANARY_REPAIR_SQL.get(missing_canary)
            if repair_sql:
                _execute_stage1_canary_repair(connection, cursor, repair_sql)
        if "civic.officeholding.date_precision" in missing_canaries and _can_repair_officeholding_date_precision(
            connection
        ):
            _execute_stage1_canary_repair(
                connection,
                cursor,
                """
                ALTER TABLE civic.officeholding
                ADD COLUMN IF NOT EXISTS date_precision core.date_precision NOT NULL DEFAULT 'day'
                """,
            )
        if (
            "cf.candidate_committee_link.date_precision" in missing_canaries
            and _can_repair_candidate_committee_link_date_precision(connection)
        ):
            _execute_stage1_canary_repair(
                connection,
                cursor,
                """
                ALTER TABLE cf.candidate_committee_link
                ADD COLUMN IF NOT EXISTS date_precision core.date_precision NOT NULL DEFAULT 'year'
                """,
            )
        if {"core.person_er_view", "core.organization_er_view"} & set(missing_canaries) and _relation_exists(
            connection, "core.person"
        ):
            _execute_stage1_canary_repair(connection, cursor, _ER_VIEWS_SCHEMA_PATH.read_text(encoding="utf-8"))
        if "core.match_decision" in missing_canaries and not _relation_exists(connection, "core.match_decision"):
            _execute_stage1_canary_repair(connection, cursor, _match_decision_bootstrap_sql())


def _fail_if_stage1_bootstrap_drift_detected(connection: psycopg.Connection) -> None:
    _bootstrap_missing_contest_result_from_canonical_schema(connection)
    connection.commit()
    missing_canaries = _collect_missing_stage1_canaries(connection)
    if missing_canaries:
        # Canary probes can leave the current transaction aborted when optional schema is missing.
        connection.rollback()
        _bootstrap_missing_stage1_canaries(connection, missing_canaries=missing_canaries)
        connection.commit()
        remaining_missing_canaries = _collect_missing_stage1_canaries(connection)
        if remaining_missing_canaries:
            connection.rollback()
            pytest.fail(_STAGE1_BOOTSTRAP_DRIFT_PREFIX + ", ".join(remaining_missing_canaries))


@pytest.fixture
def db_conn() -> psycopg.Connection:
    _require_postgres_password()
    connection = _connection_or_skip()
    try:
        _fail_if_stage1_bootstrap_drift_detected(connection)
        # Preflight SELECTs auto-open a transaction, so reset before explicit BEGIN.
        connection.rollback()
        connection.execute("BEGIN")
        try:
            yield connection
        finally:
            connection.rollback()
    finally:
        connection.close()


@pytest.fixture
def graph_conn() -> psycopg.Connection:
    """Provide a graph-enabled DB connection with AGE bootstrap and drift preflight."""
    _require_postgres_password()
    connection = _connection_or_skip(post_connect=age_post_connect)
    try:
        _fail_if_stage1_bootstrap_drift_detected(connection)
        ensure_graph(connection)
        connection.commit()
        connection.execute("BEGIN")
        try:
            yield connection
        finally:
            connection.rollback()
    finally:
        connection.close()


@pytest.fixture
def committing_db_conn() -> psycopg.Connection:
    """Provide a DB connection for integration tests that commit real work."""
    _require_postgres_password()
    connection = _connection_or_skip()
    try:
        _fail_if_stage1_bootstrap_drift_detected(connection)
        connection.rollback()
        yield connection
    finally:
        connection.close()
