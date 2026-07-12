from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg

from core.db import get_connection
from domains.civics.loaders.official_rosters.loader import harvest_official_roster


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Harvest one official roster source into canonical civic owners")
    parser.add_argument(
        "--source-id", required=True, help="Roster source registry id (for example: nc_durham_city_council_roster)"
    )
    parser.add_argument("--fixture-path", type=Path, help="Optional local HTML fixture path")
    parser.add_argument("--dry-run", action="store_true", help="Parse + resolve only; never write to DB")
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=30.0,
        help="Network timeout in seconds when fixture-path is not provided",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Command entrypoint for source-id-driven official roster harvests."""
    args = _build_argument_parser().parse_args(argv)

    if args.fixture_path is not None and not args.fixture_path.exists():
        print(f"Fixture HTML file not found: {args.fixture_path}", file=sys.stderr)
        return 1

    connection: psycopg.Connection | None = None
    try:
        connection = get_connection()
        with connection.transaction():
            result = harvest_official_roster(
                connection,
                source_id=args.source_id,
                fixture_path=args.fixture_path,
                dry_run=args.dry_run,
                timeout_seconds=args.timeout_seconds,
            )
        if args.dry_run:
            connection.rollback()
        else:
            connection.commit()
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"Official roster harvest failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            connection.close()

    print(
        "Official roster harvest complete: "
        f"source_id={result.source_id} body_key={result.body_key} members={result.member_count} "
        f"resolved={result.resolved_member_count} unresolved={result.unresolved_member_count} "
        f"officeholding_upserts={result.officeholding_upserts} portrait_writes={result.portrait_writes} "
        f"dry_run={result.dry_run}"
    )
    if result.source_record_key is not None and result.source_record_id is not None:
        print(
            "Source snapshot: "
            f"key={result.source_record_key} source_record_id={result.source_record_id} inserted={result.source_record_inserted}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
