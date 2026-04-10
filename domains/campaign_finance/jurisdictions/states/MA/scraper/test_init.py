"""Tests for MA scraper config helpers."""

from __future__ import annotations

import pytest

from domains.campaign_finance.jurisdictions.states.MA.scraper import (
    _load_bulk_download_url_template,
    _load_columns_for_data_type,
    _load_column_for_semantic_path,
    _load_data_source_name,
    _load_ma_config,
)


class TestMAConfigLoading:
    """Test that config.yaml loads correctly."""

    def test_config_loads_successfully(self) -> None:
        config = _load_ma_config()
        assert config.jurisdiction.code == "MA"
        assert config.jurisdiction.name == "Massachusetts"

    def test_config_has_one_data_source(self) -> None:
        config = _load_ma_config()
        # MA has a single source covering both contributions and expenditures.
        assert len(config.data_sources) == 1

    def test_contributions_has_21_columns(self) -> None:
        columns = _load_columns_for_data_type("contributions")
        assert len(columns) == 21

    def test_semantic_path_resolves_amount(self) -> None:
        col = _load_column_for_semantic_path("contributions", "transaction.amount")
        assert col == "Amount"

    def test_semantic_path_resolves_date(self) -> None:
        col = _load_column_for_semantic_path("contributions", "transaction.date")
        assert col == "Date"

    def test_bulk_download_url_has_year_placeholder(self) -> None:
        url = _load_bulk_download_url_template()
        assert "{year}" in url

    def test_data_source_name_includes_ocpf(self) -> None:
        name = _load_data_source_name()
        assert name == "MA OCPF Report Items (Contributions + Expenditures)"

    def test_unsupported_data_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported MA data type"):
            _load_columns_for_data_type("invalid_type")
