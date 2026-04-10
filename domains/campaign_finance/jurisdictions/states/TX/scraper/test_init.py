from __future__ import annotations

from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions._test_helpers import nested_keys, read, source_block_by_name
from domains.campaign_finance.jurisdictions.states.TX.scraper import (
    _load_bulk_download_url_for_data_type,
    _load_column_for_semantic_path,
    _load_columns_for_data_type,
    _load_tx_config,
    _load_tx_data_source_blocks,
)

REPO_ROOT = Path(__file__).resolve().parents[6]
TX_DIR = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "TX"
CONFIG_PATH = TX_DIR / "config.yaml"
LAWS_PATH = TX_DIR / "laws.md"


def _expected_columns_from_config(source_name: str) -> tuple[str, ...]:
    config_text = read(CONFIG_PATH)
    source_block = source_block_by_name(config_text, source_name)
    return tuple(nested_keys(source_block, "field_mappings"))


def test_config_loads_successfully() -> None:
    config = _load_tx_config()

    assert config.jurisdiction.code == "TX"
    assert config.jurisdiction.name == "Texas"
    assert config.jurisdiction.type == "state"
    assert config.jurisdiction.fips == "48"


def test_data_source_blocks_include_expected_transaction_types() -> None:
    blocks = _load_tx_data_source_blocks()
    names = {block.name for block in blocks}

    assert names == {
        "TEC Campaign Finance — Contributions",
        "TEC Campaign Finance — Expenditures",
        "TEC Campaign Finance — Loans",
    }


def test_columns_for_contributions_derive_from_config_order() -> None:
    columns = _load_columns_for_data_type("contributions")

    assert columns == _expected_columns_from_config("TEC Campaign Finance — Contributions")


def test_columns_for_expenditures_derive_from_config_order() -> None:
    columns = _load_columns_for_data_type("expenditures")

    assert columns == _expected_columns_from_config("TEC Campaign Finance — Expenditures")


def test_columns_for_loans_derive_from_config_order() -> None:
    columns = _load_columns_for_data_type("loans")

    assert columns == _expected_columns_from_config("TEC Campaign Finance — Loans")


def test_contribution_mapping_stays_tx_local() -> None:
    assert _load_column_for_semantic_path("contributions", "tx.contributor_pac_fein") == "contributorPacFein"

    with pytest.raises(RuntimeError, match="No TX field mapping found"):
        _load_column_for_semantic_path("contributions", "donor.pac_fein")


def test_shared_name_semantic_paths_use_dotted_convention() -> None:
    assert _load_column_for_semantic_path("contributions", "donor.name.first") == "contributorNameFirst"
    assert _load_column_for_semantic_path("expenditures", "payee.name.organization") == "payeeNameOrganization"
    assert _load_column_for_semantic_path("loans", "lender.name.last") == "lenderNameLast"

    with pytest.raises(RuntimeError, match="No TX field mapping found"):
        _load_column_for_semantic_path("contributions", "donor.name_first")


def test_coverage_and_bulk_download_fields_match_tx_research_decisions() -> None:
    config = _load_tx_config()

    assert config.laws.itemization_threshold == 110

    for source in config.data_sources:
        transaction_type = source.coverage.transaction_types[0]
        assert source.coverage.start_year == 2000
        assert source.coverage.covers_sub_jurisdictions is True
        assert _load_bulk_download_url_for_data_type(transaction_type) == source.bulk_download_url


def test_laws_markdown_matches_2026_threshold_adjustment_effective_date() -> None:
    laws_text = read(LAWS_PATH)

    assert "effective January 1, 2026" in laws_text
    assert "March 16, 2026" not in laws_text
    assert "$34,890" in laws_text


def test_columns_for_unsupported_type_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported TX data type"):
        _load_columns_for_data_type("pledges")
