from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.schema_sql_fallback import run_sql_file_via_psycopg, run_sql_via_psycopg


def _mock_connection_with_rows(rows: list[tuple[object, ...]]) -> MagicMock:
    connection = MagicMock()
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.__exit__.return_value = None
    cursor.description = ("column",)
    cursor.fetchall.return_value = rows
    connection.cursor.return_value = cursor
    return connection


def test_run_sql_via_psycopg_returns_trimmed_tuple_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _mock_connection_with_rows([("one",), (" two ",), ("",)])
    monkeypatch.setattr("core.schema_sql_fallback.get_connection", lambda **kwargs: connection)

    result = run_sql_via_psycopg("civibus", "SELECT 1;")

    assert result == ["one", "two"]


def test_run_sql_via_psycopg_raises_runtime_error_on_execute_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _mock_connection_with_rows([])
    cursor = connection.cursor.return_value
    cursor.execute.side_effect = Exception("execute failure")
    monkeypatch.setattr("core.schema_sql_fallback.get_connection", lambda **kwargs: connection)

    with pytest.raises(RuntimeError, match="execute failure"):
        run_sql_via_psycopg("civibus", "SELECT broken;")


def test_run_sql_file_via_psycopg_executes_file_contents(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sql_file = tmp_path / "test.sql"
    sql_file.write_text("SELECT 1;", encoding="utf-8")

    connection = _mock_connection_with_rows([])
    monkeypatch.setattr("core.schema_sql_fallback.get_connection", lambda **kwargs: connection)

    run_sql_file_via_psycopg("civibus", sql_file)

    cursor = connection.cursor.return_value
    cursor.execute.assert_called_once()
