from __future__ import annotations

import csv
from pathlib import Path

from domains.campaign_finance.jurisdictions.states.TX.scraper.parse import (
    parse_contributions,
    parse_expenditures,
    parse_loans,
)

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.csv"
SAMPLE_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_expenditures.csv"
SAMPLE_LOANS_PATH = _FIXTURE_DIR / "sample_loans.csv"


def parsed_contributions() -> list[dict[str, str | None]]:
    return list(parse_contributions(SAMPLE_CONTRIBUTIONS_PATH))


def parsed_expenditures() -> list[dict[str, str | None]]:
    return list(parse_expenditures(SAMPLE_EXPENDITURES_PATH))


def parsed_loans() -> list[dict[str, str | None]]:
    return list(parse_loans(SAMPLE_LOANS_PATH))


def write_csv_rows(
    csv_path: Path,
    *,
    fieldnames: list[str],
    rows: list[dict[str, str | None]],
) -> None:
    with csv_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column) or "" for column in fieldnames})
