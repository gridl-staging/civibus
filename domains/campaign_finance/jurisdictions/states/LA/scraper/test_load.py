from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

from domains.campaign_finance.jurisdictions.states.LA.scraper import load
from domains.campaign_finance.jurisdictions.states.LA.scraper.load import (
    load_la_contributions_with_filings,
    load_la_expenditures_with_filings,
    load_la_loans_with_filings,
)

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.csv"
_SAMPLE_LOANS_PATH = _FIXTURE_DIR / "sample_loans.csv"
_SAMPLE_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_expenditures.csv"


def test_public_load_functions_dispatch_to_internal_loader(monkeypatch) -> None:
    internal = MagicMock()
    monkeypatch.setattr(load, "_load_la_with_filings", internal)
    conn = MagicMock()

    load_la_contributions_with_filings(conn, _SAMPLE_CONTRIBUTIONS_PATH, year=2026, year_from=2022, limit=5)
    load_la_expenditures_with_filings(conn, _SAMPLE_EXPENDITURES_PATH, year=2026, year_from=2022, limit=6)
    load_la_loans_with_filings(conn, _SAMPLE_LOANS_PATH, year=2026, year_from=2022, limit=7)

    assert internal.call_count == 3
    assert internal.call_args_list[0].kwargs["data_type"] == "contributions"
    assert internal.call_args_list[1].kwargs["data_type"] == "expenditures"
    assert internal.call_args_list[2].kwargs["data_type"] == "loans"


def test_parse_optional_la_date_accepts_mmddyyyy() -> None:
    assert load._parse_optional_la_date("03/29/2026") == date(2026, 3, 29)


def test_parse_required_la_amount_accepts_currency_format() -> None:
    assert load._parse_required_la_amount("$1,234.50", "ContributionAmt") == Decimal("1234.50")
