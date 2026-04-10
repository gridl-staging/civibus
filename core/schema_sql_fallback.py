from __future__ import annotations

from pathlib import Path
from typing import LiteralString, cast

from psycopg import sql as psycopg_sql

from core.db import get_connection


def _execute_psycopg_sql(database: str, sql_text: str, *, fetch_rows: bool) -> list[tuple[object, ...]]:
    connection = get_connection(dbname=database)
    connection.autocommit = True
    try:
        try:
            with connection.cursor() as cursor:
                if sql_text.strip():
                    cursor.execute(psycopg_sql.SQL(cast(LiteralString, sql_text)))
                if not fetch_rows or cursor.description is None:
                    return []
                return cursor.fetchall()
        except Exception as exc:  # pragma: no cover - exercised by tests via mocks
            raise RuntimeError(str(exc).strip()) from exc
    finally:
        connection.close()


def run_sql_via_psycopg(database: str, sql: str, *, expect_tuples: bool = True) -> list[str] | str:
    rows = _execute_psycopg_sql(database, sql, fetch_rows=True)
    output_lines = ["|".join("" if value is None else str(value) for value in row) for row in rows]
    if not expect_tuples:
        return "\n".join(output_lines).strip()
    return [line.strip() for line in output_lines if line.strip()]


def run_sql_file_via_psycopg(database: str, sql_file: Path) -> None:
    _execute_psycopg_sql(database, sql_file.read_text(encoding="utf-8"), fetch_rows=False)
