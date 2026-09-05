from __future__ import annotations

import argparse
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Callable

import psycopg

from core.db import get_connection

from .download import (
    WA_PAGE_ROWS,
    download_wa_csv,
    download_wa_csv_page,
    fetch_wa_source_change_count,
    fetch_wa_source_snapshot,
)
from .load import (
    LoadResult,
    count_active_wa_source_records,
    filter_wa_contribution_page_changes,
    load_wa_contributions_with_filings,
    load_wa_expenditures_with_filings,
    load_wa_independent_expenditures_with_filings,
    load_wa_loans_with_filings,
    select_wa_contributions_refresh_baseline,
)
from .parse import parse_contributions, parse_expenditures, parse_independent_expenditures, parse_loans

_SUPPORTED_DATA_TYPES = ("contributions", "expenditures", "independent_expenditures", "loans")
_CONTRIBUTIONS_BUDGET_SECONDS = 25 * 60
_CONTRIBUTIONS_CURSOR_OVERLAP = timedelta(days=1)


class WAContributionsIncompleteError(RuntimeError):
    """A bounded pass persisted safe progress but did not prove complete freshness."""


@dataclass(slots=True)
class WACompleteContributionsResult(LoadResult):
    source_complete: bool
    source_row_count: int


def _empty_complete_result(
    *, started_at: float, monotonic: Callable[[], float], row_count: int
) -> WACompleteContributionsResult:
    return WACompleteContributionsResult(
        inserted=0,
        skipped=0,
        quarantined=0,
        superseded=0,
        errors=0,
        elapsed_seconds=monotonic() - started_at,
        source_complete=True,
        source_row_count=row_count,
    )


def _run_complete_contributions_refresh(
    connection: psycopg.Connection,
    download_dir: Path,
    *,
    monotonic: Callable[[], float] = time.monotonic,
    budget_seconds: float = _CONTRIBUTIONS_BUDGET_SECONDS,
) -> WACompleteContributionsResult:
    """Load a stable Socrata delta and refuse freshness without exact count proof.

    A complete existing source scans only rows changed inside a one-day overlap. An
    incomplete source takes bounded full-source pages. Each existing WA loader page owns
    its commit boundary, so interruption leaves deduplicated progress that a later pass
    can safely revisit; only the final stable snapshot/count equality returns success.
    """
    if budget_seconds <= 0:
        raise ValueError("WA contributions budget_seconds must be positive")
    started_at = monotonic()
    baseline = select_wa_contributions_refresh_baseline(connection)
    connection.commit()
    source_snapshot = fetch_wa_source_snapshot("contributions")
    updated_after = None
    if baseline.active_source_records == source_snapshot.row_count and baseline.last_pull_at is not None:
        updated_after = baseline.last_pull_at - _CONTRIBUTIONS_CURSOR_OVERLAP
    rows_to_download = fetch_wa_source_change_count(
        "contributions",
        updated_after=updated_after,
        updated_through=source_snapshot.max_updated_at,
    )
    totals = _empty_complete_result(
        started_at=started_at, monotonic=lambda: started_at, row_count=source_snapshot.row_count
    )

    for offset in range(0, rows_to_download, WA_PAGE_ROWS):
        if monotonic() - started_at >= budget_seconds:
            raise WAContributionsIncompleteError(
                f"WA contributions bounded pass stopped before offset {offset}; committed pages are safe to resume"
            )
        page_rows = min(WA_PAGE_ROWS, rows_to_download - offset)
        page_path = download_wa_csv_page(
            "contributions",
            download_dir,
            offset=offset,
            limit=page_rows,
            updated_after=updated_after,
            updated_through=source_snapshot.max_updated_at,
        )
        page_changes = filter_wa_contribution_page_changes(
            connection,
            page_path,
            download_dir / f"wa_contributions_changed_offset_{offset}.csv",
        )
        connection.commit()
        if page_changes.source_rows != page_rows:
            raise WAContributionsIncompleteError(
                f"WA contributions page at offset {offset} returned {page_changes.source_rows} of {page_rows} rows"
            )
        if page_changes.path is None:
            continue
        page_result = load_wa_contributions_with_filings(connection, page_changes.path, limit=None)
        totals.inserted += page_result.inserted
        totals.skipped += page_result.skipped
        totals.quarantined += page_result.quarantined
        totals.superseded += page_result.superseded
        totals.errors += page_result.errors
        if offset + page_rows < rows_to_download and monotonic() - started_at >= budget_seconds:
            raise WAContributionsIncompleteError(
                f"WA contributions bounded pass stopped after offset {offset}; committed pages are safe to resume"
            )

    active_source_records = count_active_wa_source_records(connection, data_type="contributions")
    verification_snapshot = fetch_wa_source_snapshot("contributions")
    if verification_snapshot != source_snapshot:
        raise WAContributionsIncompleteError(
            "WA contributions source changed during the bounded snapshot; resume required"
        )
    if active_source_records != source_snapshot.row_count:
        raise WAContributionsIncompleteError(
            "WA contributions active source count does not match the complete Socrata snapshot; resume required"
        )
    totals.elapsed_seconds = monotonic() - started_at
    return totals


