"""Populate stored committee-detail top lists without re-ingesting FEC files."""

from __future__ import annotations

import argparse
import json
import sys
import time
from uuid import UUID

import psycopg
from pydantic import BaseModel

from core.db import get_connection
from core.refresh.job_builders import populate_committee_summary_derived_aggregates


class CommitteeTopListBackfillResult(BaseModel):
    rows_updated: int
    elapsed_seconds: float
    cycles: tuple[int, ...]
    committee_ids: tuple[str, ...] | None


def _non_negative_int(raw_value: str) -> int:
    try:
        value = int(raw_value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("--limit must be an integer") from error
    if value < 0:
        raise argparse.ArgumentTypeError("--limit must be greater than or equal to 0")
    return value


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
    return parser


def _select_limited_committee_ids(
    connection: psycopg.Connection,
    *,
    cycles: tuple[int, ...],
    limit: int,
) -> tuple[str, ...]:
    if limit == 0:
        return ()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT committee_id::text
            FROM cf.committee_summary
            WHERE cycle = ANY(%s)
              AND (
                  derived_top_donors IS NULL
                  OR derived_top_vendors IS NULL
                  OR derived_spend_categories IS NULL
              )
            ORDER BY committee_id ASC
            LIMIT %s
            """,
            (list(cycles), limit),
        )
        return tuple(row[0] for row in cursor.fetchall())


def _resolve_committee_scope(
    connection: psycopg.Connection,
    *,
    cycles: tuple[int, ...],
    committee_ids: tuple[str, ...] | None,
    limit: int | None,
) -> tuple[str, ...] | None:
    if committee_ids is not None:
        normalized_committee_ids = _normalize_committee_ids(committee_ids)
        return normalized_committee_ids[:limit] if limit is not None else normalized_committee_ids
    if limit is None:
        return None
    return _select_limited_committee_ids(connection, cycles=cycles, limit=limit)


def backfill_committee_top_lists(
    connection: psycopg.Connection,
    *,
    cycles: tuple[int, ...],
    committee_ids: tuple[str, ...] | None = None,
    limit: int | None = None,
) -> CommitteeTopListBackfillResult:
    scoped_committee_ids = _resolve_committee_scope(
        connection,
        cycles=cycles,
        committee_ids=committee_ids,
        limit=limit,
    )
    started_at = time.perf_counter()
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


def main(argv: list[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)
    cycles = tuple(args.cycles)
    committee_ids = None if args.committee_id is None else tuple(args.committee_id)
    connection = get_connection()
    try:
        with connection.transaction():
            result = backfill_committee_top_lists(
                connection,
                cycles=cycles,
                committee_ids=committee_ids,
                limit=args.limit,
            )
    finally:
        connection.close()

    print(json.dumps(result.model_dump(mode="json"), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
