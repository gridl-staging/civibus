
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Iterable

import psycopg

from core.db import get_connection

from .checks import (
    check_amount_sanity,
    check_date_range,
    check_duplicate_records,
    check_graph_edge_presence,
    check_null_rate,
)
from .freshness import run_freshness_checks
from .models import CheckResult, JurisdictionSummary, QualityReport
from .reconciliation import (
    check_key_field_completeness,
    check_record_count_reconciliation,
    count_source_records,
    fetch_data_source_metadata,
    list_data_source_jurisdictions,
    resolve_data_source_ids,
)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run campaign finance data quality checks",
    )
    parser.add_argument(
        "--jurisdiction",
        help="Filter to a specific jurisdiction (e.g. federal/fec, state/CO)",
    )
    parser.add_argument(
        "--check",
        help=(
            "Run only a specific check by name "
            "(e.g. record_count, null_rate, duplicates, amount, date_range, completeness, graph_edges)"
        ),
    )
    parser.add_argument(
        "--artifact-path",
        help="Optional JSON artifact path for saving the emitted report alongside stdout output.",
    )
    return parser


# ---------------------------------------------------------------------------
# Jurisdiction discovery and check execution
# ---------------------------------------------------------------------------

_CAMPAIGN_FINANCE_DOMAIN = "campaign_finance"
_VALID_CHECKS = frozenset(
    {
        "record_count",
        "completeness",
        "null_rate",
        "duplicates",
        "amount",
        "date_range",
        "graph_edges",
        "freshness",
    }
)


def _validate_cli_arguments(args: argparse.Namespace) -> None:
    """Reject unsupported filters before attempting a database connection."""
    if args.check is not None and args.check not in _VALID_CHECKS:
        valid_checks = ", ".join(sorted(_VALID_CHECKS))
        raise ValueError(f"Unsupported --check value {args.check!r}; expected one of: {valid_checks}")


def _run_checks_for_data_source(
    conn: psycopg.Connection,
    data_source_id: str,
    data_source_name: str,
    check_filter: str | None,
) -> list[CheckResult]:
    """Run selected checks against a single data source."""
    from uuid import UUID

    ds_id = UUID(data_source_id)
    results: list[CheckResult] = []

    if check_filter is None or check_filter == "record_count":
        results.append(check_record_count_reconciliation(conn, ds_id, data_source_name))

    if check_filter is None or check_filter == "completeness":
        results.extend(check_key_field_completeness(conn, ds_id, data_source_name))

    if check_filter is None or check_filter == "null_rate":
        for col in ("source_record_key", "source_url"):
            results.append(check_null_rate(conn, ds_id, data_source_name, col))

    if check_filter is None or check_filter == "duplicates":
        results.append(check_duplicate_records(conn, ds_id, data_source_name))

    if check_filter is None or check_filter == "amount":
        results.append(check_amount_sanity(conn, ds_id, data_source_name))

    if check_filter is None or check_filter == "date_range":
        results.append(check_date_range(conn, ds_id, data_source_name))

    if check_filter is None or check_filter == "graph_edges":
        results.append(check_graph_edge_presence(conn, ds_id, data_source_name))

    return results


