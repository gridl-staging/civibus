"""Tests for AL load module."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

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
    assert load._parse_required_al_amount("$1,234.50", "AMOUNT") == Decimal("1234.50")


def test_parse_required_al_amount_accepts_plain_decimal() -> None:
    assert load._parse_required_al_amount("500.00", "AMOUNT") == Decimal("500.00")


def test_amendment_indicator_maps_values() -> None:
    assert load._amendment_indicator("N") == "N"
    assert load._amendment_indicator("Y") == "A"
    assert load._amendment_indicator("Yes") == "A"
    assert load._amendment_indicator(None) == "N"
    assert load._amendment_indicator("") == "N"


def test_al_is_independent_expenditure_true_for_assumed_token() -> None:
    row = {"EXPENDITURETYPE": "Independent Expenditure"}
    assert load._al_is_independent_expenditure(row) is True


def test_al_is_independent_expenditure_false_for_non_ie_token() -> None:
    row = {"EXPENDITURETYPE": "Campaign Expense"}
    assert load._al_is_independent_expenditure(row) is False


@pytest.mark.parametrize("raw_value", ["", None])
def test_al_is_independent_expenditure_false_for_blank_or_null(raw_value: str | None) -> None:
    row = {"EXPENDITURETYPE": raw_value}
    assert load._al_is_independent_expenditure(row) is False


def test_upsert_al_transaction_overrides_type_for_independent_expenditure(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[object] = []
    monkeypatch.setattr(load, "upsert_transaction", lambda _conn, txn: captured.append(txn))
    monkeypatch.setattr(load, "resolve_transaction_counterparty_ids", lambda _conn, **_kw: (None, None))
    monkeypatch.setattr(load, "_resolve_al_transaction_address_id", lambda _conn, **_kw: None)
    monkeypatch.setattr(load, "_counterparty_name_raw", lambda _row, **_kw: "SYNTHETIC PAYEE")
    monkeypatch.setattr(load, "_counterparty_employer", lambda _row, **_kw: None)
    monkeypatch.setattr(load, "_counterparty_occupation", lambda _row, **_kw: None)
    monkeypatch.setitem(load._AL_EXTRACT_FN, "expenditures", lambda _row: {"address": None})

    row = {
        "EXPENDITURETYPE": "Independent Expenditure",
        "EXPENDEDDATE": "03/29/2026",
        "AMOUNT": "500.00",
        "DESCRIPTION": "Synthetic IE test row",
        "AMENDED": "N",
    }
    load._upsert_al_transaction_with_filing(
        MagicMock(),
        row,
        filing_id=uuid4(),
        committee_id=uuid4(),
        source_record_id=uuid4(),
        data_type="expenditures",
    )

    assert len(captured) == 1
    assert captured[0].transaction_type == "Independent Expenditure"


def test_upsert_al_transaction_does_not_override_non_expenditures(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[object] = []
    monkeypatch.setattr(load, "upsert_transaction", lambda _conn, txn: captured.append(txn))
    monkeypatch.setattr(load, "resolve_transaction_counterparty_ids", lambda _conn, **_kw: (None, None))
    monkeypatch.setattr(load, "_resolve_al_transaction_address_id", lambda _conn, **_kw: None)
    monkeypatch.setattr(load, "_counterparty_name_raw", lambda _row, **_kw: "SYNTHETIC DONOR")
    monkeypatch.setattr(load, "_counterparty_employer", lambda _row, **_kw: None)
    monkeypatch.setattr(load, "_counterparty_occupation", lambda _row, **_kw: None)
    monkeypatch.setitem(load._AL_EXTRACT_FN, "contributions", lambda _row: {"address": None})

    row = {
        "EXPENDITURETYPE": "Independent Expenditure",
        "receivedDate": "03/29/2026",
        "AMOUNT": "300.00",
        "DESCRIPTION": "Synthetic contribution row",
        "AMENDED": "N",
    }
    load._upsert_al_transaction_with_filing(
        MagicMock(),
        row,
        filing_id=uuid4(),
        committee_id=uuid4(),
        source_record_id=uuid4(),
        data_type="contributions",
    )

    assert len(captured) == 1
    assert captured[0].transaction_type == "contribution"