def _non_negative_int(raw_value: str) -> int:
    value = int(raw_value)
    if value < 0:
        raise argparse.ArgumentTypeError("--limit must be greater than or equal to 0")
    return value


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load Washington campaign-finance CSV data into Civibus")
    input_source_group = parser.add_mutually_exclusive_group(required=True)
    input_source_group.add_argument("--path", type=Path, help="Path to a local WA CSV export")
    input_source_group.add_argument(
        "--download",
        action="store_true",
        help="Download current WA CSV export for the selected data type",
    )
    parser.add_argument(
        "--data-type",
        required=True,
        choices=list(_SUPPORTED_DATA_TYPES),
        help="WA data type to ingest",
    )
    parser.add_argument("--limit", type=_non_negative_int, help="Optional maximum rows to load")
    parser.add_argument("--dry-run", action="store_true", help="Parse and report row count without writing to DB")
    return parser


def _validate_data_type(data_type: str) -> str:
    if data_type not in _SUPPORTED_DATA_TYPES:
        raise ValueError(f"Unsupported WA data type: {data_type}")
    return data_type


def _print_load_summary(result: LoadResult, data_type: str) -> None:
    print(
        f"WA {data_type} load complete: "
        f"inserted={result.inserted} "
        f"skipped={result.skipped} "
        f"quarantined={result.quarantined} "
        f"superseded={result.superseded} "
        f"errors={result.errors} "
        f"elapsed_seconds={result.elapsed_seconds:.2f}"
    )


def _print_dry_run_summary(data_type: str, parsed_count: int) -> None:
    print(f"WA {data_type} dry-run: parsed {parsed_count} rows")


def _resolve_input_path(args: argparse.Namespace) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    if args.path is not None:
        return args.path, None

    temp_dir = tempfile.TemporaryDirectory(prefix=f"wa-{args.data_type}-")
    try:
        download_path = download_wa_csv(args.data_type, dest_dir=Path(temp_dir.name), limit=args.limit)
        return download_path, temp_dir
    except Exception:
        temp_dir.cleanup()
        raise


def _count_rows(path: Path, *, data_type: str, limit: int | None) -> int:
    normalized_data_type = _validate_data_type(data_type)
    parser = {
        "contributions": parse_contributions,
        "expenditures": parse_expenditures,
        "independent_expenditures": parse_independent_expenditures,
        "loans": parse_loans,
    }[normalized_data_type](path)
    if limit is None:
        return sum(1 for _row in parser)
    return sum(1 for _row in zip(range(limit), parser))


def _load_path(
    connection: psycopg.Connection,
    input_path: Path,
    *,
    data_type: str,
    limit: int | None,
) -> LoadResult:
    normalized_data_type = _validate_data_type(data_type)
    loader = {
        "contributions": load_wa_contributions_with_filings,
        "expenditures": load_wa_expenditures_with_filings,
        "independent_expenditures": load_wa_independent_expenditures_with_filings,
        "loans": load_wa_loans_with_filings,
    }[normalized_data_type]
    return loader(connection, input_path, limit=limit)


def run_wa_refresh(
    *,
    data_type: str,
    path: Path | None = None,
    download: bool = False,
    limit: int | None = None,
) -> LoadResult:
    _validate_data_type(data_type)
    if path is None and not download:
        raise ValueError("WA refresh requires either path or download mode")
    if path is not None and download:
        raise ValueError("WA refresh accepts path or download mode, not both")

    args = argparse.Namespace(path=path, download=download, data_type=data_type, limit=limit, dry_run=False)
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    connection: psycopg.Connection | None = None
    try:
        if data_type == "contributions" and download and limit is None:
            temp_dir = tempfile.TemporaryDirectory(prefix="wa-contributions-")
            connection = get_connection()
            load_result = _run_complete_contributions_refresh(connection, Path(temp_dir.name))
            connection.commit()
            return load_result
        input_path, temp_dir = _resolve_input_path(args)
        connection = get_connection()
        load_result = _load_path(connection, input_path, data_type=data_type, limit=limit)
        connection.commit()
        return load_result
    finally:
        if connection is not None:
            connection.close()
        if temp_dir is not None:
            temp_dir.cleanup()


def run_wa_officeholder_refresh(
    *,
    rows: list[dict[str, str | None]],
) -> tuple[int, int, int]:
    """Load pre-parsed WA officeholder directory rows into the DB.

    Returns (inserted, skipped, errors) counts.
    """
    from core.types.python.models import DataSource
    from domains.campaign_finance.jurisdictions.states.load_utils import ensure_data_source

    from .wa_officeholder_loader import load_wa_officeholders

    connection = get_connection()
    try:
        ds_id = ensure_data_source(
            connection,
            DataSource(
                domain="campaign_finance",
                jurisdiction="state/WA/officeholder",
                name="WA Officeholder Directory",
                source_url="https://leg.wa.gov/legislature/pages/memberinformation.aspx",
            ),
        )
        connection.commit()
        result = load_wa_officeholders(connection, rows, data_source_id=ds_id)
        connection.commit()
        return result.inserted, result.skipped, result.errors
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)

    try:
        if args.dry_run:
            input_path, temp_dir = _resolve_input_path(args)
            _print_dry_run_summary(
                args.data_type,
                _count_rows(input_path, data_type=args.data_type, limit=args.limit),
            )
            if temp_dir is not None:
                temp_dir.cleanup()
            return 0

        load_result = run_wa_refresh(
            data_type=args.data_type,
            path=args.path,
            download=args.download,
            limit=args.limit,
        )
    except Exception as error:  # noqa: BLE001
        print(f"WA ingest failed: {error}", file=sys.stderr)
        return 1

    _print_load_summary(load_result, args.data_type)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
