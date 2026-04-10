"""Unit tests for property schema SQL execution path selection."""

from __future__ import annotations

import pytest

from domains.property.tests import test_tables_schema as schema_tests


def test_skip_if_no_database_access_allows_non_cli_sql_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        schema_tests._skip_if_no_database_access.__globals__, "_build_base_psql_command", lambda database: []
    )
    monkeypatch.setitem(
        schema_tests._skip_if_no_database_access.__globals__, "_run_psql_command", lambda database, sql: ["1"]
    )

    try:
        schema_tests._skip_if_no_database_access()
    except pytest.skip.Exception as exc:
        pytest.fail(f"skip should not be triggered when SQL execution succeeds without CLI psql: {exc}")
