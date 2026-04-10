from __future__ import annotations

from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions._test_helpers import nested_keys, read, source_block_by_name
from domains.campaign_finance.jurisdictions.states.PA.scraper import (
    _load_bulk_download_url_for_data_type,
    _load_column_for_semantic_path,
    _load_columns_for_data_type,
    _load_data_source_for_data_type,
    _load_pa_config,
    _load_pa_data_source_blocks,
)

REPO_ROOT = Path(__file__).resolve().parents[6]
PA_DIR = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "PA"
CONFIG_PATH = PA_DIR / "config.yaml"


def _expected_columns_from_config(source_name: str) -> tuple[str, ...]:
    config_text = read(CONFIG_PATH)
    source_block = source_block_by_name(config_text, source_name)
    return tuple(nested_keys(source_block, "field_mappings"))


def test_config_loads_successfully() -> None:
    config = _load_pa_config()

    assert config.jurisdiction.code == "PA"
    assert config.jurisdiction.name == "Pennsylvania"
    assert config.jurisdiction.type == "state"
    assert config.jurisdiction.fips == "42"


def test_data_source_blocks_include_expected_data_sources() -> None:
    blocks = _load_pa_data_source_blocks()
    names = {block.name for block in blocks}

    assert names == {
        "PA DOS Campaign Finance — Contributions",
        "PA DOS Campaign Finance — Expenditures",
        "PA DOS Campaign Finance — Debt",
        "PA DOS Campaign Finance — Receipts",
        "PA DOS Campaign Finance — Filing Index",
    }


def test_load_data_source_for_data_type_returns_expected_source() -> None:
    assert _load_data_source_for_data_type("contributions").name == "PA DOS Campaign Finance — Contributions"
    assert _load_data_source_for_data_type("expenditures").name == "PA DOS Campaign Finance — Expenditures"
    assert _load_data_source_for_data_type("debts").name == "PA DOS Campaign Finance — Debt"
    assert _load_data_source_for_data_type("receipts").name == "PA DOS Campaign Finance — Receipts"
    assert _load_data_source_for_data_type("filings").name == "PA DOS Campaign Finance — Filing Index"


def test_columns_for_contributions_derive_from_config_order() -> None:
    columns = _load_columns_for_data_type("contributions")

    assert columns == _expected_columns_from_config("PA DOS Campaign Finance — Contributions")


def test_columns_for_expenditures_derive_from_config_order() -> None:
    columns = _load_columns_for_data_type("expenditures")

    assert columns == _expected_columns_from_config("PA DOS Campaign Finance — Expenditures")


def test_columns_for_debts_derive_from_config_order() -> None:
    columns = _load_columns_for_data_type("debts")

    assert columns == _expected_columns_from_config("PA DOS Campaign Finance — Debt")


def test_columns_for_receipts_derive_from_config_order() -> None:
    columns = _load_columns_for_data_type("receipts")

    assert columns == _expected_columns_from_config("PA DOS Campaign Finance — Receipts")


def test_columns_for_filings_derive_from_config_order() -> None:
    columns = _load_columns_for_data_type("filings")

    assert columns == _expected_columns_from_config("PA DOS Campaign Finance — Filing Index")


def test_campaign_finance_id_mapping_captures_header_capitalization_difference() -> None:
    assert _load_column_for_semantic_path("contributions", "pa.campaign_finance_id") == "CampaignFinanceID"
    assert _load_column_for_semantic_path("filings", "pa.campaignfinance_id") == "CampaignfinanceID"

    with pytest.raises(RuntimeError, match="No PA field mapping found"):
        _load_column_for_semantic_path("filings", "pa.campaign_finance_id")


def test_yearly_bulk_download_url_resolution_uses_template_and_2025_exception() -> None:
    assert _load_bulk_download_url_for_data_type("contributions", 2026).endswith("/2026.zip")
    assert (
        _load_bulk_download_url_for_data_type("contributions", 2025)
        == "https://www.pa.gov/content/dam/copapwp-pagov/en/dos/resources/voting-and-elections/campaign-finance/campaign-finance-data/2025%20campaign%20finance%20full%20export%20.zip"
    )


def test_filing_index_known_issue_documents_amendment_inheritance_dependency() -> None:
    filing_source = _load_data_source_for_data_type("filings")

    assert any(
        "CampaignFinanceID to CampaignfinanceID join" in issue and "amendment" in issue.lower()
        for issue in filing_source.known_issues
    )


def test_columns_for_unsupported_type_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported PA data type"):
        _load_columns_for_data_type("independent_expenditures")
