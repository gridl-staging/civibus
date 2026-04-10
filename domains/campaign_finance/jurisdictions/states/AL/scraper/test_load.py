"""Tests for AL load module."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

from domains.campaign_finance.jurisdictions.states.AL.scraper import load
from domains.campaign_finance.jurisdictions.states.AL.scraper.load import (
    load_al_contributions_with_filings,
    load_al_expenditures_with_filings,
)

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.json"
_SAMPLE_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_expenditures.json"


def test_public_load_functions_dispatch_to_internal_loader(monkeypatch) -> None:
    """Both public load functions should delegate to _load_al_with_filings."""
    internal = MagicMock()
    monkeypatch.setattr(load, "_load_al_with_filings", internal)
    conn = MagicMock()

    load_al_contributions_with_filings(conn, _SAMPLE_CONTRIBUTIONS_PATH, year_from=2022, limit=5)
    load_al_expenditures_with_filings(conn, _SAMPLE_EXPENDITURES_PATH, year_from=2022, limit=6)

    assert internal.call_count == 2
    assert internal.call_args_list[0].kwargs["data_type"] == "contributions"
    assert internal.call_args_list[1].kwargs["data_type"] == "expenditures"


def test_parse_optional_al_date_accepts_mmddyyyy() -> None:
    assert load._parse_optional_al_date("03/29/2026") == date(2026, 3, 29)


def test_parse_optional_al_date_returns_none_for_empty() -> None:
    assert load._parse_optional_al_date(None) is None
    assert load._parse_optional_al_date("") is None


def test_parse_required_al_amount_accepts_currency_format() -> None:
    assert load._parse_required_al_amount("$1,234.50", "amount") == Decimal("1234.50")


def test_parse_required_al_amount_accepts_plain_decimal() -> None:
    assert load._parse_required_al_amount("500.00", "amount") == Decimal("500.00")


def test_amendment_indicator_maps_values() -> None:
    assert load._amendment_indicator("N") == "N"
    assert load._amendment_indicator("Y") == "A"
    assert load._amendment_indicator("Yes") == "A"
    assert load._amendment_indicator(None) == "N"
    assert load._amendment_indicator("") == "N"
