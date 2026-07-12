"""
Stub summary for mar22_03_fec_schedule_e_independent_expenditures/civibus_dev/domains/campaign_finance/quality/reconciliation.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import psycopg

from core.graph import GRAPH_NAME
from core.graph.loader import CONTRIBUTION_LIKE_TYPES, EXPENDITURE_LIKE_TYPES

from .models import CheckResult

# ---------------------------------------------------------------------------
# Shared DB helpers — reused by checks.py
# ---------------------------------------------------------------------------

_DATA_SOURCE_ORDER_BY = "name, id"
"""Stable output order for multi-source jurisdiction reports."""

_EDGE_FAMILIES: tuple[str, ...] = (
    "CONTRIBUTED_TO",
    "SPENT_ON",
    "SUPPORTS",
    "OPPOSES",
    "AFFILIATED_WITH",
    "FILED",
)

_TRANSACTION_SOURCE_RECORD_JOIN = "FROM cf.transaction t JOIN core.source_record sr ON t.source_record_id = sr.id "
_IE_ELIGIBLE_TRANSACTION_JOIN = (
    "FROM cf.transaction t "
    "JOIN core.source_record sr ON t.source_record_id = sr.id "
    "JOIN cf.candidate cand ON cand.id = t.recipient_candidate_id "
)
_CANDIDATE_COMMITTEE_LINK_SOURCE_RECORD_JOIN = (
    "FROM cf.candidate_committee_link ccl JOIN core.source_record sr ON ccl.source_record_id = sr.id "
)
_FILING_SOURCE_RECORD_JOIN = "FROM cf.filing f JOIN core.source_record sr ON f.source_record_id = sr.id "
_EDGE_DENOMINATOR_SQL_BY_FAMILY: dict[str, str] = {
    "CONTRIBUTED_TO": (
        "SELECT COUNT(*) "
        f"{_TRANSACTION_SOURCE_RECORD_JOIN}"
        "WHERE {sr_scope} "
        "AND t.transaction_type = ANY(%s) "
        "AND t.support_oppose IS NULL"
    ),
    "SPENT_ON": (
        "SELECT COUNT(*) "
        f"{_TRANSACTION_SOURCE_RECORD_JOIN}"
        "WHERE {sr_scope} "
        "AND t.transaction_type = ANY(%s) "
        "AND t.support_oppose IS NULL"
    ),
    "SUPPORTS": (f"SELECT COUNT(*) {_IE_ELIGIBLE_TRANSACTION_JOIN}WHERE {{sr_scope}} AND t.support_oppose = %s"),
    "OPPOSES": (f"SELECT COUNT(*) {_IE_ELIGIBLE_TRANSACTION_JOIN}WHERE {{sr_scope}} AND t.support_oppose = %s"),
    "AFFILIATED_WITH": (f"SELECT COUNT(*) {_CANDIDATE_COMMITTEE_LINK_SOURCE_RECORD_JOIN}WHERE {{sr_scope}}"),
    "FILED": (f"SELECT COUNT(*) {_FILING_SOURCE_RECORD_JOIN}WHERE {{sr_scope}}"),
}


def source_record_scope_where(*, alias: str = "sr", active_only: bool = True) -> str:
    """Build reusable source_record scope predicate for data-source-bound queries."""
    _validate_identifier(alias)
    where = f"{alias}.data_source_id = %s"
    if active_only:
        return f"{where} AND {alias}.superseded_by IS NULL"
    return where


def _append_source_key_prefix_filter(
    where: str,
    params: list[object],
    source_key_prefix: str | None,
) -> str:
    """Narrow source_record scope to keys starting with the given prefix."""
    if source_key_prefix is not None:
        where += " AND sr.source_record_key LIKE %s"
        params.append(f"{source_key_prefix}%")
    return where


def resolve_data_source_ids(
    conn: psycopg.Connection,
    *,
    domain: str,
    jurisdiction: str,
    name: str | None = None,
) -> list[UUID]:
    """Return data_source ids matching the given scope."""
    sql = "SELECT id FROM core.data_source WHERE domain = %s AND jurisdiction = %s"
    params: tuple[object, ...] = (domain, jurisdiction)
    if name is not None:
        sql += " AND name = %s"
        params += (name,)

    with conn.cursor() as cur:
        cur.execute(f"{sql} ORDER BY {_DATA_SOURCE_ORDER_BY}", params)  # noqa: S608
        return [row[0] for row in cur.fetchall()]


def list_data_source_jurisdictions(
    conn: psycopg.Connection,
    *,
    domain: str,
) -> list[str]:
    """Return distinct non-null jurisdictions for a domain."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT jurisdiction "
            "FROM core.data_source "
            "WHERE domain = %s AND jurisdiction IS NOT NULL "
            "ORDER BY jurisdiction",
            (domain,),
        )
        return [row[0] for row in cur.fetchall()]


