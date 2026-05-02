"""Tests for NY scraper config helpers."""

from __future__ import annotations

import pytest

from domains.campaign_finance.jurisdictions.states.NY.scraper import (
    _load_bulk_download_url_for_data_type,
    _load_columns_for_data_type,
    _load_column_for_semantic_path,
    _load_data_source_for_data_type,
    _load_data_source_name_for_data_type,
    _load_ny_config,
)


class TestNYConfigLoading:
    """Test that config.yaml loads correctly and field mappings resolve."""

    def test_config_loads_successfully(self) -> None:
        config = _load_ny_config()
        assert config.jurisdiction.code == "NY"
        assert config.jurisdiction.name == "New York"

    def test_config_has_three_data_sources(self) -> None:
        config = _load_ny_config()
        assert len(config.data_sources) == 3

    def test_config_has_exactly_one_source_per_supported_data_type(self) -> None:
        config = _load_ny_config()
        sources_by_type: dict[str, list[str]] = {}
        for data_source in config.data_sources:
            for transaction_type in data_source.coverage.transaction_types:
                normalized = transaction_type.strip().lower()
                sources_by_type.setdefault(normalized, []).append(data_source.name)

        assert set(sources_by_type) == {"contributions", "expenditures", "independent_expenditures"}
        assert all(len(sources) == 1 for sources in sources_by_type.values())

    def test_contributions_has_45_columns(self) -> None:
        columns = _load_columns_for_data_type("contributions")
        assert len(columns) == 45

    def test_expenditures_has_45_columns(self) -> None:
        columns = _load_columns_for_data_type("expenditures")
        assert len(columns) == 45

    def test_ie_has_45_columns(self) -> None:
        columns = _load_columns_for_data_type("independent_expenditures")
        assert len(columns) == 45

    def test_ie_columns_match_expenditure_columns(self) -> None:
        ie_cols = _load_columns_for_data_type("independent_expenditures")
        exp_cols = _load_columns_for_data_type("expenditures")
        assert ie_cols == exp_cols

    def test_ie_payee_semantic_paths_match_expenditures(self) -> None:
        payee_paths = [
            "payee.org_name",
            "payee.first_name",
            "payee.middle_name",
            "payee.last_name",
            "payee.address.street1",
            "payee.address.city",
            "payee.address.state",
            "payee.address.zip",
        ]
        for path in payee_paths:
            ie_col = _load_column_for_semantic_path("independent_expenditures", path)
            exp_col = _load_column_for_semantic_path("expenditures", path)
            assert ie_col == exp_col, f"Mismatch for {path}: IE={ie_col}, expenditure={exp_col}"

    def test_ie_bulk_url_contains_parent_dataset(self) -> None:
        url = _load_bulk_download_url_for_data_type("independent_expenditures")
        assert "e9ss-239a" in url

    def test_ie_data_source_resolves(self) -> None:
        ds = _load_data_source_for_data_type("independent_expenditures")
        assert ds.name == "NY BoE Independent Expenditures"

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
