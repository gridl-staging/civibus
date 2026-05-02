
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import psycopg

_REEXEC_SENTINEL_ENV_VAR = "CIVIBUS_PYTEST_REEXEC"
_POSTGRES_UNAVAILABLE_PREFIX = "Unable to connect to PostgreSQL at "
_DB_CONNECTION_STARTUP_RETRY_ATTEMPTS = 10
_DB_CONNECTION_STARTUP_RETRY_DELAY_SECONDS = 1.0
_STAGE1_BOOTSTRAP_DRIFT_PREFIX = "Stage 1 bootstrap contract drift detected. Missing canaries: "
_CONTEST_RESULT_CANARY_PREFIX = "civic.contest_result."
_REPO_ROOT = Path(__file__).resolve().parent
_CIVICS_SCHEMA_PATH = _REPO_ROOT / "domains" / "civics" / "schema" / "tables.sql"
_ENTITY_RESOLUTION_SCHEMA_PATH = _REPO_ROOT / "core" / "schema" / "entity_resolution.sql"
_ER_VIEWS_SCHEMA_PATH = _REPO_ROOT / "core" / "schema" / "er_views.sql"
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
}


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


def _require_postgres_password() -> None:
    """Default DB-backed tests to the standard local development password."""
    os.environ.setdefault("POSTGRES_PASSWORD", "civibus_dev")


def _connection_or_skip(*, post_connect=None) -> psycopg.Connection:
    """Try to connect with retries; skip the test if PostgreSQL is unavailable."""
    last_connection_error: RuntimeError | None = None
    for attempt_index in range(_DB_CONNECTION_STARTUP_RETRY_ATTEMPTS):
        try:
            return get_connection(post_connect=post_connect)
        except RuntimeError as error:
            if not str(error).startswith(_POSTGRES_UNAVAILABLE_PREFIX):
                raise
            last_connection_error = error
            if attempt_index == _DB_CONNECTION_STARTUP_RETRY_ATTEMPTS - 1:
                break
            time.sleep(_DB_CONNECTION_STARTUP_RETRY_DELAY_SECONDS)

    assert last_connection_error is not None
    pytest.skip(str(last_connection_error))


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
            "CREATE SCHEMA IF NOT EXISTS civic;",
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


def _bootstrap_missing_stage1_canaries(connection: psycopg.Connection, *, missing_canaries: list[str]) -> None:
    with connection.cursor() as cursor:
        for missing_canary in missing_canaries:
            if not (
                missing_canary.startswith(_CONTEST_RESULT_CANARY_PREFIX)
                or missing_canary == "civic.uq_contest_result_canonical"
            ):
                continue
            repair_sql = _CONTEST_RESULT_CANARY_REPAIR_SQL.get(missing_canary)
            if repair_sql:
                cursor.execute(repair_sql)
        if "civic.officeholding.date_precision" in missing_canaries:
            cursor.execute(
                """
                ALTER TABLE civic.officeholding
                ADD COLUMN IF NOT EXISTS date_precision core.date_precision NOT NULL DEFAULT 'day'
                """
            )
        if {"core.person_er_view", "core.organization_er_view"} & set(missing_canaries):
            cursor.execute(_ER_VIEWS_SCHEMA_PATH.read_text(encoding="utf-8"))
        if "core.match_decision" in missing_canaries and not _relation_exists(connection, "core.match_decision"):
            cursor.execute(_match_decision_bootstrap_sql())


def _fail_if_stage1_bootstrap_drift_detected(connection: psycopg.Connection) -> None:
    _bootstrap_missing_contest_result_from_canonical_schema(connection)
    connection.commit()
    missing_canaries = _collect_missing_stage1_canaries(connection)
    if missing_canaries:
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