def count_source_records(
    conn: psycopg.Connection,
    data_source_id: UUID,
    *,
    active_only: bool = True,
    source_key_prefix: str | None = None,
) -> int:
    """Count source records for a given data source.

    When source_key_prefix is set, only records whose source_record_key
    starts with that prefix are counted (e.g. ``"schedule_e:"``).
    """
    where = source_record_scope_where(active_only=active_only)
    params: list[object] = [data_source_id]
    where = _append_source_key_prefix_filter(where, params, source_key_prefix)
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM core.source_record sr WHERE {where}", params)  # noqa: S608
        row = cur.fetchone()
        return row[0] if row else 0


def count_graph_edges_by_family(
    conn: psycopg.Connection,
    data_source_id: UUID,
) -> dict[str, int]:
    """Count graph edges per campaign-finance family for one data source."""
    sr_scope = source_record_scope_where(alias="sr")
    # AGE's ag_catalog.cypher(graph_name, ...) expects graph_name as a SQL string
    # literal, not a bind parameter. Keep only data_source_id parameterized.
    graph_name_literal = "'" + GRAPH_NAME.replace("'", "''") + "'"
    counts: dict[str, int] = {}
    with conn.cursor() as cur:
        for family in _EDGE_FAMILIES:
            sql = (
                "SELECT COUNT(*) "
                f"FROM ag_catalog.cypher({graph_name_literal}, $$ "
                f"MATCH ()-[e:{family}]->() "
                "RETURN e "
                "$$) AS edge(v agtype) "
                "JOIN core.source_record sr "
                "ON ((edge.v->>'source_record_id')::uuid) = sr.id "
                f"WHERE {sr_scope}"
            )
            cur.execute(sql, (data_source_id,))
            row = cur.fetchone()
            counts[family] = row[0] if row else 0
    return counts


def expected_edge_denominators(
    conn: psycopg.Connection,
    data_source_id: UUID,
) -> dict[str, int]:
    """Count expected edge baselines from relational campaign-finance tables."""
    sr_scope = source_record_scope_where(alias="sr")
    family_params: dict[str, tuple[object, ...]] = {
        "CONTRIBUTED_TO": (data_source_id, sorted(CONTRIBUTION_LIKE_TYPES)),
        "SPENT_ON": (data_source_id, sorted(EXPENDITURE_LIKE_TYPES)),
        "SUPPORTS": (data_source_id, "S"),
        "OPPOSES": (data_source_id, "O"),
        "AFFILIATED_WITH": (data_source_id,),
        "FILED": (data_source_id,),
    }

    counts: dict[str, int] = {}
    with conn.cursor() as cur:
        for family in _EDGE_FAMILIES:
            sql = _EDGE_DENOMINATOR_SQL_BY_FAMILY[family].format(sr_scope=sr_scope)
            params = family_params[family]
            cur.execute(sql, params)
            row = cur.fetchone()
            counts[family] = row[0] if row else 0
    return counts


def fetch_aggregate(
    conn: psycopg.Connection,
    data_source_id: UUID,
    column: str,
    agg: str = "COUNT",
    *,
    active_only: bool = True,
) -> object:
    """Run a single aggregate (COUNT, MIN, MAX, AVG) on source_record."""
    _validate_identifier(column)
    _validate_identifier(agg)
    aggregate = agg.upper()
    if aggregate not in {"COUNT", "MIN", "MAX", "AVG"}:
        msg = f"Unsupported SQL aggregate: {agg!r}"
        raise ValueError(msg)
    where = source_record_scope_where(active_only=active_only)
    sql = f"SELECT {aggregate}(sr.{column}) FROM core.source_record sr WHERE {where}"  # noqa: S608
    with conn.cursor() as cur:
        cur.execute(sql, (data_source_id,))
        row = cur.fetchone()
        return row[0] if row else None


def null_rate(
    conn: psycopg.Connection,
    data_source_id: UUID,
    column: str,
    *,
    active_only: bool = True,
) -> tuple[int, int]:
    """Return (null_count, total_count) for a column in source_record."""
    _validate_identifier(column)
    where = source_record_scope_where(active_only=active_only)
    sql = (
        f"SELECT COUNT(*) FILTER (WHERE sr.{column} IS NULL), COUNT(*) "  # noqa: S608
        f"FROM core.source_record sr WHERE {where}"
    )
    with conn.cursor() as cur:
        cur.execute(sql, (data_source_id,))
        row = cur.fetchone()
        if row is None:
            return (0, 0)
        return (row[0], row[1])


