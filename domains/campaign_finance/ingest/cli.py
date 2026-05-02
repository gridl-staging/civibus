"""
Stub summary for /Users/stuart/parallel_development/civibus_dev/mar21_01_fec_pipeline_hardening/civibus_dev/domains/campaign_finance/ingest/cli.py.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from uuid import UUID

import psycopg

from core.db import get_connection
from core.graph import age_post_connect, ensure_graph
from core.types.python.models import DataSource
from domains.campaign_finance.ingest.fec_client import FecApiError, FecClient
from domains.campaign_finance.ingest.loader import ensure_fec_data_source, load_contribution


@dataclass(frozen=True, slots=True)
class FECRefreshSummary:
    loaded_count: int
    skipped_count: int
    error_count: int
    fetched_count: int


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load FEC Schedule A contributions into Civibus")
    parser.add_argument("--state", required=True, help="Two-letter contributor state filter (example: NC)")
    parser.add_argument("--cycle", required=True, type=int, help="Two-year transaction period (example: 2024)")
    parser.add_argument("--limit", type=int, default=100, help="Maximum records to fetch (default: 100)")
    return parser


def _load_contributions(
    connection: psycopg.Connection,
    data_source_id: UUID,
    contribution_records: list[dict[str, object]],
) -> tuple[int, int, int]:
    loaded_count = 0
    skipped_count = 0
    error_count = 0

    for contribution in contribution_records:
        try:
            # Keep each record isolated so one database failure doesn't abort the batch transaction.
            with connection.transaction():
                inserted = load_contribution(connection, data_source_id, contribution, graph_enabled=True)
        except Exception as error:  # noqa: BLE001
            error_count += 1
            print(f"Error loading contribution sub_id={contribution.get('sub_id')}: {error}", file=sys.stderr)
            continue

        if inserted:
            loaded_count += 1
        else:
            skipped_count += 1

    return loaded_count, skipped_count, error_count


def run_fec_refresh(*, state: str, cycle: int, limit: int) -> FECRefreshSummary:
    """Run one typed FEC refresh cycle without argparse plumbing."""
    client = FecClient()
    contribution_records = client.fetch_contributions(state=state, cycle=cycle, limit=limit)

    connection: psycopg.Connection | None = None
    try:
        connection = get_connection(post_connect=age_post_connect)
        connection.commit()
        with connection.transaction():
            ensure_graph(connection)
            data_source_id = ensure_fec_data_source(connection)
            loaded_count, skipped_count, error_count = _load_contributions(
                connection,
                data_source_id,
                contribution_records,
            )
        connection.commit()
    finally:
        if connection is not None:
            connection.close()

    return FECRefreshSummary(
        loaded_count=loaded_count,
        skipped_count=skipped_count,
        error_count=error_count,
        fetched_count=len(contribution_records),
    )


def run_federal_officeholder_refresh(
    *,
    chamber: str,
    rows: list[dict[str, str | None]],
) -> tuple[int, int, int]:
    """Load pre-parsed federal officeholder directory rows into the DB.

    Returns (inserted, skipped, errors) counts.
    """
    from domains.campaign_finance.ingest.federal_officeholder_loader import (
        load_federal_house_officeholders,
        load_federal_senate_officeholders,
    )
    from domains.campaign_finance.jurisdictions.states.load_utils import ensure_data_source

    chamber_lower = chamber.strip().lower()
    if chamber_lower not in ("house", "senate"):
        raise ValueError(f"chamber must be 'house' or 'senate', got {chamber!r}")

    source_name = f"US {chamber.title()} Officeholder Directory"
    source_url = (
        "https://clerk.house.gov/xml/lists/MemberData.xml"
        if chamber_lower == "house"
        else "https://www.senate.gov/general/contact_information/senators_cfm.xml"
    )

    connection = get_connection()
    try:
        ds_id = ensure_data_source(
            connection,
            DataSource(
                domain="campaign_finance",
                jurisdiction=f"federal/officeholder/{chamber_lower}",
                name=source_name,
                source_url=source_url,
            ),
        )
        connection.commit()
        loader = load_federal_house_officeholders if chamber_lower == "house" else load_federal_senate_officeholders
        result = loader(connection, rows, data_source_id=ds_id)
        connection.commit()
        return result.inserted, result.skipped, result.errors
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    args = _build_argument_parser().parse_args(argv)
    try:
        summary = run_fec_refresh(state=args.state, cycle=args.cycle, limit=args.limit)
    except FecApiError as error:
        print(f"FEC fetch failed: {error}", file=sys.stderr)
        return 1
    except Exception as error:  # noqa: BLE001
        print(f"FEC ingest failed: {error}", file=sys.stderr)
        return 1

    print(
        f"FEC ingest complete: loaded={summary.loaded_count} skipped={summary.skipped_count} "
        f"errors={summary.error_count} fetched={summary.fetched_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
