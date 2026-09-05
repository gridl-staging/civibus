"""Shared test fixtures for federal-first content-health and canary tests.

Single source of truth for the federal-first content counts and production
floors so ``test_health_content.py`` and ``test_canary_check.py`` cannot
silently diverge if the counts are recomputed.

Module name is underscore-prefixed so pytest does not collect it as a test
module.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from api import health_content

FEDERAL_FIRST_COUNTS = health_content.FEDERAL_FIRST_CONTENT_COUNTS
FEDERAL_FIRST_FLOORS = health_content.FEDERAL_FIRST_CONTENT_FLOORS
_DEFAULT_TRANSACTION_CONFIRM_COUNT = object()
_DEFAULT_DONOR_ROLLUP_PROVENANCE = object()


def fresh_federal_fec_bulk_pull_row() -> tuple[datetime]:
    """Return explicit successful FEC bulk freshness evidence for direct health tests."""
    return (datetime.now(timezone.utc),)


def fresh_donor_search_rollup_provenance_row() -> tuple[datetime]:
    """Return a just-rebuilt donor-search rollup provenance row.

    This is the fake's default so existing content-health tests keep asserting
    what they were written to assert. The stale / missing / future arms of the
    guard are proven by dedicated tests that pass those values explicitly, so
    the default cannot make the check vacuous.
    """
    return (datetime.now(timezone.utc),)


class FakeCursor:
    """Cursor that returns static and parameterized counts in ``_CHECK_QUERIES`` order.

    Records SQL text and params in ``executed`` / ``executed_params`` so
    contract tests can assert on the exact parameterized queries the production
    module issues.
    """

    def __init__(
        self,
        counts: list[int],
        freshness_result: tuple[object, ...] | None,
        present_schema_columns: set[tuple[str, str, str]] | None = None,
        transaction_confirm_count: object = _DEFAULT_TRANSACTION_CONFIRM_COUNT,
        candidate_money_rows: list[dict[str, object]] | None = None,
        donor_rollup_provenance_result: object = _DEFAULT_DONOR_ROLLUP_PROVENANCE,
    ) -> None:
        self._counts = list(counts)
        self._freshness_result = freshness_result
        if donor_rollup_provenance_result is _DEFAULT_DONOR_ROLLUP_PROVENANCE:
            # Capture the default before health captures its own observation
            # time; creating it in fetchone() can make the fake evidence future.
            donor_rollup_provenance_result = fresh_donor_search_rollup_provenance_row()
        self._donor_rollup_provenance_result = donor_rollup_provenance_result
        self._present_schema_columns = present_schema_columns
        self._transaction_confirm_count = transaction_confirm_count
        self._candidate_money_rows = candidate_money_rows
        self._transaction_estimate: int | None = None
        self.executed: list[str] = []
        self.executed_params: list[object] = []
        self._schema_rows: list[tuple[str, str, str]] = []
        self._last_query_kind = "count"
        self._last_query_params: object = None

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: object, params: object = None) -> None:
        # psycopg.sql.SQL or plain str — coerce so callers see uniform text.
        query_text = str(query)
        self.executed.append(query_text)
        self.executed_params.append(params)
        self._last_query_params = params
        normalized_query = " ".join(query_text.lower().split())
        if "select count(*) from cf.transaction" in normalized_query and " where " not in normalized_query:
            self._last_query_kind = "transaction_confirm"
            return
        if "pg_stat_user_tables" in normalized_query and "relname = 'transaction'" in normalized_query:
            self._last_query_kind = "transaction_estimate"
            return
        if "from cf.donor_search_rollup_provenance" in normalized_query:
            # Trailing freshness read, not a count — dispatched before the
            # rollup-count branch because both mention donor_search_rollup.
            self._last_query_kind = "donor_rollup_provenance"
            return
        if "select count(*) from cf.donor_search_rollup" in normalized_query:
            self._last_query_kind = "donor_search_rollup"
            return
        if self._candidate_money_rows is not None and "from cf.candidate" in normalized_query:
            # The recent-summary query keeps the inline BETWEEN + >= bounds; the
            # repaired serving query binds its window through the
            # ``selected_cycle_window`` CTE and adds the out-of-cycle promotion
            # branch, so the two are distinguished by those markers.
            if (
                "summary_coverage_end_date between %s and %s" in normalized_query
                and "summary_coverage_end_date >= %s" in normalized_query
            ):
                self._last_query_kind = "candidate_money_recent_summary"
                return
            if "selected_cycle_window" in normalized_query:
                self._last_query_kind = "candidate_money_serving"
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
        if self._last_query_kind == "donor_rollup_provenance":
            result = self._donor_rollup_provenance_result
            assert result is None or isinstance(result, tuple)
            return result
        if self._last_query_kind == "transaction_confirm":
            if isinstance(self._transaction_confirm_count, BaseException):
                raise self._transaction_confirm_count
            if self._transaction_confirm_count is _DEFAULT_TRANSACTION_CONFIRM_COUNT:
                return (self._transaction_estimate or 0,)
            return (self._transaction_confirm_count,)
        if self._last_query_kind == "candidate_money_serving":
            return (self._candidate_money_serving_count(),)
        if self._last_query_kind == "candidate_money_recent_summary":
            return (self._candidate_money_recent_summary_count(),)
        if self._counts:
            count = self._counts.pop(0)
            if self._last_query_kind == "transaction_estimate":
                self._transaction_estimate = count
            return (count,)
        if self._last_query_kind == "donor_search_rollup":
            return (0,)
        return self._freshness_result

    def fetchall(self) -> list[tuple[str, str, str]]:
        return self._schema_rows

    def _candidate_money_serving_count(self) -> int:
        rows, window_start, window_end = self._candidate_money_window_rows()
        # The third bound parameter is the selected-cycle integer that scopes the
        # production suppression subquery; assert it so a resolver that stops
        # binding it cannot pass here.
        params = self._last_query_params
        assert isinstance(params, tuple)
        assert isinstance(params[2], int)
        assert params[2] == window_end.year
        return sum(
            1
            for row in rows
            if _has_candidate_money_totals(row)
            and _candidate_money_row_is_served(
                row,
                window_start=window_start,
                window_end=window_end,
            )
        )

    def _candidate_money_recent_summary_count(self) -> int:
        rows, window_start, window_end = self._candidate_money_window_rows()
        params = self._last_query_params
        assert isinstance(params, tuple)
        cutoff, evaluation_date = params[2], params[3]
        assert isinstance(cutoff, date)
        assert isinstance(evaluation_date, date)
        return sum(
            1
            for row in rows
            if _has_candidate_money_totals(row)
            and _candidate_money_date_is_in_window(
                row.get("summary_coverage_end_date"),
                window_start=window_start,
                window_end=window_end,
            )
            and _candidate_money_date_is_recent(
                row.get("summary_coverage_end_date"),
                cutoff=cutoff,
                evaluation_date=evaluation_date,
            )
        )

    def _candidate_money_window_rows(self) -> tuple[list[dict[str, object]], date, date]:
        assert self._candidate_money_rows is not None
        params = self._last_query_params
        assert isinstance(params, tuple)
        window_start, window_end = params[0], params[1]
        assert isinstance(window_start, date)
        assert isinstance(window_end, date)
        return self._candidate_money_rows, window_start, window_end


class FakeConnection:
    """Stand-in psycopg connection for ordered content-health query results.

    Tracks ``close()`` so canary tests can assert the container does not leak
    connections on repeated boot attempts.
    """

    def __init__(
        self,
        counts: list[int],
        freshness_result: tuple[object, ...] | None = None,
        present_schema_columns: set[tuple[str, str, str]] | None = None,
        transaction_confirm_count: object = _DEFAULT_TRANSACTION_CONFIRM_COUNT,
        candidate_money_rows: list[dict[str, object]] | None = None,
        donor_rollup_provenance_result: object = _DEFAULT_DONOR_ROLLUP_PROVENANCE,
    ) -> None:
        self._cursor = FakeCursor(
            counts,
            freshness_result=freshness_result,
            present_schema_columns=present_schema_columns,
            transaction_confirm_count=transaction_confirm_count,
            candidate_money_rows=candidate_money_rows,
            donor_rollup_provenance_result=donor_rollup_provenance_result,
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


def _has_candidate_money_totals(row: dict[str, object]) -> bool:
    return any(row.get(key) is not None for key in ("total_receipts", "total_disbursements", "cash_on_hand"))


def _candidate_money_coverage_end_date(value: object) -> date | None:
    if not isinstance(value, date) or isinstance(value, datetime):
        return None
    return value


def _candidate_money_date_is_in_window(value: object, *, window_start: date, window_end: date) -> bool:
    coverage_end = _candidate_money_coverage_end_date(value)
    return coverage_end is not None and window_start <= coverage_end <= window_end


def _candidate_money_date_is_recent(value: object, *, cutoff: date, evaluation_date: date) -> bool:
    coverage_end = _candidate_money_coverage_end_date(value)
    return coverage_end is not None and cutoff <= coverage_end <= evaluation_date


def _candidate_money_row_is_served(row: dict[str, object], *, window_start: date, window_end: date) -> bool:
    """Mirror the two branches of ``_CANDIDATE_MONEY_SERVING_COVERAGE_QUERY``.

    (a) coverage-end inside the selected-cycle window, or (b) coverage-end
    strictly before the window and no selected-cycle fundraising activity to
    suppress the out-of-cycle promotion. Rows opt into (b)'s suppression with
    ``selected_cycle_activity=True``; production derives the same signal from
    linked authorized committees. Future-dated coverage-ends fail both branches.
    """
    if _candidate_money_date_is_in_window(
        row.get("summary_coverage_end_date"), window_start=window_start, window_end=window_end
    ):
        return True
    coverage_end = _candidate_money_coverage_end_date(row.get("summary_coverage_end_date"))
    if coverage_end is None or coverage_end >= window_start:
        return False
    return not bool(row.get("selected_cycle_activity", False))
