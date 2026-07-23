"""Populate stored committee-detail top lists without re-ingesting FEC files."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import psycopg
from pydantic import BaseModel

from core.db import get_connection
from core.refresh.job_builders import populate_committee_summary_derived_aggregates

_PROGRESS_SOURCE = "committee_top_list_backfill"


class CommitteeTopListBackfillResult(BaseModel):
    rows_updated: int
    elapsed_seconds: float
    cycles: tuple[int, ...]
    committee_ids: tuple[str, ...] | None


def _non_negative_int_for(option_name: str) -> Callable[[str], int]:
    def _parse(raw_value: str) -> int:
        try:
            value = int(raw_value)
        except ValueError as error:
            raise argparse.ArgumentTypeError(f"{option_name} must be an integer") from error
        if value < 0:
            raise argparse.ArgumentTypeError(f"{option_name} must be greater than or equal to 0")
        return value

    return _parse


def _non_negative_int(raw_value: str) -> int:
    return _non_negative_int_for("--limit")(raw_value)


def _committee_uuid(raw_value: str) -> str:
    try:
        return str(UUID(raw_value))
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"invalid committee UUID: {raw_value}") from error


def _normalize_committee_ids(committee_ids: tuple[str, ...]) -> tuple[str, ...]:
    normalized_committee_ids: list[str] = []
    seen_committee_ids: set[str] = set()
    for raw_committee_id in committee_ids:
        committee_id = _committee_uuid(raw_committee_id)
        if committee_id not in seen_committee_ids:
            normalized_committee_ids.append(committee_id)
            seen_committee_ids.add(committee_id)
    return tuple(normalized_committee_ids)


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Populate cf.committee_summary committee-detail top-list JSONB columns"
    )
    parser.add_argument(
        "--cycles",
        type=int,
        nargs="+",
        required=True,
        help="FEC cycles to populate, for example: --cycles 2026",
    )
    parser.add_argument(
        "--committee-id",
        action="append",
        default=None,
        type=_committee_uuid,
        help="Committee UUID to populate. Repeat to populate more than one committee.",
    )
    parser.add_argument(
        "--limit",
        type=_non_negative_int,
        default=None,
        help="Populate only the first N committee_summary rows for the selected cycles.",
    )
    parser.add_argument(
        "--max-committee-size",
        type=_non_negative_int_for("--max-committee-size"),
        default=None,
        help="Only implicitly select committees with no more than N all-time filings.",
    )
    parser.add_argument(
        "--progress-file",
        type=Path,
        default=None,
        help="Append JSONL progress and skip committee IDs already recorded there.",
    )
    return parser


def _select_limited_committee_ids(
    connection: psycopg.Connection,
    *,
    cycles: tuple[int, ...],
    limit: int | None,
    max_committee_size: int | None = None,
    exclude_committee_ids: tuple[str, ...] = (),
) -> tuple[str, ...]:
    if limit == 0:
        return ()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            WITH residual_committees AS (
                SELECT DISTINCT cs.committee_id
                FROM cf.committee_summary cs
                WHERE cs.cycle = ANY(%s)
                  AND cs.committee_id <> ALL(%s::uuid[])
                  AND (
                      cs.derived_top_donors IS NULL
                      OR cs.derived_top_vendors IS NULL
                      OR cs.derived_spend_categories IS NULL
                      OR cs.derived_filing_breakdown IS NULL
                  )
            ),
            filing_counts AS (
                SELECT f.committee_id, COUNT(*)::integer AS filing_count
                FROM cf.filing f
                JOIN residual_committees rc
                  ON rc.committee_id = f.committee_id
                GROUP BY f.committee_id
            )
            SELECT rc.committee_id::text
            FROM residual_committees rc
            LEFT JOIN filing_counts fc
              ON fc.committee_id = rc.committee_id
            WHERE (%s::integer IS NULL OR COALESCE(fc.filing_count, 0) <= %s)
            ORDER BY COALESCE(fc.filing_count, 0) ASC, rc.committee_id ASC
            LIMIT %s
            """,
            (
                list(cycles),
                list(exclude_committee_ids),
                max_committee_size,
                max_committee_size,
                limit,
            ),
        )
        return tuple(row[0] for row in cursor.fetchall())


def _resolve_committee_scope(
    connection: psycopg.Connection,
    *,
    cycles: tuple[int, ...],
    committee_ids: tuple[str, ...] | None,
    limit: int | None,
    max_committee_size: int | None = None,
    exclude_committee_ids: tuple[str, ...] = (),
) -> tuple[str, ...]:
    if committee_ids is not None:
        normalized_committee_ids = _normalize_committee_ids(committee_ids)
        return normalized_committee_ids[:limit] if limit is not None else normalized_committee_ids
    return _select_limited_committee_ids(
        connection,
        cycles=cycles,
        limit=limit,
        max_committee_size=max_committee_size,
        exclude_committee_ids=exclude_committee_ids,
    )


