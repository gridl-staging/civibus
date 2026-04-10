"""Tests for NY CLI module."""

from __future__ import annotations

from domains.campaign_finance.jurisdictions.states.NY.scraper.cli import (
    _SUPPORTED_DATA_TYPES,
    _validate_data_type,
)

import pytest


class TestNYCLIContract:
    """Verify CLI contract for runner integration."""

    def test_supported_data_types_are_contributions_and_expenditures(self) -> None:
        assert _SUPPORTED_DATA_TYPES == ("contributions", "expenditures")

    def test_validate_data_type_accepts_valid_types(self) -> None:
        assert _validate_data_type("contributions") == "contributions"
        assert _validate_data_type("expenditures") == "expenditures"

    def test_validate_data_type_rejects_invalid_type(self) -> None:
        with pytest.raises(ValueError, match="Unsupported NY data type"):
            _validate_data_type("loans")