def raw_field_null_rate(
    conn: psycopg.Connection,
    data_source_id: UUID,
    field_name: str,
    *,
    active_only: bool = True,
    source_key_prefix: str | None = None,
) -> tuple[int, int]:
    """Return (null_count, total_count) for a raw_fields JSONB key.

    A record is counted as null when the key is missing from raw_fields,
    the value is JSON null, or the value is an empty/whitespace-only string.
    """
    where = source_record_scope_where(active_only=active_only)
    where_params: list[object] = [data_source_id]
    where = _append_source_key_prefix_filter(where, where_params, source_key_prefix)
    # field_name is parameterized — safe from injection
    sql = (
        "SELECT "
        "  COUNT(*) FILTER (WHERE sr.raw_fields->>%s IS NULL OR btrim(sr.raw_fields->>%s) = ''), "
        "  COUNT(*) "
        f"FROM core.source_record sr WHERE {where}"
    )
    # field_name params appear in SELECT (before WHERE), so they must come first
    params: list[object] = [field_name, field_name, *where_params]
    with conn.cursor() as cur:
        cur.execute(sql, params)  # noqa: S608
        row = cur.fetchone()
        if row is None:
            return (0, 0)
        return (row[0], row[1])


def duplicate_hashes(
    conn: psycopg.Connection,
    data_source_id: UUID,
    *,
    active_only: bool = True,
    limit: int | None = 20,
    source_key_prefix: str | None = None,
) -> list[tuple[str, int]]:
    where = source_record_scope_where(active_only=active_only)
    params: list[object] = [data_source_id]
    where = _append_source_key_prefix_filter(where, params, source_key_prefix)
    limit_clause = " LIMIT %s" if limit is not None else ""
    sql = (
        f"SELECT sr.record_hash, COUNT(*) AS cnt "  # noqa: S608
        f"FROM core.source_record sr WHERE {where} AND sr.record_hash IS NOT NULL "
        f"GROUP BY sr.record_hash HAVING COUNT(*) > 1 "
        f"ORDER BY cnt DESC{limit_clause}"
    )
    with conn.cursor() as cur:
        if limit is not None:
            params.append(limit)
        cur.execute(sql, params)
        return [(row[0], row[1]) for row in cur.fetchall()]


def pull_date_range(
    conn: psycopg.Connection,
    data_source_id: UUID,
    *,
    active_only: bool = True,
) -> tuple[object, object]:
    """Return (min_pull_date, max_pull_date) for source records."""
    where = source_record_scope_where(active_only=active_only)
    sql = f"SELECT MIN(sr.pull_date), MAX(sr.pull_date) FROM core.source_record sr WHERE {where}"  # noqa: S608
    with conn.cursor() as cur:
        cur.execute(sql, (data_source_id,))
        row = cur.fetchone()
        if row is None:
            return (None, None)
        return (row[0], row[1])


def fetch_data_source_metadata(
    conn: psycopg.Connection,
    data_source_id: UUID,
) -> tuple[str, str | None]:
    """Return (name, source_url) for a data source id."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT name, source_url FROM core.data_source WHERE id = %s",
            (data_source_id,),
        )
        row = cur.fetchone()
        if row is None:
            return (str(data_source_id), None)
        return (row[0], row[1])


@dataclass(frozen=True, slots=True)
class DataSourceSnapshot:
    """Point-in-time snapshot of core.data_source metadata columns."""

    record_count: int | None
    last_pull_status: str | None
    last_pull_at: datetime | None


def fetch_data_source_snapshot(
    conn: psycopg.Connection,
    data_source_id: UUID,
) -> DataSourceSnapshot:
    """Return a metadata snapshot for a data source."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT record_count, last_pull_status, last_pull_at FROM core.data_source WHERE id = %s",
            (data_source_id,),
        )
        row = cur.fetchone()
        if row is None:
            return DataSourceSnapshot(record_count=None, last_pull_status=None, last_pull_at=None)
        return DataSourceSnapshot(record_count=row[0], last_pull_status=row[1], last_pull_at=row[2])


def derive_pull_status_from_counts(inserted: int, skipped: int, errors: int) -> str:
    """Derive pull status from scalar load counts.

    Same semantics as federal ``derive_pull_status`` but accepts scalar
    counts instead of ``list[LoadStepSummary]``.
    """
    if errors == 0:
        return "success"
    if inserted + skipped > 0:
        return "partial"
    return "failed"