def backfill_committee_top_lists(
    connection: psycopg.Connection,
    *,
    cycles: tuple[int, ...],
    committee_ids: tuple[str, ...] | None = None,
    limit: int | None = None,
    max_committee_size: int | None = None,
) -> CommitteeTopListBackfillResult:
    scoped_committee_ids = _resolve_committee_scope(
        connection,
        cycles=cycles,
        committee_ids=committee_ids,
        limit=limit,
        max_committee_size=max_committee_size,
    )
    started_at = time.perf_counter()
    if committee_ids is None:
        rows_updated = sum(
            populate_committee_summary_derived_aggregates(
                connection,
                cycles=cycles,
                committee_ids=(committee_id,),
            )
            for committee_id in scoped_committee_ids
        )
    else:
        rows_updated = populate_committee_summary_derived_aggregates(
            connection,
            cycles=cycles,
            committee_ids=scoped_committee_ids,
        )
    elapsed_seconds = time.perf_counter() - started_at
    return CommitteeTopListBackfillResult(
        rows_updated=rows_updated,
        elapsed_seconds=elapsed_seconds,
        cycles=cycles,
        committee_ids=scoped_committee_ids,
    )


def _normalize_cycle_scope(cycles: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(sorted(set(cycles)))


def _progress_detail_matches_cycles(detail: object, expected_cycles: tuple[int, ...]) -> bool:
    if not isinstance(detail, dict):
        return False
    cycles = detail.get("cycles")
    if not isinstance(cycles, list) or not all(isinstance(value, int) for value in cycles):
        return False
    return _normalize_cycle_scope(tuple(cycles)) == expected_cycles


def _progress_committee_ids(detail: object) -> tuple[str, ...] | None:
    if not isinstance(detail, dict):
        return None
    committee_ids = detail.get("committee_ids")
    if not isinstance(committee_ids, list):
        return None
    normalized_committee_ids: list[str] = []
    for committee_id in committee_ids:
        if not isinstance(committee_id, str):
            return None
        try:
            normalized_committee_ids.append(str(UUID(committee_id)))
        except ValueError:
            return None
    return tuple(normalized_committee_ids)


def _progress_rows_total(record: dict[str, object]) -> int | None:
    rows_total = record.get("rows_total")
    rows_delta = record.get("rows_delta")
    if type(rows_total) is not int or type(rows_delta) is not int:
        return None
    if rows_total < 1 or rows_delta != 1:
        return None
    return rows_total


def _read_progress(progress_file: Path | None, *, cycles: tuple[int, ...]) -> tuple[set[str], int]:
    if progress_file is None or not progress_file.exists():
        return set(), 0
    expected_cycles = _normalize_cycle_scope(cycles)
    completed_committee_ids: set[str] = set()
    rows_total = 0
    for line in progress_file.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        if record.get("source") != _PROGRESS_SOURCE:
            continue
        detail = record.get("detail")
        if not _progress_detail_matches_cycles(detail, expected_cycles):
            continue
        committee_ids = _progress_committee_ids(detail)
        if committee_ids is None or len(committee_ids) != 1:
            continue
        record_rows_total = _progress_rows_total(record)
        if record_rows_total is None:
            continue
        completed_committee_ids.update(committee_ids)
        rows_total = max(rows_total, record_rows_total)
    return completed_committee_ids, rows_total


def _append_progress(
    progress_file: Path | None, *, rows_total: int, committee_id: str, cycles: tuple[int, ...]
) -> None:
    if progress_file is None:
        return
    progress_file.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "source": _PROGRESS_SOURCE,
        "rows_total": rows_total,
        "rows_delta": 1,
        "detail": {"committee_ids": [committee_id], "cycles": list(_normalize_cycle_scope(cycles))},
    }
    with progress_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, separators=(",", ":")) + "\n")


def _run_implicit_committee_backfill(
    connection: psycopg.Connection,
    *,
    cycles: tuple[int, ...],
    limit: int | None,
    max_committee_size: int | None,
    progress_file: Path | None,
) -> CommitteeTopListBackfillResult:
    completed_committee_ids, rows_total = _read_progress(progress_file, cycles=cycles)
    scoped_committee_ids = _select_limited_committee_ids(
        connection,
        cycles=cycles,
        limit=limit,
        max_committee_size=max_committee_size,
        exclude_committee_ids=tuple(sorted(completed_committee_ids)),
    )
    started_at = time.perf_counter()
    rows_updated = 0
    processed_committee_ids: list[str] = []
    try:
        for committee_id in scoped_committee_ids:
            try:
                rows_updated += populate_committee_summary_derived_aggregates(
                    connection,
                    cycles=cycles,
                    committee_ids=(committee_id,),
                )
            except Exception:
                connection.rollback()
                raise
            connection.commit()
            processed_committee_ids.append(committee_id)
            rows_total += 1
            _append_progress(progress_file, rows_total=rows_total, committee_id=committee_id, cycles=cycles)
    finally:
        elapsed_seconds = time.perf_counter() - started_at
    return CommitteeTopListBackfillResult(
        rows_updated=rows_updated,
        elapsed_seconds=elapsed_seconds,
        cycles=cycles,
        committee_ids=tuple(processed_committee_ids),
    )


def _uses_implicit_committee_batches(args: argparse.Namespace) -> bool:
    return args.committee_id is None


def main(argv: list[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)
    cycles = tuple(args.cycles)
    committee_ids = None if args.committee_id is None else tuple(args.committee_id)
    connection = get_connection()
    try:
        if _uses_implicit_committee_batches(args):
            result = _run_implicit_committee_backfill(
                connection,
                cycles=cycles,
                limit=args.limit,
                max_committee_size=args.max_committee_size,
                progress_file=args.progress_file,
            )
        else:
            with connection.transaction():
                result = backfill_committee_top_lists(
                    connection,
                    cycles=cycles,
                    committee_ids=committee_ids,
                    limit=args.limit,
                    max_committee_size=args.max_committee_size,
                )
    finally:
        connection.close()

    print(json.dumps(result.model_dump(mode="json"), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
