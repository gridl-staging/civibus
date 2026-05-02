from __future__ import annotations

from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions._test_helpers import nested_keys, read, source_block_by_name
from domains.campaign_finance.jurisdictions.states.LA.scraper import (
    _load_bulk_download_url_for_data_type,
    _load_column_for_semantic_path,
    _load_columns_for_data_type,
    _load_data_source_for_data_type,
    _load_la_config,
    load_supported_data_types,
)

REPO_ROOT = Path(__file__).resolve().parents[6]
LA_DIR = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "LA"
CONFIG_PATH = LA_DIR / "config.yaml"


def _expected_columns_from_config(source_name: str) -> tuple[str, ...]:
    config_text = read(CONFIG_PATH)
    source_block = source_block_by_name(config_text, source_name)
    return tuple(nested_keys(source_block, "field_mappings"))


def test_config_loads_successfully() -> None:
    config = _load_la_config()

    assert config.jurisdiction.code == "LA"
    assert config.jurisdiction.name == "Louisiana"


def test_data_sources_match_la_types() -> None:
    assert _load_data_source_for_data_type("contributions").name == "LA Ethics Campaign Finance — Contributions"
    assert _load_data_source_for_data_type("loans").name == "LA Ethics Campaign Finance — Loans"
    assert _load_data_source_for_data_type("expenditures").name == "LA Ethics Campaign Finance — Expenditures"


def test_supported_data_types_pin_la_contract() -> None:
    assert load_supported_data_types() == ("contributions", "loans", "expenditures")


def test_columns_derive_from_config_order() -> None:
    assert _load_columns_for_data_type("contributions") == _expected_columns_from_config(
        "LA Ethics Campaign Finance — Contributions"
    )
    assert _load_columns_for_data_type("loans") == _expected_columns_from_config("LA Ethics Campaign Finance — Loans")
    assert _load_columns_for_data_type("expenditures") == _expected_columns_from_config(
        "LA Ethics Campaign Finance — Expenditures"
    )


def test_bulk_url_resolution_uses_expected_urls() -> None:
    assert _load_bulk_download_url_for_data_type("contributions").endswith("ContributionReports.zip")
    assert _load_bulk_download_url_for_data_type("loans").endswith("LoanReports.zip")
    assert _load_bulk_download_url_for_data_type("expenditures").endswith("ExpenditureReports.zip")


def test_semantic_path_resolution_for_transaction_fields() -> None:
    assert _load_column_for_semantic_path("contributions", "transaction.date") == "ContributionDate"
    assert _load_column_for_semantic_path("loans", "transaction.amount") == "LoanAmt"
    assert _load_column_for_semantic_path("expenditures", "transaction.date") == "ExpenditureDate"
    assert _load_column_for_semantic_path("expenditures", "la.report_code") == "ReportCode"
    assert _load_column_for_semantic_path("expenditures", "la.candidate_beneficiary") == "CandidateBeneficiary"


def test_unsupported_data_type_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported LA data type"):
        _load_columns_for_data_type("debts")
