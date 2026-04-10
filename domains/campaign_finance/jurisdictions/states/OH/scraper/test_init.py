from __future__ import annotations

from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions._test_helpers import csv_headers
from domains.campaign_finance.jurisdictions.states.OH.scraper import (
    _load_bulk_download_url_for_data_type,
    _load_column_for_semantic_path,
    _load_columns_for_data_type,
    _load_data_source_for_data_type,
    _load_oh_config,
    _load_oh_data_source_blocks,
)

REPO_ROOT = Path(__file__).resolve().parents[6]
OH_DIR = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "OH"
CONTRIBUTIONS_SAMPLE_PATH = OH_DIR / "sample_rows" / "contributions_sample.csv"
EXPENDITURES_SAMPLE_PATH = OH_DIR / "sample_rows" / "expenditures_sample.csv"


def test_config_loads_successfully() -> None:
    config = _load_oh_config()

    assert config.jurisdiction.code == "OH"
    assert config.jurisdiction.name == "Ohio"
    assert config.jurisdiction.type == "state"
    assert config.jurisdiction.fips == "39"


def test_last_verified_working_is_null_while_live_apex_verification_is_deferred() -> None:
    config = _load_oh_config()

    assert all(data_source.last_verified_working is None for data_source in config.data_sources)


def test_data_source_blocks_include_only_expected_oh_shapes() -> None:
    blocks = _load_oh_data_source_blocks()
    names = {block.name for block in blocks}

    assert names == {
        "OH SOS Campaign Finance — Contributions",
        "OH SOS Campaign Finance — Expenditures",
    }


def test_load_data_source_for_data_type_returns_expected_source() -> None:
    assert _load_data_source_for_data_type("contributions").name == "OH SOS Campaign Finance — Contributions"
    assert _load_data_source_for_data_type("expenditures").name == "OH SOS Campaign Finance — Expenditures"


def test_columns_for_contributions_match_sample_header_order() -> None:
    columns = _load_columns_for_data_type("contributions")

    assert columns == tuple(csv_headers(CONTRIBUTIONS_SAMPLE_PATH))


def test_columns_for_expenditures_match_sample_header_order() -> None:
    columns = _load_columns_for_data_type("expenditures")

    assert columns == tuple(csv_headers(EXPENDITURES_SAMPLE_PATH))


def test_semantic_path_lookup_supports_oh_local_and_shared_paths() -> None:
    assert _load_column_for_semantic_path("contributions", "oh.report_description") == "REPORT_DESCRIPTION"
    assert _load_column_for_semantic_path("contributions", "donor.name.first") == "FIRST_NAME"


def test_bulk_download_url_accessor_reads_from_data_source_config() -> None:
    expected_url = _load_data_source_for_data_type("contributions").bulk_download_url

    assert _load_bulk_download_url_for_data_type("contributions") == expected_url


def test_columns_for_unsupported_type_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported OH data type"):
        _load_columns_for_data_type("loans")


def test_missing_semantic_path_raises() -> None:
    with pytest.raises(RuntimeError, match="No OH field mapping found"):
        _load_column_for_semantic_path("expenditures", "donor.name.first")
