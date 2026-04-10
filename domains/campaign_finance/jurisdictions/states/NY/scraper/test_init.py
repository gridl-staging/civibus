"""Tests for NY scraper config helpers."""

from __future__ import annotations

import pytest

from domains.campaign_finance.jurisdictions.states.NY.scraper import (
    _load_bulk_download_url_for_data_type,
    _load_columns_for_data_type,
    _load_column_for_semantic_path,
    _load_data_source_name_for_data_type,
    _load_ny_config,
)


class TestNYConfigLoading:
    """Test that config.yaml loads correctly and field mappings resolve."""

    def test_config_loads_successfully(self) -> None:
        config = _load_ny_config()
        assert config.jurisdiction.code == "NY"
        assert config.jurisdiction.name == "New York"

    def test_config_has_two_data_sources(self) -> None:
        config = _load_ny_config()
        assert len(config.data_sources) == 2

    def test_contributions_has_45_columns(self) -> None:
        columns = _load_columns_for_data_type("contributions")
        assert len(columns) == 45

    def test_expenditures_has_45_columns(self) -> None:
        columns = _load_columns_for_data_type("expenditures")
        assert len(columns) == 45

    def test_semantic_path_resolves_committee_id(self) -> None:
        col = _load_column_for_semantic_path("contributions", "committee.id")
        assert col == "filer_id"

    def test_semantic_path_resolves_transaction_amount(self) -> None:
        col = _load_column_for_semantic_path("contributions", "transaction.amount")
        assert col == "org_amt"

    def test_semantic_path_resolves_transaction_date(self) -> None:
        col = _load_column_for_semantic_path("contributions", "transaction.date")
        assert col == "sched_date"

    def test_bulk_download_url_contains_dataset_id(self) -> None:
        url = _load_bulk_download_url_for_data_type("contributions")
        assert "4j2b-6a2j" in url

    def test_data_source_name_for_contributions(self) -> None:
        name = _load_data_source_name_for_data_type("contributions")
        assert name == "NY BoE Contributions"

    def test_unsupported_data_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported NY data type"):
            _load_columns_for_data_type("invalid_type")
