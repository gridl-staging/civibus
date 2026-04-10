from __future__ import annotations

from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions._test_helpers import nested_keys, read, source_block_by_name
from domains.campaign_finance.jurisdictions.states.NE.scraper import (
    _load_bulk_download_url_for_data_type,
    _load_column_for_semantic_path,
    _load_columns_for_data_type,
    _load_data_source_for_data_type,
    _load_ne_config,
)

REPO_ROOT = Path(__file__).resolve().parents[6]
NE_DIR = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "NE"
CONFIG_PATH = NE_DIR / "config.yaml"


def _expected_columns_from_config(source_name: str) -> tuple[str, ...]:
    config_text = read(CONFIG_PATH)
    source_block = source_block_by_name(config_text, source_name)
    return tuple(nested_keys(source_block, "field_mappings"))


def test_config_loads_successfully() -> None:
    config = _load_ne_config()

    assert config.jurisdiction.code == "NE"
    assert config.jurisdiction.name == "Nebraska"


def test_contributions_and_loans_share_the_same_data_source() -> None:
    assert _load_data_source_for_data_type("contributions").name == "NE NADC Campaign Finance — Contributions and Loans"
    assert _load_data_source_for_data_type("loans").name == "NE NADC Campaign Finance — Contributions and Loans"


def test_expenditures_use_the_expenditure_data_source() -> None:
    assert _load_data_source_for_data_type("expenditures").name == "NE NADC Campaign Finance — Expenditures"


def test_columns_derive_from_config_order() -> None:
    assert _load_columns_for_data_type("contributions") == _expected_columns_from_config(
        "NE NADC Campaign Finance — Contributions and Loans"
    )
    assert _load_columns_for_data_type("loans") == _expected_columns_from_config(
        "NE NADC Campaign Finance — Contributions and Loans"
    )
    assert _load_columns_for_data_type("expenditures") == _expected_columns_from_config(
        "NE NADC Campaign Finance — Expenditures"
    )


def test_bulk_url_resolution_uses_expected_templates() -> None:
    assert _load_bulk_download_url_for_data_type("contributions", 2026).endswith("2026_ContributionLoanExtract.csv.zip")
    assert _load_bulk_download_url_for_data_type("loans", 2026).endswith("2026_ContributionLoanExtract.csv.zip")
    assert _load_bulk_download_url_for_data_type("expenditures", 2026).endswith("2026_ExpenditureExtract.csv.zip")


def test_semantic_path_resolution_for_transaction_fields() -> None:
    assert _load_column_for_semantic_path("contributions", "transaction.date") == "Receipt Date"
    assert _load_column_for_semantic_path("loans", "transaction.amount") == "Receipt Amount"
    assert _load_column_for_semantic_path("expenditures", "transaction.date") == "Expenditure Date"


def test_unsupported_data_type_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported NE data type"):
        _load_columns_for_data_type("debts")
