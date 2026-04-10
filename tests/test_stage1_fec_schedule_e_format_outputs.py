from __future__ import annotations

import csv
from pathlib import Path

from domains.campaign_finance.ingest.bulk_cli import fec_schedule_e_url


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_schedule_e_fixture_parses_with_dict_reader_contract() -> None:
    fixture_path = REPO_ROOT / "tests" / "fixtures" / "bulk" / "schedule_e_sample.csv"

    with fixture_path.open(encoding="utf-8", newline="") as fixture_file:
        reader = csv.DictReader(fixture_file)
        rows = list(reader)

    assert reader.fieldnames is not None
    assert len(reader.fieldnames) == 23
    assert 20 <= len(rows) <= 50
    assert all(len(row) == 23 for row in rows)
    assert {"", "O", "S"} == {row["sup_opp"] for row in rows}
    assert {"N", "A1", "A2", "A3", "A4"} == {row["amndt_ind"] for row in rows}

    for row in rows:
        for value in row.values():
            assert value == value.encode("utf-8").decode("utf-8")


def test_schedule_e_research_docs_stay_empirical_and_cross_referenced() -> None:
    format_doc = (REPO_ROOT / "docs" / "research" / "fec-schedule-e-format.md").read_text(encoding="utf-8")
    bulk_doc = (REPO_ROOT / "docs" / "research" / "fec-bulk-data.md").read_text(encoding="utf-8")

    assert "## Fixture Validation (csv.DictReader)" in format_doc
    assert "Implication for schema:" not in format_doc
    assert "cf.transaction.amendment_indicator" not in format_doc
    assert "must map" not in format_doc

    assert "See [fec-schedule-e-format.md](fec-schedule-e-format.md)." in bulk_doc
    assert "Key differences from legacy TXT:" not in bulk_doc


def test_fec_schedule_e_url_uses_independent_expenditure_csv_pattern() -> None:
    assert fec_schedule_e_url(2024) == "https://www.fec.gov/files/bulk-downloads/2024/independent_expenditure_2024.csv"
    assert fec_schedule_e_url(2026) == "https://www.fec.gov/files/bulk-downloads/2026/independent_expenditure_2026.csv"
