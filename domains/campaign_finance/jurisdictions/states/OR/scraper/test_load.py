"""Tests for OR DB loading helpers."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

from domains.campaign_finance.jurisdictions.states.OR.scraper import load
from domains.campaign_finance.jurisdictions.states.OR.scraper.load import (
    load_or_contributions_with_filings,
    load_or_expenditures_with_filings,
)
from domains.campaign_finance.jurisdictions.states.OR.scraper.parse import parse_contributions

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.xls"
_SAMPLE_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_expenditures.xls"


def test_public_load_functions_dispatch_to_internal_loader(monkeypatch) -> None:
    internal = MagicMock()
    monkeypatch.setattr(load, "_load_or_with_filings", internal)
    conn = MagicMock()

    load_or_contributions_with_filings(conn, _SAMPLE_CONTRIBUTIONS_PATH, year_from=2022, limit=5)
    load_or_expenditures_with_filings(conn, _SAMPLE_EXPENDITURES_PATH, year_from=2022, limit=6)

    assert internal.call_count == 2
    assert internal.call_args_list[0].kwargs["data_type"] == "contributions"
    assert internal.call_args_list[1].kwargs["data_type"] == "expenditures"


def test_parse_optional_or_date_accepts_mmddyyyy() -> None:
    assert load._parse_optional_or_date("03/29/2026") == date(2026, 3, 29)


def test_parse_optional_or_date_returns_none_for_empty() -> None:
    assert load._parse_optional_or_date(None) is None
    assert load._parse_optional_or_date("") is None


def test_parse_required_or_amount_accepts_plain_number() -> None:
    assert load._parse_required_or_amount("1234.50", "Amount") == Decimal("1234.50")


def test_parse_required_or_amount_accepts_currency_format() -> None:
    assert load._parse_required_or_amount("$1,234.50", "Amount") == Decimal("1234.50")


def test_upsert_or_transaction_with_filing_preserves_amended_status(monkeypatch) -> None:
    row = next(iter(parse_contributions(_SAMPLE_CONTRIBUTIONS_PATH, year_from=2022)))
    amended_row = dict(row)
    amended_row["Tran Status"] = "Amended"
    captured_transaction = None

    def _capture_transaction(_conn, transaction):
        nonlocal captured_transaction
        captured_transaction = transaction

    monkeypatch.setattr(load, "resolve_transaction_counterparty_ids", MagicMock(return_value=(None, None)))
    monkeypatch.setattr(load, "upsert_transaction", _capture_transaction)

    load._upsert_or_transaction_with_filing(
        MagicMock(),
        amended_row,
        filing_id=uuid4(),
        committee_id=uuid4(),
        source_record_id=uuid4(),
        data_type="contributions",
    )

    assert captured_transaction is not None
    assert captured_transaction.amendment_indicator == "A"
