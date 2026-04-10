from __future__ import annotations

from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions._test_helpers import nested_keys, read, source_block_by_name
from domains.campaign_finance.jurisdictions.states.WA.scraper import (
    _load_column_for_semantic_path,
    _load_columns_for_data_type,
    _load_wa_config,
    _load_wa_data_source_blocks,
)

REPO_ROOT = Path(__file__).resolve().parents[6]
WA_DIR = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "WA"
CONFIG_PATH = WA_DIR / "config.yaml"


def _expected_columns_from_config(source_name: str) -> tuple[str, ...]:
    config_text = read(CONFIG_PATH)
    source_block = source_block_by_name(config_text, source_name)
    return tuple(nested_keys(source_block, "field_mappings"))


def test_config_loads_successfully() -> None:
    config = _load_wa_config()

    assert config.jurisdiction.code == "WA"
    assert config.jurisdiction.name == "Washington"
    assert config.jurisdiction.type == "state"
    assert config.jurisdiction.fips == "53"


def test_data_source_blocks_include_expected_transaction_types() -> None:
    blocks = _load_wa_data_source_blocks()
    names = {block.name for block in blocks}

    assert names == {
        "WA Legislature Sponsor Directory",
        "WA PDC Contributions",
        "WA PDC Expenditures",
        "WA PDC Independent Expenditures",
        "WA PDC Loans",
    }


def test_columns_for_contributions_derive_from_config_order() -> None:
    columns = _load_columns_for_data_type("contributions")

    assert columns == _expected_columns_from_config("WA PDC Contributions")


def test_columns_for_expenditures_derive_from_config_order() -> None:
    columns = _load_columns_for_data_type("expenditures")

    assert columns == _expected_columns_from_config("WA PDC Expenditures")


def test_columns_for_loans_derive_from_config_order() -> None:
    columns = _load_columns_for_data_type("loans")

    assert columns == _expected_columns_from_config("WA PDC Loans")


def test_columns_for_independent_expenditures_derive_from_config_order() -> None:
    columns = _load_columns_for_data_type("independent_expenditures")

    assert columns == _expected_columns_from_config("WA PDC Independent Expenditures")


def test_independent_expenditure_mapping_supports_standard_loader_aliases() -> None:
    assert _load_column_for_semantic_path("independent_expenditures", "committee.id") == "sponsor_id"
    assert _load_column_for_semantic_path("independent_expenditures", "committee.name") == "sponsor_name"
    assert _load_column_for_semantic_path("independent_expenditures", "payee.name") == "vendor_name"
    assert _load_column_for_semantic_path("independent_expenditures", "transaction.amount") == "expenditure_amount"
    assert _load_column_for_semantic_path("independent_expenditures", "transaction.support_oppose") == "for_or_against"

    with pytest.raises(RuntimeError, match="No WA field mapping found"):
        _load_column_for_semantic_path("independent_expenditures", "wa.ie.sponsor_name")


def test_coverage_fields_match_wa_research_decisions() -> None:
    config = _load_wa_config()

    for source in config.data_sources:
        assert source.coverage.covers_sub_jurisdictions is (source.name != "WA Legislature Sponsor Directory")


def test_columns_for_unsupported_type_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported WA data type"):
        _load_columns_for_data_type("pledges")
