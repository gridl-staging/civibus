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


def test_skip_if_no_database_access_skips_when_database_is_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CIVIBUS_REQUIRE_DB", raising=False)
    monkeypatch.setitem(
        schema_tests._skip_if_no_database_access.__globals__,
        "_run_psql_command",
        lambda database, sql: (_ for _ in ()).throw(RuntimeError("connection refused")),
    )

    with pytest.raises(pytest.skip.Exception, match="Unable to connect to test database"):
        schema_tests._skip_if_no_database_access()


def test_skip_if_no_database_access_fails_when_database_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIVIBUS_REQUIRE_DB", "1")
    monkeypatch.setitem(
        schema_tests._skip_if_no_database_access.__globals__,
        "_run_psql_command",
        lambda database, sql: (_ for _ in ()).throw(RuntimeError("connection refused")),
    )

    try:
        schema_tests._skip_if_no_database_access()
    except pytest.skip.Exception as exc:
        pytest.fail(f"expected required database failure, got skip: {exc}")
    except pytest.fail.Exception as exc:
        assert "Unable to connect to test database" in str(exc)
    else:
        pytest.fail("expected required database failure")
