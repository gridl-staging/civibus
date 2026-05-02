"""Tests for AL scraper config helpers (__init__.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from domains.campaign_finance.jurisdictions._test_helpers import nested_keys, read, source_block_by_name
from domains.campaign_finance.jurisdictions.states.AL.scraper import (
    _load_al_config,
    _load_api_base_url_for_data_type,
    _load_column_for_semantic_path,
    _load_columns_for_data_type,
    _load_data_source_for_data_type,
    _load_data_source_name_for_data_type,
    _load_data_source_url_for_data_type,
    load_supported_data_types,
)

REPO_ROOT = Path(__file__).resolve().parents[6]
AL_DIR = REPO_ROOT / "domains" / "campaign_finance" / "jurisdictions" / "states" / "AL"
CONFIG_PATH = AL_DIR / "config.yaml"


def _expected_columns_from_config(source_name: str) -> tuple[str, ...]:
    config_text = read(CONFIG_PATH)
    source_block = source_block_by_name(config_text, source_name)
    return tuple(nested_keys(source_block, "field_mappings"))


def test_config_loads_successfully() -> None:
    config = _load_al_config()
    assert config.jurisdiction.code == "AL"
    assert config.jurisdiction.name == "Alabama"


def test_contributions_use_contribution_data_source() -> None:
    ds = _load_data_source_for_data_type("contributions")
    assert ds.name == "AL FCPA Campaign Finance — Contributions"


def test_expenditures_use_expenditure_data_source() -> None:
    ds = _load_data_source_for_data_type("expenditures")
    assert ds.name == "AL FCPA Campaign Finance — Expenditures"


def test_columns_derive_from_config_order() -> None:
    assert _load_columns_for_data_type("contributions") == _expected_columns_from_config(
        "AL FCPA Campaign Finance — Contributions"
    )
    assert _load_columns_for_data_type("expenditures") == _expected_columns_from_config(
        "AL FCPA Campaign Finance — Expenditures"
    )


def test_supported_data_types_include_contributions_and_expenditures() -> None:
    supported = load_supported_data_types()
    assert "contributions" in supported
    assert "expenditures" in supported


def test_semantic_path_resolution_for_transaction_fields() -> None:
    assert _load_column_for_semantic_path("contributions", "transaction.date") == "TRANSACTIONDATE"
    assert _load_column_for_semantic_path("contributions", "transaction.amount") == "AMOUNT"
    assert _load_column_for_semantic_path("expenditures", "transaction.date") == "TRANSACTIONDATE"
    assert _load_column_for_semantic_path("expenditures", "transaction.amount") == "AMOUNT"


def test_api_base_url_resolution() -> None:
    url = _load_api_base_url_for_data_type("contributions")
    assert "fcpa.alabamavotes.gov" in url


def test_data_source_name_resolution() -> None:
    assert "Contributions" in _load_data_source_name_for_data_type("contributions")
    assert "Expenditures" in _load_data_source_name_for_data_type("expenditures")


def test_data_source_url_resolution() -> None:
    url = _load_data_source_url_for_data_type("contributions")
    assert "fcpa.alabamavotes.gov" in url


def test_unsupported_data_type_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported AL data type"):
        _load_columns_for_data_type("debts")
