from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

from domains.campaign_finance.jurisdictions.states.KY.scraper import load
from domains.campaign_finance.jurisdictions.states.KY.scraper.load import (
    load_ky_contributions_with_filings,
    load_ky_expenditures_with_filings,
)

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTIONS_PATH = _FIXTURE_DIR / "sample_contributions.csv"
_SAMPLE_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_expenditures.csv"


def test_public_load_functions_dispatch_to_internal_loader(monkeypatch) -> None:
    internal = MagicMock()
    monkeypatch.setattr(load, "_load_ky_with_filings", internal)
    conn = MagicMock()

    load_ky_contributions_with_filings(conn, _SAMPLE_CONTRIBUTIONS_PATH, year_from=2022, limit=5)
    load_ky_expenditures_with_filings(conn, _SAMPLE_EXPENDITURES_PATH, year_from=2022, limit=6)

    assert internal.call_count == 2
    assert internal.call_args_list[0].kwargs["data_type"] == "contributions"
    assert internal.call_args_list[1].kwargs["data_type"] == "expenditures"


def test_parse_optional_ky_date_accepts_mmddyyyy() -> None:
    assert load._parse_optional_ky_date("03/29/2026") == date(2026, 3, 29)


def test_parse_optional_ky_date_returns_none_for_empty() -> None:
    assert load._parse_optional_ky_date(None) is None
    assert load._parse_optional_ky_date("") is None


def test_parse_optional_ky_date_accepts_upstream_future_date() -> None:
    # KREF CSV for 2022 Primary contains Receipt Date "9/30/2041" (data entry
    # error, likely 9/30/2021). The parser must accept it without raising —
    # upstream anomalies are preserved, not filtered. See
    # docs/reference/research/2026_04_29_ky_freshness_attribution.md.
    assert load._parse_optional_ky_date("9/30/2041") == date(2041, 9, 30)


def test_parse_optional_ky_date_accepts_iso_format() -> None:
    assert load._parse_optional_ky_date("2026-02-19") == date(2026, 2, 19)


def test_parse_required_ky_amount_accepts_decimal_format() -> None:
    assert load._parse_required_ky_amount("1234.50", "Amount") == Decimal("1234.50")


def test_parse_required_ky_amount_accepts_currency_format() -> None:
    assert load._parse_required_ky_amount("$1,234.50", "Amount") == Decimal("1234.50")


class TestKyIsIndependentExpenditure:
    """Unit tests for _ky_is_independent_expenditure."""

    def test_true_value_is_ie(self) -> None:
        row = {"Is Independent Expenditure": "True"}
        assert load._ky_is_independent_expenditure(row) is True

    def test_yes_value_is_ie(self) -> None:
        row = {"Is Independent Expenditure": "Yes"}
        assert load._ky_is_independent_expenditure(row) is True

    def test_y_value_is_ie(self) -> None:
        row = {"Is Independent Expenditure": "Y"}
        assert load._ky_is_independent_expenditure(row) is True

    def test_one_value_is_ie(self) -> None:
        row = {"Is Independent Expenditure": "1"}
        assert load._ky_is_independent_expenditure(row) is True

    def test_case_insensitive(self) -> None:
        row = {"Is Independent Expenditure": "true"}
        assert load._ky_is_independent_expenditure(row) is True

    def test_empty_is_not_ie(self) -> None:
        row = {"Is Independent Expenditure": ""}
        assert load._ky_is_independent_expenditure(row) is False

    def test_none_is_not_ie(self) -> None:
        row = {"Is Independent Expenditure": None}
        assert load._ky_is_independent_expenditure(row) is False

    def test_false_value_is_not_ie(self) -> None:
        row = {"Is Independent Expenditure": "False"}
        assert load._ky_is_independent_expenditure(row) is False

    def test_no_value_is_not_ie(self) -> None:
        row = {"Is Independent Expenditure": "No"}
        assert load._ky_is_independent_expenditure(row) is False

    def test_n_value_is_not_ie(self) -> None:
        row = {"Is Independent Expenditure": "N"}
        assert load._ky_is_independent_expenditure(row) is False


