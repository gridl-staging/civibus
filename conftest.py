"""Root pytest conftest — DB fixture wiring with retry and bootstrap-drift preflight."""

from __future__ import annotations

import os
import sys
import time
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import psycopg

_REEXEC_SENTINEL_ENV_VAR = "CIVIBUS_PYTEST_REEXEC"
_POSTGRES_UNAVAILABLE_PREFIX = "Unable to connect to PostgreSQL at "
_DB_CONNECTION_STARTUP_RETRY_ATTEMPTS = 10
_DB_CONNECTION_STARTUP_RETRY_DELAY_SECONDS = 1.0
_STAGE1_BOOTSTRAP_DRIFT_PREFIX = "Stage 1 bootstrap contract drift detected. Missing canaries: "


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


def _fail_if_stage1_bootstrap_drift_detected(connection: psycopg.Connection) -> None:
    missing_canaries = _collect_missing_stage1_canaries(connection)
    if missing_canaries:
        connection.rollback()
        pytest.fail(_STAGE1_BOOTSTRAP_DRIFT_PREFIX + ", ".join(missing_canaries))


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
