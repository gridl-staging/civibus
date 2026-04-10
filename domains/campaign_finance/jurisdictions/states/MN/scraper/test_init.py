from __future__ import annotations

from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions._test_helpers import nested_keys, read, source_block_by_name
from domains.campaign_finance.jurisdictions.states.MN.scraper import (
    _load_column_for_semantic_path,
    _load_columns_for_data_type,
    _load_mn_config,
    _load_mn_data_source_blocks,
)

REPO_ROOT = Path(__file__).resolve().parents[6]
MN_DIR = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "MN"
CONFIG_PATH = MN_DIR / "config.yaml"


def _expected_columns_from_config(source_name: str) -> tuple[str, ...]:
    config_text = read(CONFIG_PATH)
    source_block = source_block_by_name(config_text, source_name)
    return tuple(nested_keys(source_block, "field_mappings"))


def test_config_loads_successfully() -> None:
    config = _load_mn_config()

    assert config.jurisdiction.code == "MN"
    assert config.jurisdiction.name == "Minnesota"
    assert config.jurisdiction.type == "state"
    assert config.jurisdiction.fips == "27"


def test_data_source_blocks_include_expected_transaction_types() -> None:
    blocks = _load_mn_data_source_blocks()
    names = {block.name for block in blocks}

    assert names == {
        "MN CFB Contributions (All)",
        "MN CFB Expenditures (All)",
        "MN CFB Independent Expenditures (All)",
    }


def test_columns_for_contributions_derive_from_config_order() -> None:
    columns = _load_columns_for_data_type("contributions")

    assert columns == _expected_columns_from_config("MN CFB Contributions (All)")


def test_columns_for_expenditures_derive_from_config_order() -> None:
    columns = _load_columns_for_data_type("expenditures")

    assert columns == _expected_columns_from_config("MN CFB Expenditures (All)")


def test_columns_for_independent_expenditures_derive_from_config_order() -> None:
    columns = _load_columns_for_data_type("independent_expenditures")

    assert columns == _expected_columns_from_config("MN CFB Independent Expenditures (All)")


def test_independent_expenditure_support_oppose_mapping_stays_mn_local() -> None:
    assert (
        _load_column_for_semantic_path("independent_expenditures", "mn.independent_expenditure.support_oppose")
        == "For /Against"
    )

    with pytest.raises(RuntimeError, match="No MN field mapping found"):
        _load_column_for_semantic_path("independent_expenditures", "transaction.support_oppose")


def test_coverage_fields_match_mn_research_decisions() -> None:
    config = _load_mn_config()

    for source in config.data_sources:
        assert source.coverage.start_year == 2015
        assert source.coverage.covers_sub_jurisdictions is False


def test_columns_for_unsupported_type_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported MN data type"):
        _load_columns_for_data_type("loans")
