from __future__ import annotations

from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions._test_helpers import csv_headers
from domains.campaign_finance.jurisdictions.states.IN.scraper import (
    _load_bulk_download_url_for_data_type,
    _load_column_for_semantic_path,
    _load_columns_for_data_type,
    _load_data_source_for_data_type,
    _load_in_config,
    _load_in_data_source_blocks,
    _load_semantic_path_to_column_map,
)

REPO_ROOT = Path(__file__).resolve().parents[6]
IN_DIR = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "IN"
CONTRIBUTIONS_SAMPLE_PATH = IN_DIR / "sample_rows" / "contributions_sample.csv"
EXPENDITURES_SAMPLE_PATH = IN_DIR / "sample_rows" / "expenditures_sample.csv"
_EXPECTED_SOURCE_NAME_BY_DATA_TYPE = {
    "contributions": "IN IED Campaign Finance - Contributions",
    "expenditures": "IN IED Campaign Finance - Expenditures",
}
_EXPECTED_BULK_DOWNLOAD_URL_BY_DATA_TYPE = {
    "contributions": (
        "https://campaignfinance.in.gov/PublicSite/Docs/BulkDataDownloads/{YEAR}_ContributionData.csv.zip"
    ),
    "expenditures": ("https://campaignfinance.in.gov/PublicSite/Docs/BulkDataDownloads/{YEAR}_ExpenditureData.csv.zip"),
}
_SAMPLE_PATH_BY_DATA_TYPE = {
    "contributions": CONTRIBUTIONS_SAMPLE_PATH,
    "expenditures": EXPENDITURES_SAMPLE_PATH,
}


def _in_data_sources_by_type():
    data_sources = tuple(_load_in_config().data_sources)
    return data_sources, {tuple(data_source.coverage.transaction_types): data_source for data_source in data_sources}


def test_config_loads_successfully() -> None:
    config = _load_in_config()

    assert config.jurisdiction.code == "IN"
    assert config.jurisdiction.name == "Indiana"
    assert config.jurisdiction.type == "state"
    assert config.jurisdiction.fips == "18"


def test_data_source_blocks_include_only_expected_in_shapes() -> None:
    blocks = _load_in_data_source_blocks()
    names = {block.name for block in blocks}

    assert names == {
        "IN IED Campaign Finance - Contributions",
        "IN IED Campaign Finance - Expenditures",
    }


def test_indiana_ingest_contract_is_annual_zip_for_contributions_and_expenditures() -> None:
    data_sources, data_sources_by_transaction_type = _in_data_sources_by_type()

    assert len(data_sources) == 2
    assert set(data_sources_by_transaction_type) == {("contributions",), ("expenditures",)}

    for data_type, expected_url in _EXPECTED_BULK_DOWNLOAD_URL_BY_DATA_TYPE.items():
        source = data_sources_by_transaction_type[(data_type,)]
        assert source.update_frequency == "annual"
        assert source.bulk_download_url == expected_url


def test_scraper_status_is_complete_in_machine_readable_config() -> None:
    config = _load_in_config()

    assert config.status.scraper == "complete"


def test_load_data_source_for_data_type_returns_expected_source() -> None:
    for data_type, expected_name in _EXPECTED_SOURCE_NAME_BY_DATA_TYPE.items():
        assert _load_data_source_for_data_type(data_type).name == expected_name


def test_bulk_download_url_accessor_reads_from_data_source_config() -> None:
    expected_url = _load_data_source_for_data_type("contributions").bulk_download_url

    assert _load_bulk_download_url_for_data_type("contributions") == expected_url


@pytest.mark.parametrize("data_type", ("contributions", "expenditures"))
def test_columns_match_sample_header_order(data_type: str) -> None:
    assert _load_columns_for_data_type(data_type) == tuple(csv_headers(_SAMPLE_PATH_BY_DATA_TYPE[data_type]))


def test_semantic_path_round_trip_uses_config_field_mappings() -> None:
    for data_type in ("contributions", "expenditures"):
        semantic_path_to_column = _load_semantic_path_to_column_map(data_type)

        assert set(semantic_path_to_column.values()) == set(_load_columns_for_data_type(data_type))
        for semantic_path, column_name in semantic_path_to_column.items():
            assert _load_column_for_semantic_path(data_type, semantic_path) == column_name


def test_semantic_path_lookup_supports_in_local_and_shared_paths() -> None:
    assert _load_column_for_semantic_path("contributions", "in.received_by") == "Received_By"
    assert _load_column_for_semantic_path("contributions", "donor.address.city") == "City"
    assert _load_column_for_semantic_path("expenditures", "transaction.code") == "ExpenditureCode"


def test_columns_for_unsupported_type_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported IN data type"):
        _load_columns_for_data_type("loans")


def test_missing_semantic_path_raises() -> None:
    with pytest.raises(RuntimeError, match="No IN field mapping found"):
        _load_column_for_semantic_path("expenditures", "donor.name.first")
