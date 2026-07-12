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

    def __init__(self, counts: list[int]) -> None:
        self._counts = list(counts)
        self.executed: list[str] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: object) -> None:
        # psycopg.sql.SQL or plain str — coerce so callers see uniform text.
        self.executed.append(str(query))

    def fetchone(self) -> tuple[int]:
        return (self._counts.pop(0),)


class FakeConnection:
    """Stand-in psycopg connection.

    Tracks ``close()`` so canary tests can assert the container does not leak
    connections on repeated boot attempts.
    """

    def __init__(self, counts: list[int]) -> None:
        self._cursor = FakeCursor(counts)
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
