from __future__ import annotations

from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions._test_helpers import nested_keys, read, source_block_by_name
from domains.campaign_finance.jurisdictions.states.KY.scraper import (
    _load_api_base_url_for_data_type,
    _load_column_for_semantic_path,
    _load_columns_for_data_type,
    _load_data_source_for_data_type,
    _load_ky_config,
    load_supported_data_types,
)

REPO_ROOT = Path(__file__).resolve().parents[6]
KY_DIR = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "KY"
CONFIG_PATH = KY_DIR / "config.yaml"


def _expected_columns_from_config(source_name: str) -> tuple[str, ...]:
    config_text = read(CONFIG_PATH)
    source_block = source_block_by_name(config_text, source_name)
    return tuple(nested_keys(source_block, "field_mappings"))


def test_config_loads_successfully() -> None:
    config = _load_ky_config()

    assert config.jurisdiction.code == "KY"
    assert config.jurisdiction.name == "Kentucky"


def test_contributions_use_the_contributions_data_source() -> None:
    ds = _load_data_source_for_data_type("contributions")
    assert ds.name == "KY KREF Campaign Finance — Contributions"


def test_expenditures_use_the_expenditure_data_source() -> None:
    ds = _load_data_source_for_data_type("expenditures")
    assert ds.name == "KY KREF Campaign Finance — Expenditures"


def test_columns_derive_from_config_order() -> None:
    assert _load_columns_for_data_type("contributions") == _expected_columns_from_config(
        "KY KREF Campaign Finance — Contributions"
    )
    assert _load_columns_for_data_type("expenditures") == _expected_columns_from_config(
        "KY KREF Campaign Finance — Expenditures"
    )


def test_semantic_path_resolution_for_transaction_fields() -> None:
    assert _load_column_for_semantic_path("contributions", "transaction.date") == "Receipt Date"
    assert _load_column_for_semantic_path("contributions", "transaction.amount") == "Amount"
    assert _load_column_for_semantic_path("expenditures", "transaction.date") == "Disbursement Date"
    assert _load_column_for_semantic_path("expenditures", "transaction.amount") == "Disbursement Amount"


def test_api_base_url_resolution() -> None:
    url = _load_api_base_url_for_data_type("contributions")
    assert url == "https://secure.kentucky.gov/kref/publicsearch"


def test_supported_data_types() -> None:
    supported = load_supported_data_types()
    assert "contributions" in supported
    assert "expenditures" in supported


def test_unsupported_data_type_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported KY data type"):
        _load_columns_for_data_type("debts")
