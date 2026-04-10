"""Unit tests for _resolve_ga_transaction_amount (no DB required).

Extracted from test_load.py so these pure-function tests run under
``make test`` (which filters out ``pytest.mark.integration``).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from domains.campaign_finance.jurisdictions.states.GA.scraper.load import (
    _resolve_ga_transaction_amount,
)


class TestResolveGaTransactionAmount:
    """Direct tests for the five code paths in _resolve_ga_transaction_amount."""

    def test_primary_nonzero_returns_primary(self) -> None:
        row = {"Cash_Amount": "25.0000", "In_Kind_Amount": "10.0000"}
        result = _resolve_ga_transaction_amount(row, "contributions")
        assert result == Decimal("25.0000")

    def test_primary_zero_secondary_nonzero_returns_secondary(self) -> None:
        row = {"Cash_Amount": "0.00", "In_Kind_Amount": "15.0000"}
        result = _resolve_ga_transaction_amount(row, "contributions")
        assert result == Decimal("15.0000")

    def test_primary_zero_secondary_zero_returns_primary(self) -> None:
        # Both zero: primary wins (the Decimal("0.00") path)
        row = {"Cash_Amount": "0.00", "In_Kind_Amount": "0.00"}
        result = _resolve_ga_transaction_amount(row, "contributions")
        assert result == Decimal("0.00")

    def test_primary_none_secondary_zero_returns_secondary(self) -> None:
        # Primary is None, secondary is zero: secondary wins
        # This is the only path where a zero secondary is returned
        row = {"In_Kind_Amount": "0.00"}
        result = _resolve_ga_transaction_amount(row, "contributions")
        assert result == Decimal("0.00")

    def test_both_none_raises_value_error(self) -> None:
        row: dict[str, object] = {}
        with pytest.raises(ValueError, match="missing both primary and secondary amount fields"):
            _resolve_ga_transaction_amount(row, "contributions")

    def test_expenditure_primary_nonzero_returns_paid(self) -> None:
        row = {"Paid": "100.0000", "Other": "50.0000"}
        result = _resolve_ga_transaction_amount(row, "expenditures")
        assert result == Decimal("100.0000")

    def test_expenditure_primary_zero_secondary_nonzero_returns_other(self) -> None:
        row = {"Paid": "0.00", "Other": "75.0000"}
        result = _resolve_ga_transaction_amount(row, "expenditures")
        assert result == Decimal("75.0000")