def completeness_sample(
    conn: psycopg.Connection,
    data_source_id: UUID,
    columns: tuple[str, ...] = ("source_record_key", "source_url", "raw_fields"),
    *,
    active_only: bool = True,
    sample_limit: int = 1000,
) -> dict[str, tuple[int, int]]:
    """Sample N records and return {column: (null_count, sampled_count)}.

    Uses a deterministic sample ordered by created_at to ensure repeatable results.
    """
    for col in columns:
        _validate_identifier(col)
    where = source_record_scope_where(active_only=active_only)
    select_parts = [f"COUNT(*) FILTER (WHERE sr.{col} IS NULL), COUNT(*)" for col in columns]
    inner_sql = (
        f"SELECT * FROM core.source_record sr WHERE {where} "  # noqa: S608
        f"ORDER BY sr.created_at, sr.id LIMIT %s"
    )
    sql = f"SELECT {', '.join(select_parts)} FROM ({inner_sql}) sr"  # noqa: S608
    with conn.cursor() as cur:
        cur.execute(sql, (data_source_id, sample_limit))
        row = cur.fetchone()
        if row is None:
            return {col: (0, 0) for col in columns}
        result: dict[str, tuple[int, int]] = {}
        for i, col in enumerate(columns):
            result[col] = (row[i * 2], row[i * 2 + 1])
        return result


# ---------------------------------------------------------------------------
# Identifier validation
# ---------------------------------------------------------------------------

_SAFE_IDENTIFIER_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz_0123456789")


def _validate_identifier(name: str) -> None:
    """Guard against SQL injection in dynamic column/aggregate names."""
    if not name or not all(c in _SAFE_IDENTIFIER_CHARS for c in name.lower()):
        msg = f"Invalid SQL identifier: {name!r}"
        raise ValueError(msg)


# ---------------------------------------------------------------------------
# High-level reconciliation checks
# ---------------------------------------------------------------------------


def check_record_count_reconciliation(
    conn: psycopg.Connection,
    data_source_id: UUID,
    data_source_name: str,
) -> CheckResult:
    """Compare core.data_source.record_count to actual source_record count."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT record_count FROM core.data_source WHERE id = %s",
            (data_source_id,),
        )
        row = cur.fetchone()
        expected = row[0] if row else None

    actual = count_source_records(conn, data_source_id)

    if expected is None:
        return CheckResult(
            name="record_count_reconciliation",
            status="warn",
            message=f"{data_source_name}: data_source.record_count is NULL, actual={actual}",
            metric_name="actual_record_count",
            metric_value=float(actual),
            details={"data_source_id": str(data_source_id), "expected": None, "actual": actual},
        )

    if expected == actual:
        return CheckResult(
            name="record_count_reconciliation",
            status="pass",
            message=f"{data_source_name}: expected={expected}, actual={actual}",
            metric_name="record_count_diff",
            metric_value=0.0,
            details={"data_source_id": str(data_source_id), "expected": expected, "actual": actual},
        )

    return CheckResult(
        name="record_count_reconciliation",
        status="fail",
        message=f"{data_source_name}: expected={expected}, actual={actual}",
        metric_name="record_count_diff",
        metric_value=float(abs(expected - actual)),
        details={"data_source_id": str(data_source_id), "expected": expected, "actual": actual},
    )


def check_key_field_completeness(
    conn: psycopg.Connection,
    data_source_id: UUID,
    data_source_name: str,
    *,
    null_rate_threshold: float = 0.05,
    sample_limit: int = 1000,
) -> list[CheckResult]:
    """Check that key fields are populated in a sample of source records."""
    columns = ("source_record_key", "source_url", "raw_fields")
    sample = completeness_sample(conn, data_source_id, columns, sample_limit=sample_limit)
    results: list[CheckResult] = []
    for col, (nulls, total) in sample.items():
        rate = nulls / total if total > 0 else 0.0
        status: str = "pass" if rate <= null_rate_threshold else "fail"
        if 0 < rate <= null_rate_threshold:
            status = "warn"
        results.append(
            CheckResult(
                name=f"completeness_{col}",
                status=status,  # type: ignore[arg-type]
                message=f"{data_source_name}: {col} null rate {rate:.4f} ({nulls}/{total})",
                metric_name=f"null_rate_{col}",
                metric_value=rate,
                threshold=null_rate_threshold,
                details={"column": col, "null_count": nulls, "sample_size": total},
            )
        )
    return results
