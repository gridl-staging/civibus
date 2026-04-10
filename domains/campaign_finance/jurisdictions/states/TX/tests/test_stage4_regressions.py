from __future__ import annotations

import csv
from pathlib import Path

from domains.campaign_finance.jurisdictions.states.TX.scraper import _load_columns_for_data_type

_TX_DIR = Path(__file__).resolve().parents[1]
_SCRAPER_DIR = _TX_DIR / "scraper"
_FIXTURE_DIR = _SCRAPER_DIR / "test_fixtures"


def _header(path: Path) -> tuple[str, ...]:
    with path.open("r", encoding="utf-8", newline="") as csv_file:
        reader = csv.reader(csv_file)
        return tuple(next(reader))


def test_tx_fixture_headers_match_config_field_mapping_order() -> None:
    assert _header(_FIXTURE_DIR / "sample_contributions.csv") == _load_columns_for_data_type("contributions")
    assert _header(_FIXTURE_DIR / "sample_expenditures.csv") == _load_columns_for_data_type("expenditures")
    assert _header(_FIXTURE_DIR / "sample_loans.csv") == _load_columns_for_data_type("loans")


def test_required_stage4_scraper_files_exist() -> None:
    required_paths = [
        _SCRAPER_DIR / "__init__.py",
        _SCRAPER_DIR / "download.py",
        _SCRAPER_DIR / "parse.py",
        _SCRAPER_DIR / "extract.py",
        _SCRAPER_DIR / "load.py",
        _SCRAPER_DIR / "cli.py",
        _SCRAPER_DIR / "test_parse.py",
        _SCRAPER_DIR / "test_download.py",
        _SCRAPER_DIR / "test_extract.py",
        _SCRAPER_DIR / "test_load.py",
        _SCRAPER_DIR / "test_cli.py",
    ]

    assert all(path.exists() for path in required_paths)


def test_expected_stage4_fixture_files_exist() -> None:
    expected_fixtures = {
        "sample_contributions.csv",
        "sample_expenditures.csv",
        "sample_loans.csv",
    }

    assert expected_fixtures.issubset({path.name for path in _FIXTURE_DIR.iterdir() if path.is_file()})
