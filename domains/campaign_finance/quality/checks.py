"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/mar22_pm_01_seo_landing_pages_and_slug_routing/civibus_dev/domains/campaign_finance/quality/checks.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import psycopg

from .models import CheckResult
from .reconciliation import (
    count_graph_edges_by_family,
    count_source_records,
    duplicate_hashes,
    expected_edge_denominators,
    null_rate,
    pull_date_range,
    raw_field_null_rate,
    source_record_scope_where,
)

# ---------------------------------------------------------------------------
# Threshold defaults — overridable via CLI args
# ---------------------------------------------------------------------------

DEFAULT_NULL_RATE_THRESHOLD = 0.05
DEFAULT_DUPLICATE_FAIL_THRESHOLD = 10
_NUMERIC_TEXT_PATTERN = r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$"


def _normalize_pull_datetime(value: object) -> datetime | None:
    """Normalize DB pull_date values to aware datetimes for comparison."""
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _null_rate_status(rate: float, total: int, threshold: float) -> str:
    """Derive pass/warn/fail from a null rate and threshold."""
    if rate == 0.0 and total > 0:
        return "pass"
    if rate <= threshold:
        return "warn" if rate > 0 else "pass"
    return "fail"


def check_null_rate(
    conn: psycopg.Connection,
    data_source_id: UUID,
    data_source_name: str,
    column: str,
    *,
    threshold: float = DEFAULT_NULL_RATE_THRESHOLD,
) -> CheckResult:
    nulls, total = null_rate(conn, data_source_id, column)
    rate = nulls / total if total > 0 else 0.0
    status = _null_rate_status(rate, total, threshold)

    return CheckResult(
        name=f"null_rate_{column}",
        status=status,  # type: ignore[arg-type]
        message=f"{data_source_name}: {column} null rate {rate:.4f} ({nulls}/{total})",
        metric_name=f"null_rate_{column}",
        metric_value=rate,
        threshold=threshold,
        details={"column": column, "null_count": nulls, "total_count": total},
    )


def check_duplicate_records(
    conn: psycopg.Connection,
    data_source_id: UUID,
    data_source_name: str,
    *,
    fail_threshold: int = DEFAULT_DUPLICATE_FAIL_THRESHOLD,
    source_key_prefix: str | None = None,
    check_name: str | None = None,
) -> CheckResult:
    dupes = duplicate_hashes(conn, data_source_id, limit=None, source_key_prefix=source_key_prefix)
    total_dupes = sum(count - 1 for _, count in dupes)

    if total_dupes == 0:
        status = "pass"
    elif total_dupes <= fail_threshold:
        status = "warn"
    else:
        status = "fail"

    return CheckResult(
        name=check_name or "duplicate_records",
        status=status,  # type: ignore[arg-type]
        message=f"{data_source_name}: {total_dupes} duplicate records across {len(dupes)} hash groups",
        metric_name="duplicate_record_count",
        metric_value=float(total_dupes),
        threshold=float(fail_threshold),
        details={
            "duplicate_hash_groups": len(dupes),
            "total_extra_records": total_dupes,
            "top_duplicates": [{"hash": h, "count": c} for h, c in dupes[:5]],
        },
    )


def check_amount_sanity(
    conn: psycopg.Connection,
    data_source_id: UUID,
    data_source_name: str,
    *,
    amount_field: str = "transaction_amt",
    min_valid: float = -1_000_000_000,
    max_valid: float = 1_000_000_000,
) -> CheckResult:
    """Check that amounts in raw_fields are within sane bounds.

    Sources amounts from raw_fields JSONB only (cf.transaction is out of scope).
    """
    where = source_record_scope_where(active_only=True)
    sql = (
        "SELECT "
        "  COUNT(*) FILTER (WHERE amount_present AND (amount_numeric IS NULL OR amount_numeric < %s OR amount_numeric > %s)), "
        "  COUNT(*) FILTER (WHERE amount_present AND amount_numeric IS NULL), "
        "  COUNT(*) FILTER (WHERE amount_present), "
        "  COUNT(*) "
        "FROM ("
        "  SELECT "
        "    sr.raw_fields ? %s AS amount_present, "
        "    CASE "
        "      WHEN sr.raw_fields ? %s AND btrim(sr.raw_fields->>%s) ~ %s "
        "      THEN (btrim(sr.raw_fields->>%s))::numeric "
        "      ELSE NULL "
        "    END AS amount_numeric "
        "  FROM core.source_record sr "
        f"  WHERE {where}"
        ") AS sampled_amounts"
    )
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                min_valid,
                max_valid,
                amount_field,
                amount_field,
                amount_field,
                _NUMERIC_TEXT_PATTERN,
                amount_field,
                data_source_id,
            ),
        )
        row = cur.fetchone()

    if row is None or row[3] == 0:
        return CheckResult(
            name="amount_sanity",
            status="pass",
            message=f"{data_source_name}: no records to check",
            metric_name="outlier_count",
            metric_value=0.0,
            details={"amount_field": amount_field, "total_records": 0},
        )

    outliers, invalid_amounts, with_field, total = row[0] or 0, row[1] or 0, row[2] or 0, row[3]

    if with_field == 0:
        return CheckResult(
            name="amount_sanity",
            status="pass",
            message=f"{data_source_name}: no records contain {amount_field}",
            metric_name="outlier_count",
            metric_value=0.0,
            details={"amount_field": amount_field, "records_with_field": 0, "total_records": total},
        )

    status = "pass" if outliers == 0 else "fail"

    return CheckResult(
        name="amount_sanity",
        status=status,  # type: ignore[arg-type]
        message=f"{data_source_name}: {outliers}/{with_field} amounts outside [{min_valid}, {max_valid}]",
        metric_name="outlier_count",
        metric_value=float(outliers),
        details={
            "amount_field": amount_field,
            "outlier_count": outliers,
            "invalid_amount_count": invalid_amounts,
            "records_with_field": with_field,
            "total_records": total,
            "min_valid": min_valid,
            "max_valid": max_valid,
        },
    )


