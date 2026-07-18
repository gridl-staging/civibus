"""Shared test fixtures for federal-first content-health and canary tests.

Single source of truth for the federal-first content counts and production
floors so ``test_health_content.py`` and ``test_canary_check.py`` cannot
silently diverge if the counts are recomputed.

Module name is underscore-prefixed so pytest does not collect it as a test
module.
"""

from __future__ import annotations

import pytest

from api import health_content

FEDERAL_FIRST_COUNTS = health_content.FEDERAL_FIRST_CONTENT_COUNTS
FEDERAL_FIRST_FLOORS = health_content.FEDERAL_FIRST_CONTENT_FLOORS


class FakeCursor:
    """Cursor that returns counts in declaration order of ``_CHECK_QUERIES``.

    Records executed SQL text in ``executed`` so contract tests can assert on
    the query strings the production module issues.
    """

    def __init__(
        self,
        counts: list[int],
        present_schema_columns: set[tuple[str, str, str]] | None = None,
    ) -> None:
        self._counts = list(counts)
        self._present_schema_columns = present_schema_columns
        self.executed: list[str] = []
        self._schema_rows: list[tuple[str, str, str]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: object, params: object = None) -> None:
        # psycopg.sql.SQL or plain str — coerce so callers see uniform text.
        self.executed.append(str(query))
        if params is None:
            return
        required_columns = {(params[index], params[index + 1], params[index + 2]) for index in range(0, len(params), 3)}
        present_columns = required_columns if self._present_schema_columns is None else self._present_schema_columns
        self._schema_rows = sorted(required_columns - present_columns)

    def fetchone(self) -> tuple[int]:
        return (self._counts.pop(0),)

    def fetchall(self) -> list[tuple[str, str, str]]:
        return self._schema_rows


class FakeConnection:
    """Stand-in psycopg connection.

    Tracks ``close()`` so canary tests can assert the container does not leak
    connections on repeated boot attempts.
    """

    def __init__(
        self,
        counts: list[int],
        present_schema_columns: set[tuple[str, str, str]] | None = None,
    ) -> None:
        self._cursor = FakeCursor(counts, present_schema_columns=present_schema_columns)
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self._cursor

    def close(self) -> None:
        self.closed = True


def set_federal_floor_env(
    monkeypatch: pytest.MonkeyPatch,
    floors: dict[str, int],
) -> None:
    """Apply the floor map to the ``CIVIBUS_HEALTH_CONTENT_FLOOR_*`` env vars."""
    for key, value in floors.items():
        monkeypatch.setenv(f"CIVIBUS_HEALTH_CONTENT_FLOOR_{key.upper()}", str(value))