class TestKyExpenditureIeClassification:
    """Verify IE rows from fixture get correct transaction_type via upsert wiring."""

    def test_ie_row_gets_independent_expenditure_type(self, monkeypatch) -> None:
        """IE row should produce transaction_type='Independent Expenditure'."""
        captured_transactions = []
        monkeypatch.setattr(
            load,
            "upsert_transaction",
            lambda conn, txn: captured_transactions.append(txn),
        )
        # Stub all DB calls used by _upsert_ky_transaction_with_filing
        monkeypatch.setattr(
            load,
            "resolve_transaction_counterparty_ids",
            lambda conn, **kw: (None, None),
        )
        monkeypatch.setattr(load, "_resolve_ky_transaction_address_id", lambda conn, **kw: None)

        ie_row = {
            "Recipient Last Name": "",
            "Recipient First Name": "",
            "Organization Name": "CITIZENS FOR LIBERTY PAC",
            "Purpose": "Television advertising",
            "Occupation": "",
            "Disbursement Code": "MONETARY",
            "Disbursement Amount": "25000.00",
            "Disbursement Date": "04/01/2026",
            "From Candidate First Name": "John",
            "From Candidate Last Name": "Smith",
            "From Organization Name": "",
            "Statement Type": "PRE-PRIMARY",
            "Office Sought": "GOVERNOR",
            "Election Date": "5/19/2026",
            "Election Type": "PRIMARY",
            "Is Independent Expenditure": "True",
        }
        filing_id, committee_id, source_record_id = uuid4(), uuid4(), uuid4()
        conn = MagicMock()
        load._upsert_ky_transaction_with_filing(
            conn,
            ie_row,
            filing_id=filing_id,
            committee_id=committee_id,
            source_record_id=source_record_id,
            data_type="expenditures",
        )
        assert len(captured_transactions) == 1
        assert captured_transactions[0].transaction_type == "Independent Expenditure"
        assert captured_transactions[0].support_oppose is None

    def test_non_ie_row_stays_expenditure(self, monkeypatch) -> None:
        """Non-IE row should keep transaction_type='expenditure'."""
        captured_transactions = []
        monkeypatch.setattr(
            load,
            "upsert_transaction",
            lambda conn, txn: captured_transactions.append(txn),
        )
        monkeypatch.setattr(
            load,
            "resolve_transaction_counterparty_ids",
            lambda conn, **kw: (None, None),
        )
        monkeypatch.setattr(load, "_resolve_ky_transaction_address_id", lambda conn, **kw: None)

        non_ie_row = {
            "Recipient Last Name": "",
            "Recipient First Name": "",
            "Organization Name": "BLUEGRASS PRINTING INC",
            "Purpose": "Campaign literature",
            "Occupation": "",
            "Disbursement Code": "MONETARY",
            "Disbursement Amount": "800.00",
            "Disbursement Date": "12/15/2021",
            "From Candidate First Name": "Jane",
            "From Candidate Last Name": "Doe",
            "From Organization Name": "",
            "Statement Type": "ANNUAL",
            "Office Sought": "GOVERNOR",
            "Election Date": "5/19/2026",
            "Election Type": "PRIMARY",
            "Is Independent Expenditure": "",
        }
        filing_id, committee_id, source_record_id = uuid4(), uuid4(), uuid4()
        conn = MagicMock()
        load._upsert_ky_transaction_with_filing(
            conn,
            non_ie_row,
            filing_id=filing_id,
            committee_id=committee_id,
            source_record_id=source_record_id,
            data_type="expenditures",
        )
        assert len(captured_transactions) == 1
        assert captured_transactions[0].transaction_type == "expenditure"
        assert captured_transactions[0].support_oppose is None
