from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from core.db import get_connection
from core.entity_resolution.roster_candidacy_resolver import resolve_roster_candidacy_people


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="roster-candidacy-resolution",
        description="Resolve roster/candidacy person links through shared ER scoring.",
    )
    parser.add_argument(
        "--auto-merge-threshold",
        type=float,
        default=None,
        help="Optional confidence threshold override for match classification.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_argument_parser()
    args = parser.parse_args(argv)

    connection = get_connection()
    try:
        summary = resolve_roster_candidacy_people(
            connection,
            auto_merge_threshold=args.auto_merge_threshold,
        )
        connection.commit()
    finally:
        connection.close()

    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
