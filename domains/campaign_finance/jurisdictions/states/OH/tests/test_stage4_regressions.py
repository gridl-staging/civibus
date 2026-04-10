from __future__ import annotations

import csv
from pathlib import Path

from domains.campaign_finance.jurisdictions.states.OH.scraper import _load_columns_for_data_type
from domains.campaign_finance.jurisdictions.states.OH.scraper.parse import parse_contributions, parse_expenditures

_OH_DIR = Path(__file__).resolve().parents[1]
_SCRAPER_DIR = _OH_DIR / "scraper"
_FIXTURE_DIR = _SCRAPER_DIR / "test_fixtures"
_SAMPLE_ROWS_DIR = _OH_DIR / "sample_rows"


def _header(path: Path) -> tuple[str, ...]:
    with path.open("r", encoding="utf-8", newline="") as csv_file:
        reader = csv.reader(csv_file)
        return tuple(next(reader))


def test_oh_fixture_headers_match_config_field_mapping_order() -> None:
    assert _header(_FIXTURE_DIR / "sample_contributions.csv") == _load_columns_for_data_type("contributions")
    assert _header(_FIXTURE_DIR / "sample_expenditures.csv") == _load_columns_for_data_type("expenditures")


def test_oh_sample_rows_headers_match_config_field_mapping_order() -> None:
    assert _header(_SAMPLE_ROWS_DIR / "contributions_sample.csv") == _load_columns_for_data_type("contributions")
    assert _header(_SAMPLE_ROWS_DIR / "expenditures_sample.csv") == _load_columns_for_data_type("expenditures")


def test_oh_sample_rows_parse_without_quarantining_rows() -> None:
    contribution_parser = parse_contributions(_SAMPLE_ROWS_DIR / "contributions_sample.csv")
    expenditure_parser = parse_expenditures(_SAMPLE_ROWS_DIR / "expenditures_sample.csv")

    assert len(list(contribution_parser)) == 3
    assert contribution_parser.skipped == 0
    assert len(list(expenditure_parser)) == 3
    assert expenditure_parser.skipped == 0


def test_required_stage4_scraper_files_exist() -> None:
    required_paths = [
        _SCRAPER_DIR / "__init__.py",
        _SCRAPER_DIR / "download.py",
        _SCRAPER_DIR / "parse.py",
        _SCRAPER_DIR / "test_parse.py",
        _SCRAPER_DIR / "test_download.py",
    ]

    assert all(path.exists() for path in required_paths)


def test_expected_stage4_fixture_files_exist() -> None:
    expected_fixtures = {
        "sample_contributions.csv",
        "sample_expenditures.csv",
    }

    assert expected_fixtures.issubset({path.name for path in _FIXTURE_DIR.iterdir() if path.is_file()})
