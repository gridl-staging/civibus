"""NJ-local CSV writer for the bounded-commit specimens.

Cleanup, seeding, independent observation, and the post-cleanup leak check are not
duplicated here: they belong to ``jurisdictions._bulk_fixture_support``, which every
jurisdiction shares.
"""

from __future__ import annotations

import csv
from pathlib import Path
from uuid import uuid4

from domains.campaign_finance.jurisdictions._bulk_fixture_support import BulkFixture
from domains.campaign_finance.jurisdictions.states.NJ.scraper.load import (
    _nj_source_record_key,
    _normalized_column_text,
)
from domains.campaign_finance.jurisdictions.states.NJ.scraper.parse import parse_contributions

_SAMPLE_CONTRIBUTIONS_PATH = Path(__file__).parent / "test_fixtures" / "sample_contributions.csv"


def write_nj_contribution_fixture(tmp_path: Path, *, row_count: int) -> BulkFixture:
    """Write a contributions CSV whose every identity is unique to this run.

    NJ exports have no per-row transaction id and ``_nj_source_record_key`` hashes the
    whole parsed row. Varying the contributor name and street therefore gives every row a
    distinct key. Those fields carry the run suffix so the shared cleanup proof can also
    observe the entity footprint by identity after provenance links are removed.

    ``EntityName`` and ``ElectionYear`` are held constant across every row so the loader
    resolves exactly one committee and one filing while crossing its 1,000-row boundary.
    The header is copied from the sample file unchanged because ``NJCsvParser`` rejects
    any header that is not exactly ``CONTRIBUTION_COLUMNS``.
    """
    if row_count < 1:
        raise ValueError(f"row_count must be >= 1, got {row_count}")

    run_suffix = uuid4().hex[:12]
    contributions_path = tmp_path / f"nj_bounded_{run_suffix}_contributions.csv"

    with _SAMPLE_CONTRIBUTIONS_PATH.open(encoding="utf-8", newline="") as sample_file:
        reader = csv.DictReader(sample_file)
        fieldnames = list(reader.fieldnames or [])
        base_row = next(reader)

    rows: list[dict[str, str]] = []
    for index in range(row_count):
        row = dict(base_row)
        row["FirstName"] = f"Donor{index}{run_suffix}"
        row["LastName"] = f"Bulk{index}{run_suffix}"
        row["Street"] = f"{run_suffix} Test Street {index}"
        row["EntityName"] = f"NJ Bounded Commit Test Committee {run_suffix}"
        rows.append(row)

    with contributions_path.open("w", encoding="utf-8", newline="") as fixture_file:
        writer = csv.DictWriter(fixture_file, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)

    # Both values come from parsed rows because the parser maps empty strings to None before
    # the loader hashes the row or reads the committee.name semantic field.
    parsed_rows = list(parse_contributions(contributions_path))
    return BulkFixture(
        input_path=contributions_path,
        jurisdiction="NJ",
        run_suffix=run_suffix,
        committee_native_id=_normalized_column_text(parsed_rows[0], "committee.name") or "",
        source_record_keys=[_nj_source_record_key(row) for row in parsed_rows],
    )