def check_source_count(
    conn: psycopg.Connection,
    data_source_id: UUID,
    data_source_name: str,
    *,
    min_expected: int = 1,
    source_key_prefix: str | None = None,
    check_name: str | None = None,
) -> CheckResult:
    """Check that at least min_expected source records exist.

    When source_key_prefix is set, only records whose source_record_key
    starts with that prefix are counted.
    """
    count = count_source_records(conn, data_source_id, source_key_prefix=source_key_prefix)
    status = "pass" if count >= min_expected else "fail"

    return CheckResult(
        name=check_name or "source_count",
        status=status,  # type: ignore[arg-type]
        message=f"{data_source_name}: {count} source records (min {min_expected})",
        metric_name="source_record_count",
        metric_value=float(count),
        threshold=float(min_expected),
        details={"count": count, "min_expected": min_expected},
    )


def check_graph_edge_presence(
    conn: psycopg.Connection,
    data_source_id: UUID,
    data_source_name: str,
    *,
    threshold: float = 0.95,
) -> CheckResult:
    """Check graph edge population ratios against expected denominators."""
    expected_counts = expected_edge_denominators(conn, data_source_id)
    actual_counts = count_graph_edges_by_family(conn, data_source_id)

    family_details: dict[str, dict[str, float | int]] = {}
    min_ratio = 1.0
    for family, expected in expected_counts.items():
        actual = actual_counts.get(family, 0)
        ratio = 1.0 if expected == 0 else actual / expected
        family_details[family] = {"expected": expected, "actual": actual, "ratio": ratio}
        min_ratio = min(min_ratio, ratio)

    status = "pass" if min_ratio >= threshold else "fail"
    return CheckResult(
        name="graph_edge_presence",
        status=status,  # type: ignore[arg-type]
        message=(
            f"{data_source_name}: minimum edge population ratio {min_ratio:.4f} across {len(family_details)} families"
        ),
        metric_name="edge_population_ratio",
        metric_value=min_ratio,
        threshold=threshold,
        details={"edge_families": family_details},
    )


def check_raw_field_null_rate(
    conn: psycopg.Connection,
    data_source_id: UUID,
    data_source_name: str,
    field_name: str,
    *,
    threshold: float = DEFAULT_NULL_RATE_THRESHOLD,
    source_key_prefix: str | None = None,
    check_name: str | None = None,
) -> CheckResult:
    nulls, total = raw_field_null_rate(
        conn,
        data_source_id,
        field_name,
        source_key_prefix=source_key_prefix,
    )
    rate = nulls / total if total > 0 else 0.0
    status = _null_rate_status(rate, total, threshold)

    name = check_name or f"null_rate_{field_name}"
    return CheckResult(
        name=name,
        status=status,  # type: ignore[arg-type]
        message=f"{data_source_name}: {field_name} null rate {rate:.4f} ({nulls}/{total})",
        metric_name=f"null_rate_{field_name}",
        metric_value=rate,
        threshold=threshold,
        details={"field_name": field_name, "null_count": nulls, "total_count": total},
    )


def check_date_range(
    conn: psycopg.Connection,
    data_source_id: UUID,
    data_source_name: str,
) -> CheckResult:
    """Check that pull dates span a reasonable range and are not in the future."""
    min_date, max_date = pull_date_range(conn, data_source_id)

    if min_date is None or max_date is None:
        return CheckResult(
            name="date_range",
            status="warn",
            message=f"{data_source_name}: no pull dates found",
            metric_name="date_range_days",
            metric_value=None,
            details={"min_pull_date": None, "max_pull_date": None},
        )

    normalized_min_date = _normalize_pull_datetime(min_date)
    normalized_max_date = _normalize_pull_datetime(max_date)
    now = datetime.now(timezone.utc)
    future_records = normalized_max_date > now if normalized_max_date is not None else False
    range_days = None
    if normalized_min_date is not None and normalized_max_date is not None:
        range_days = (normalized_max_date - normalized_min_date).total_seconds() / 86_400

    if future_records:
        status = "warn"
        msg = f"{data_source_name}: max pull_date {max_date} is in the future"
    else:
        status = "pass"
        msg = f"{data_source_name}: pull_date range {min_date} to {max_date}"

    return CheckResult(
        name="date_range",
        status=status,  # type: ignore[arg-type]
        message=msg,
        metric_name="date_range_days",
        metric_value=range_days,
        details={
            "min_pull_date": str(min_date),
            "max_pull_date": str(max_date),
            "future_records": future_records,
        },
    )
