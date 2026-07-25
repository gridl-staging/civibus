"""Shared test fixtures for federal-first content-health and canary tests.

Single source of truth for the federal-first content counts and production
floors so ``test_health_content.py`` and ``test_canary_check.py`` cannot
silently diverge if the counts are recomputed.

Module name is underscore-prefixed so pytest does not collect it as a test
module.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from api import health_content

FEDERAL_FIRST_COUNTS = health_content.FEDERAL_FIRST_CONTENT_COUNTS
FEDERAL_FIRST_FLOORS = health_content.FEDERAL_FIRST_CONTENT_FLOORS
_DEFAULT_TRANSACTION_CONFIRM_COUNT = object()


def fresh_federal_fec_bulk_pull_row() -> tuple[datetime]:
    """Return explicit successful FEC bulk freshness evidence for direct health tests."""
    return (datetime.now(timezone.utc),)


class FakeCursor:
    """Cursor that returns counts in declaration order of ``_CHECK_QUERIES``.

    Records executed SQL text in ``executed`` so contract tests can assert on
    the query strings the production module issues.
    """

    def __init__(
        self,
        counts: list[int],
        freshness_result: tuple[object, ...] | None,
        present_schema_columns: set[tuple[str, str, str]] | None = None,
        transaction_confirm_count: object = _DEFAULT_TRANSACTION_CONFIRM_COUNT,
    ) -> None:
        self._counts = list(counts)
        self._freshness_result = freshness_result
        self._present_schema_columns = present_schema_columns
        self._transaction_confirm_count = transaction_confirm_count
        self._transaction_estimate: int | None = None
        self.executed: list[str] = []
        self.executed_params: list[object] = []
        self._schema_rows: list[tuple[str, str, str]] = []
        self._last_query_kind = "count"

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: object, params: object = None) -> None:
        # psycopg.sql.SQL or plain str — coerce so callers see uniform text.
        query_text = str(query)
        self.executed.append(query_text)
        self.executed_params.append(params)
        normalized_query = " ".join(query_text.lower().split())
        if "select count(*) from cf.transaction" in normalized_query and " where " not in normalized_query:
            self._last_query_kind = "transaction_confirm"
            return
        if "pg_stat_user_tables" in normalized_query and "relname = 'transaction'" in normalized_query:
            self._last_query_kind = "transaction_estimate"
            return
        self._last_query_kind = "count"
        if params is None:
            return
        if "information_schema.columns" not in query_text:
            return
        required_columns = {(params[index], params[index + 1], params[index + 2]) for index in range(0, len(params), 3)}
        present_columns = required_columns if self._present_schema_columns is None else self._present_schema_columns
        self._schema_rows = sorted(required_columns - present_columns)

    def fetchone(self) -> tuple[object, ...] | None:
        if self._last_query_kind == "transaction_confirm":
            if isinstance(self._transaction_confirm_count, BaseException):
                raise self._transaction_confirm_count
            if self._transaction_confirm_count is _DEFAULT_TRANSACTION_CONFIRM_COUNT:
                return (self._transaction_estimate or 0,)
            return (self._transaction_confirm_count,)
        if self._counts:
            count = self._counts.pop(0)
            if self._last_query_kind == "transaction_estimate":
                self._transaction_estimate = count
            return (count,)
        return self._freshness_result

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
        freshness_result: tuple[object, ...] | None = None,
        present_schema_columns: set[tuple[str, str, str]] | None = None,
        transaction_confirm_count: object = _DEFAULT_TRANSACTION_CONFIRM_COUNT,
    ) -> None:
        self._cursor = FakeCursor(
            counts,
            freshness_result=freshness_result,
            present_schema_columns=present_schema_columns,
            transaction_confirm_count=transaction_confirm_count,
        )
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
