"""IN-local CSV writer for the bounded-commit specimens.

Cleanup, seeding, independent observation, and the post-cleanup leak check are not
duplicated here: they belong to ``jurisdictions._bulk_fixture_support``, which every
jurisdiction shares.
"""

from __future__ import annotations

import csv
from pathlib import Path
from uuid import uuid4

from domains.campaign_finance.jurisdictions._bulk_fixture_support import BulkFixture
from domains.campaign_finance.jurisdictions.states.IN.scraper.load_helpers import (
    _in_native_committee_id,
    _in_source_record_key,
)
from domains.campaign_finance.jurisdictions.states.IN.scraper.parse import parse_contributions

_SAMPLE_CONTRIBUTIONS_PATH = Path(__file__).parent / "test_fixtures" / "sample_contributions.csv"


def write_in_contribution_fixture(
    tmp_path: Path,
    *,
    row_count: int,
    amount: str | None = None,
) -> BulkFixture:
    """Write a contributions CSV whose every identity is unique to this run.

    ``_in_source_record_key`` is a whole-parsed-row hash and Indiana exports carry no
    per-row transaction id, so per-row uniqueness comes only from mutating ``Name`` and
    ``Address``. Both carry the run suffix, as does ``Committee``, which is what lets
    ``bulk_fixture_entity_row_counts`` observe the entity footprint by identity rather
    than through provenance links cleanup has already deleted.

    ``FileNumber``, ``CommitteeType``, ``Committee``, and the ``ContributionDate`` year are
    held constant across every row so the load resolves exactly one committee and one
    ``_in_filing_fec_id`` while still crossing the loader's 1,000-row commit boundary.
    ``Amended`` is pinned to ``"0"`` so no row can take ``_load_in_rows``' amendment-error
    branch, which owns a second commit boundary and would move the interrupt off the row
    the specimen intends.

    The header is copied from the sample file unchanged: ``INCsvParser`` rejects any header
    that is not exactly ``CONTRIBUTION_COLUMNS``, so an added or reordered column would fail
    the load instead of the assertion the specimen is making.
    """
    if row_count < 1:
        raise ValueError(f"row_count must be >= 1, got {row_count}")

    run_suffix = uuid4().hex[:12]
    contributions_path = tmp_path / f"in_bounded_{run_suffix}_contributions.csv"

    with _SAMPLE_CONTRIBUTIONS_PATH.open(encoding="utf-8", newline="") as sample_file:
        reader = csv.DictReader(sample_file)
        fieldnames = list(reader.fieldnames or [])
        base_row = next(reader)

    rows: list[dict[str, str]] = []
    for index in range(row_count):
        row = dict(base_row)
        row["Committee"] = f"IN Bounded Commit Test Committee {run_suffix}"
        row["Name"] = f"Donor{index} {run_suffix}"
        row["Address"] = f"{run_suffix} Test Street {index}"
        row["Amended"] = "0"
        if amount is not None:
            row["Amount"] = amount
        rows.append(row)

    with contributions_path.open("w", encoding="utf-8", newline="") as fixture_file:
        writer = csv.DictWriter(fixture_file, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)

    # Keys and the committee id are computed over parsed rows, not the raw CSV dicts: the
    # parser maps empty strings to None before the loader ever sees a row, and both the key
    # hash and the derived committee id read what the loader sees.
    parsed_rows = list(parse_contributions(contributions_path))
    source_record_keys = [_in_source_record_key(row, data_type="contributions") for row in parsed_rows]
    return BulkFixture(
        input_path=contributions_path,
        jurisdiction="IN",
        run_suffix=run_suffix,
        committee_native_id=_in_native_committee_id(parsed_rows[0], data_type="contributions"),
        source_record_keys=source_record_keys,
    )