def _discover_and_run(
    conn: psycopg.Connection,
    jurisdiction_filter: str | None,
    check_filter: str | None,
) -> QualityReport:
    """Discover data sources and run checks, building a QualityReport."""
    summaries: list[JurisdictionSummary] = []
    jurisdictions = list_data_source_jurisdictions(conn, domain=_CAMPAIGN_FINANCE_DOMAIN)

    if jurisdiction_filter is not None:
        jurisdictions = [jurisdiction for jurisdiction in jurisdictions if jurisdiction == jurisdiction_filter]

    for jurisdiction in jurisdictions:
        ds_ids = resolve_data_source_ids(conn, domain=_CAMPAIGN_FINANCE_DOMAIN, jurisdiction=jurisdiction)
        if not ds_ids:
            continue

        all_results: list[CheckResult] = []
        baseline_urls: list[str] = []
        total_records = 0
        for ds_id in ds_ids:
            ds_name, source_url = fetch_data_source_metadata(conn, ds_id)
            if source_url is not None and source_url not in baseline_urls:
                baseline_urls.append(source_url)

            total_records += count_source_records(conn, ds_id)
            all_results.extend(_run_checks_for_data_source(conn, str(ds_id), ds_name, check_filter))

        summaries.append(
            JurisdictionSummary(
                jurisdiction=jurisdiction,
                data_source_ids=[str(i) for i in ds_ids],
                baseline_urls=baseline_urls,
                record_count=total_records,
                check_results=all_results,
            )
        )

    return QualityReport(
        jurisdiction_filter=jurisdiction_filter,
        check_filter=check_filter,
        summaries=summaries,
    )


def _dedupe_strings(values: Iterable[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _merge_summaries_by_jurisdiction(
    base_summaries: list[JurisdictionSummary],
    extra_summaries: list[JurisdictionSummary],
) -> list[JurisdictionSummary]:
    merged_by_jurisdiction: dict[str, JurisdictionSummary] = {}
    merged_order: list[str] = []

    for summary in (*base_summaries, *extra_summaries):
        existing = merged_by_jurisdiction.get(summary.jurisdiction)
        if existing is None:
            merged_by_jurisdiction[summary.jurisdiction] = summary.model_copy(deep=True)
            merged_order.append(summary.jurisdiction)
            continue

        existing.data_source_ids = _dedupe_strings((*existing.data_source_ids, *summary.data_source_ids))
        existing.baseline_urls = _dedupe_strings((*existing.baseline_urls, *summary.baseline_urls))
        existing.record_count += summary.record_count
        existing.check_results.extend(summary.check_results)

    return [merged_by_jurisdiction[jurisdiction] for jurisdiction in merged_order]


def _write_report_artifact(report: QualityReport, artifact_path: str | Path) -> None:
    """Persist the same deterministic JSON emitted to stdout for later doc evidence.

    Freshness work in this repo tends to become stale when evidence only exists in
    terminal scrollback. Writing the exact CLI payload to disk keeps the artifact
    machine-readable and prevents a second serialization format from drifting.
    """
    destination = Path(artifact_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f"{report.to_json()}\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = build_argument_parser()
    try:
        args = parser.parse_args(argv)
        _validate_cli_arguments(args)
    except SystemExit as error:
        return int(error.code)
    except ValueError as error:
        print(f"CLI validation failed: {error}", file=sys.stderr)
        return 2

    connection: psycopg.Connection | None = None
    try:
        if args.check == "freshness":
            summaries = run_freshness_checks(args.jurisdiction)
            report = QualityReport(
                jurisdiction_filter=args.jurisdiction,
                check_filter=args.check,
                summaries=summaries,
            )
        elif args.check is None:
            connection = get_connection()
            db_report = _discover_and_run(connection, args.jurisdiction, args.check)
            freshness_summaries = run_freshness_checks(args.jurisdiction)
            merged_summaries = _merge_summaries_by_jurisdiction(db_report.summaries, freshness_summaries)
            report = QualityReport(
                jurisdiction_filter=args.jurisdiction,
                check_filter=args.check,
                summaries=merged_summaries,
            )
        else:
            connection = get_connection()
            report = _discover_and_run(connection, args.jurisdiction, args.check)
    except Exception as error:  # noqa: BLE001
        print(f"Quality check failed: {error}", file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            connection.close()

    report_json = report.to_json()

    if args.artifact_path:
        try:
            _write_report_artifact(report, args.artifact_path)
        except OSError as error:
            print(report_json)
            print(f"Failed to write report artifact: {error}", file=sys.stderr)
            return 1

    print(report_json)

    if report.status in ("fail", "error"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
