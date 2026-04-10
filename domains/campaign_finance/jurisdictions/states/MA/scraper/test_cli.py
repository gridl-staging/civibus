"""Tests for MA CLI module."""

from __future__ import annotations

import pytest

from domains.campaign_finance.jurisdictions.states.MA.scraper.cli import (
    _SUPPORTED_DATA_TYPES,
    _validate_data_type,
)


class TestMACLIContract:
    """Verify CLI contract for runner integration."""

    def test_supported_data_types(self) -> None:
        assert _SUPPORTED_DATA_TYPES == ("contributions", "expenditures")

    def test_validate_data_type_accepts_valid(self) -> None:
        assert _validate_data_type("contributions") == "contributions"
        assert _validate_data_type("expenditures") == "expenditures"

    def test_validate_data_type_rejects_invalid(self) -> None:
        with pytest.raises(ValueError, match="Unsupported MA data type"):
            _validate_data_type("loans")
