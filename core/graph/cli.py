
from __future__ import annotations

import argparse
import sys
from typing import Protocol

import psycopg

from core.db import get_connection
from core.graph import age_post_connect
from core.graph.loader import (
    load_affiliated_with_edges,
    load_contributed_to_edges,
    load_filed_edges,
    load_ie_edges,
    load_spent_on_edges,
)
from domains.civics.graph.loader import load_civic_edges
from domains.property.graph.loader import load_property_edges


class LoaderFn(Protocol):
    def __call__(self, conn: psycopg.Connection, *, limit: int) -> int: ...


def _cf_edge_loaders() -> tuple[tuple[str, LoaderFn], ...]:
    return (
        ("CONTRIBUTED_TO", load_contributed_to_edges),
        ("SPENT_ON", load_spent_on_edges),
        ("SUPPORTS/OPPOSES", load_ie_edges),
        ("AFFILIATED_WITH", load_affiliated_with_edges),
        ("FILED", load_filed_edges),
    )


def load_cf_edges(conn: psycopg.Connection, *, limit: int = 1000) -> int:
    total_count = 0
    for edge_label, loader_fn in _cf_edge_loaders():
        edge_count = loader_fn(conn, limit=limit)
        print(f"Loaded {edge_label} edge(s): {edge_count}")
        total_count += edge_count

    print(f"Loaded total campaign-finance edge(s): {total_count}")
    return total_count


def _load_mixed_domain_edges(conn: psycopg.Connection, *, limit: int) -> tuple[int, int, int, int]:
    campaign_finance_count = load_cf_edges(conn, limit=limit)
    property_count = load_property_edges(conn, limit=limit)
    civic_count = load_civic_edges(conn, limit=limit)
    total_count = campaign_finance_count + property_count + civic_count
    return campaign_finance_count, property_count, civic_count, total_count


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Load mixed-domain AGE edges for campaign-finance, property, and civics (supported entrypoint: `make graph-load`)"
    )
    parser.add_argument("--limit", type=int, default=1000, help="Max rows per edge loader (default: 1000)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)

    conn: psycopg.Connection | None = None
    try:
        conn = get_connection(post_connect=age_post_connect)
        campaign_finance_count, property_count, civic_count, total_count = _load_mixed_domain_edges(
            conn, limit=args.limit
        )
        conn.commit()
        print(f"Loaded campaign-finance edge(s): {campaign_finance_count}")
        print(f"Loaded property edge(s): {property_count}")
        print(f"Loaded civic edge(s): {civic_count}")
        print(f"Loaded total edge(s) into AGE graph: {total_count}")
    except Exception as error:
        print(f"Graph load failed: {error}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
