"""Tests for AL parse module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions.states.AL.scraper import _load_columns_for_data_type
from domains.campaign_finance.jurisdictions.states.AL.scraper.parse import (
    CONTRIBUTION_COLUMNS,
    EXPENDITURE_COLUMNS,
    parse_contributions,
    parse_expenditures,
)

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.json"
_SAMPLE_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_expenditures.json"


def test_columns_derive_from_al_config() -> None:
    assert CONTRIBUTION_COLUMNS == _load_columns_for_data_type("contributions")
    assert EXPENDITURE_COLUMNS == _load_columns_for_data_type("expenditures")


def test_parse_contributions_filters_old_rows_by_year() -> None:
    """Fixture has 1 row from 2021 and 3 from 2026. year_from=2022 should drop the 2021 row."""
    rows = list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH, year_from=2022))
    assert len(rows) == 3
    for row in rows:
        assert "2026" in row["TRANSACTIONDATE"]


def test_parse_contributions_includes_all_when_year_from_is_low() -> None:
    """With year_from=2020, all 4 fixture rows pass the filter."""
    rows = list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH, year_from=2020))
    assert len(rows) == 4


def test_parse_expenditures_filters_old_rows_by_year() -> None:
    """Fixture has 1 row from 2021 and 1 from 2026. year_from=2022 should keep only the 2026 row."""
    rows = list(parse_expenditures(_SAMPLE_EXPENDITURES_PATH, year_from=2022))
    assert len(rows) == 1
    assert "2026" in rows[0]["TRANSACTIONDATE"]


def test_parse_normalizes_empty_strings_to_none() -> None:
    """Empty string fields in the JSON should be normalized to None."""
    rows = list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH, year_from=2022))
    williams_row = next(r for r in rows if r.get("CONTRIBUTOR") == "SARAH WILLIAMS")
    assert williams_row["DESCRIPTION"] is None


def test_parse_preserves_non_empty_field_values() -> None:
    """Non-empty fields should be preserved with leading/trailing whitespace stripped."""
    rows = list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH, year_from=2022))
    williams_row = next(r for r in rows if r.get("CONTRIBUTOR") == "SARAH WILLIAMS")
    assert williams_row["CONTRIBUTOR"] == "SARAH WILLIAMS"
    assert williams_row["AMOUNT"] == "1000.00"
    assert williams_row["CITYSTATE"] == "Montgomery, AL"


def test_parse_only_includes_config_columns() -> None:
    """Parsed rows should only contain keys from CONTRIBUTION_COLUMNS."""
    rows = list(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH, year_from=2022))
    for row in rows:
        assert set(row.keys()) == set(CONTRIBUTION_COLUMNS)


def test_parse_tracks_filtered_count() -> None:
    """The parser should track how many rows were filtered by year."""
    parser = parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH, year_from=2022)
    rows = list(parser)
    assert parser.filtered == 1  # The 2021 row was filtered.
    assert len(rows) == 3


def test_parse_rejects_oversized_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """JSON files exceeding the size limit should raise ValueError."""
    from domains.campaign_finance.jurisdictions.states.AL.scraper import parse as al_parse

    small_json = tmp_path / "small.json"
    small_json.write_text(json.dumps({"totalRecords": 0, "data": []}))
    # Set limit below file size.
    monkeypatch.setattr(al_parse, "MAX_JSON_FILE_BYTES", 1)
    with pytest.raises(ValueError, match="exceeds the allowed size limit"):
        list(parse_contributions(small_json, year_from=2022))


def test_parse_handles_bare_list_json(tmp_path: Path) -> None:
    """Parser should accept a bare JSON array (not wrapped in {data: [...]})."""
    bare = [
        {
            "TRANSACTIONID": "999",
            "COMMITTEEID": "CC1",
            "RECIPIENTNAME": "Test PAC",
            "CONTRIBUTOR": "JANE TEST",
            "CONTRIBUTIONTYPE": "Monetary",
            "CITYSTATE": "Test City, AL",
            "ZIP": "35000",
            "TRANSACTIONDATE": "01/01/2026",
            "FILINGDATE": "01/05/2026",
            "AMOUNT": "100.00",
            "DESCRIPTION": "",
        }
    ]
    bare_path = tmp_path / "bare.json"
    bare_path.write_text(json.dumps(bare))
    rows = list(parse_contributions(bare_path, year_from=2022))
    assert len(rows) == 1
    assert rows[0]["CONTRIBUTOR"] == "JANE TEST"
