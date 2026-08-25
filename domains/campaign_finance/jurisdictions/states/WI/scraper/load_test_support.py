"""WI-local CSV writer for the bounded-commit specimens.

Cleanup, seeding, independent observation, and the post-cleanup leak check are not
duplicated here: they belong to ``jurisdictions._bulk_fixture_support``, which every
jurisdiction shares.
"""

from __future__ import annotations

import csv
from pathlib import Path
from uuid import uuid4

from domains.campaign_finance.jurisdictions._bulk_fixture_support import BulkFixture
from domains.campaign_finance.jurisdictions.states.WI.scraper.load import _wi_source_record_key
from domains.campaign_finance.jurisdictions.states.WI.scraper.parse import parse_transactions

_SAMPLE_TRANSACTIONS_PATH = Path(__file__).parent / "test_fixtures" / "sample_transactions.csv"


def write_wi_transaction_fixture(tmp_path: Path, *, row_count: int) -> BulkFixture:
    """Write a transactions CSV whose every identity is unique to this run.

    ``_wi_source_record_key`` is a whole-row hash, so mutating ``ID``, the contributor name,
    and ``Contributor Address 1`` with the run suffix gives every row a distinct source-record
    key. Every row keeps one shared ``Registrant ID`` (the committee's native id), so the load
    resolves exactly one committee and one filing while still crossing the loader's 1,000-row
    commit boundary. Scoping cleanup by those distinct keys is what keeps two fixtures running
    concurrently under xdist from resolving to, and then deleting, each other's rows.
    """
    if row_count < 1:
        raise ValueError(f"row_count must be >= 1, got {row_count}")

    run_suffix = uuid4().hex[:12]
    committee_native_id = f"WIBATCH{run_suffix}"
    transactions_path = tmp_path / f"wi_bounded_{run_suffix}_transactions.csv"

    with _SAMPLE_TRANSACTIONS_PATH.open(encoding="utf-8", newline="") as sample_file:
        reader = csv.DictReader(sample_file)
        fieldnames = list(reader.fieldnames or [])
        base_row = next(reader)

    contributor_name_column = "Contributor Name (-> Related Payer Name if applicable)"
    rows: list[dict[str, str]] = []
    for index in range(row_count):
        row = dict(base_row)
        row["ID"] = f"TXN-{run_suffix}-{index}"
        row[contributor_name_column] = f"Donor{index} {run_suffix}"
        row["Contributor Address 1"] = f"{run_suffix} Test Street {index}"
        row["Registrant ID"] = committee_native_id
        row["Registrant Name"] = f"WI Bounded Commit Test Committee {run_suffix}"
        rows.append(row)

    with transactions_path.open("w", encoding="utf-8", newline="") as fixture_file:
        writer = csv.DictWriter(fixture_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    source_record_keys = [_wi_source_record_key(row) for row in parse_transactions(transactions_path)]
    return BulkFixture(
        input_path=transactions_path,
        jurisdiction="WI",
        run_suffix=run_suffix,
        committee_native_id=committee_native_id,
        source_record_keys=source_record_keys,
    )
