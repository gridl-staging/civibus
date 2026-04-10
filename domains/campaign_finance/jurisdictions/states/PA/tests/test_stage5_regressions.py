from __future__ import annotations

from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions.config_schema import load_jurisdiction_config
from domains.campaign_finance.jurisdictions.states.PA.scraper import cli
from domains.campaign_finance.jurisdictions.states.PA.scraper import (
    _load_bulk_download_url_for_data_type,
    _load_columns_for_data_type,
)

_PA_DIR = Path(__file__).resolve().parents[1]
_SCRAPER_DIR = _PA_DIR / "scraper"
_FIXTURES_DIR = _SCRAPER_DIR / "test_fixtures"
_README_PATH = _PA_DIR / "README.md"
_CONFIG_PATH = _PA_DIR / "config.yaml"
_EXPECTED_DATA_TYPES = {"contributions", "expenditures", "debts", "receipts", "filings"}
_FIXTURE_PATH_BY_DATA_TYPE = {
    "contributions": _FIXTURES_DIR / "sample_contributions.csv",
    "expenditures": _FIXTURES_DIR / "sample_expenditures.csv",
    "debts": _FIXTURES_DIR / "sample_debts.csv",
    "receipts": _FIXTURES_DIR / "sample_receipts.csv",
    "filings": _FIXTURES_DIR / "sample_filings.csv",
}
_REQUIRED_SCRAPER_FILES = (
    "download.py",
    "parse.py",
    "extract.py",
    "load.py",
    "cli.py",
    "test_download.py",
    "test_parse.py",
    "test_extract.py",
    "test_load.py",
    "test_cli.py",
)
_YEAR_2025_EXCEPTION_URL = (
    "https://www.pa.gov/content/dam/copapwp-pagov/en/dos/resources/voting-and-elections/"
    "campaign-finance/campaign-finance-data/2025%20campaign%20finance%20full%20export%20.zip"
)


def _csv_header(path: Path) -> tuple[str, ...]:
    first_line = path.read_text(encoding="utf-8").splitlines()[0]
    return tuple(first_line.split(","))


def _assert_named_files_exist(parent_dir: Path, file_names: tuple[str, ...]) -> None:
    for file_name in file_names:
        assert (parent_dir / file_name).is_file()


def _load_pa_data_sources_by_type() -> dict[str, object]:
    config = load_jurisdiction_config(_CONFIG_PATH)
    return {data_source.coverage.transaction_types[0]: data_source for data_source in config.data_sources}


def test_stage5_fixture_headers_match_config_field_mapping_order() -> None:
    for data_type, fixture_path in _FIXTURE_PATH_BY_DATA_TYPE.items():
        assert _csv_header(fixture_path) == _load_columns_for_data_type(data_type)


def test_stage5_required_scraper_files_exist() -> None:
    _assert_named_files_exist(_SCRAPER_DIR, _REQUIRED_SCRAPER_FILES)


def test_stage5_expected_fixture_files_exist() -> None:
    _assert_named_files_exist(_FIXTURES_DIR, tuple(path.name for path in _FIXTURE_PATH_BY_DATA_TYPE.values()))


def test_stage5_pa_readme_and_config_match_current_package_contract() -> None:
    readme_text = _README_PATH.read_text(encoding="utf-8")
    readme_text_lower = readme_text.lower()

    assert "intentionally deferred" not in readme_text_lower
    assert "canonical ingest contract" in readme_text_lower
    assert "full-export zip" in readme_text_lower
    assert "machine export/api + scope parity are unverified" in readme_text_lower
    assert "parse/dry-run only" in readme_text_lower

    data_sources_by_type = _load_pa_data_sources_by_type()

    assert set(data_sources_by_type) == _EXPECTED_DATA_TYPES

    for data_type, data_source in data_sources_by_type.items():
        # PA ZIPs are actually updated ~weekly despite URL labeling (verified 2026-03-28,
        # see docs/research/pa-freshness-investigation-2026-03-28.md)
        assert data_source.update_frequency == "weekly"
        assert data_source.api_base_url is None
        assert data_source.bulk_download_url is not None
        assert "{year}" in data_source.bulk_download_url
        assert _load_bulk_download_url_for_data_type(data_type, 2026).endswith("/2026.zip")
        assert _load_bulk_download_url_for_data_type(data_type, 2025) == _YEAR_2025_EXCEPTION_URL

    with pytest.raises(ValueError, match="PA filings data type is supported for parse/dry-run only"):
        cli.run_pa_refresh(year=2025, data_type="filings", path=_FIXTURES_DIR / "sample_filings.csv")
