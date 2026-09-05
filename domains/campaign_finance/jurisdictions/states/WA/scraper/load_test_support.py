"""Shared WA loader test fixtures for the bounded-commit specimens.

Single owner of the synthetic bulk contributions CSV and of the seeding contract the
WA batch-boundary specimens run against. Cleanup, independent observation, and the
post-cleanup leak check are not duplicated here: they belong to
``jurisdictions._bulk_fixture_support``, which every jurisdiction shares.
"""

from __future__ import annotations

import csv
from contextlib import ExitStack
from pathlib import Path
from typing import NamedTuple
from uuid import uuid4

import psycopg

from domains.campaign_finance.ingest.filing_loader import generate_synthetic_committee_id
from domains.campaign_finance.jurisdictions._bulk_fixture_support import seed_bulk_fixture
from domains.campaign_finance.jurisdictions.states.WA.scraper.load import _wa_source_record_key
from domains.campaign_finance.jurisdictions.states.WA.scraper.parse import parse_contributions

_SAMPLE_CONTRIBUTIONS_PATH = Path(__file__).parent / "test_fixtures" / "sample_contributions.csv"


class WABulkFixture(NamedTuple):
    """One synthetic WA contributions CSV and the identities it writes."""

    contributions_path: Path
    run_suffix: str
    committee_native_id: str
    source_record_keys: list[str]

    @property
    def committee_fec_id(self) -> str:
        return generate_synthetic_committee_id("WA", self.committee_native_id)


def write_wa_contribution_fixture(tmp_path: Path, *, row_count: int) -> WABulkFixture:
    """Write a contributions CSV whose every identity is unique to this run.

    All rows share one per-run committee so the load resolves a single committee and
    filing family, while each row carries a distinct PDC native ID — and therefore a
    distinct source-record key and transaction identifier. That is what lets a
    bulk fixture cross ``wa_load._COMMIT_BATCH_ROWS`` and still be cleaned up by its own
    scoped keys, and what keeps two fixtures running concurrently under xdist from
    resolving to, and then deleting, each other's rows.
    """
    if row_count < 1:
        raise ValueError(f"row_count must be >= 1, got {row_count}")

    run_suffix = uuid4().hex[:12]
    committee_native_id = f"WABATCH{run_suffix}"
    report_number = f"WABATCHRPT{run_suffix}"
    contributions_path = tmp_path / f"wa_bounded_{run_suffix}_contributions.csv"

    with _SAMPLE_CONTRIBUTIONS_PATH.open(encoding="utf-8", newline="") as sample_file:
        reader = csv.DictReader(sample_file)
        fieldnames = list(reader.fieldnames or [])
        base_row = next(reader)

    rows: list[dict[str, str]] = []
    for index in range(row_count):
        row = dict(base_row)
        row["id"] = f"{run_suffix}{index}"
        row["report_number"] = report_number
        row["committee_id"] = committee_native_id
        row["filer_name"] = f"WA Bounded Commit Test Committee {run_suffix}"
        row["contributor_name"] = f"Batch{index}, Donor{run_suffix}"
        row["contributor_address"] = f"{run_suffix} Test Street"
        rows.append(row)

    with contributions_path.open("w", encoding="utf-8", newline="") as fixture_file:
        writer = csv.DictWriter(fixture_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    source_record_keys = [
        _wa_source_record_key(row, data_type="contributions") for row in parse_contributions(contributions_path)
    ]
    return WABulkFixture(
        contributions_path=contributions_path,
        run_suffix=run_suffix,
        committee_native_id=committee_native_id,
        source_record_keys=source_record_keys,
    )


def seed_wa_bulk_fixture(
    resources: ExitStack,
    db_conn: psycopg.Connection,
    tmp_path: Path,
    *,
    row_count: int,
) -> WABulkFixture:
    """Write the bulk fixture and hand it to the shared seeding contract."""
    fixture = write_wa_contribution_fixture(tmp_path, row_count=row_count)
    seed_bulk_fixture(resources, db_conn, fixture, expected_unique_source_record_keys=row_count)
    return fixture
