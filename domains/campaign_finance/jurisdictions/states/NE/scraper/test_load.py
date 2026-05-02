from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from domains.campaign_finance.jurisdictions.states.NE.scraper import load
from domains.campaign_finance.jurisdictions.states.NE.scraper.load import (
    load_ne_contributions_with_filings,
    load_ne_expenditures_with_filings,
    load_ne_loans_with_filings,
)

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_CONTRIBUTION_LOAN_PATH = _FIXTURE_DIR / "sample_contribution_loan.csv"
_SAMPLE_EXPENDITURES_PATH = _FIXTURE_DIR / "sample_expenditures.csv"


def test_public_load_functions_dispatch_to_internal_loader(monkeypatch) -> None:
    internal = MagicMock()
    monkeypatch.setattr(load, "_load_ne_with_filings", internal)
    conn = MagicMock()

    load_ne_contributions_with_filings(conn, _SAMPLE_CONTRIBUTION_LOAN_PATH, year=2026, year_from=2022, limit=5)
    load_ne_expenditures_with_filings(conn, _SAMPLE_EXPENDITURES_PATH, year=2026, year_from=2022, limit=6)
    load_ne_loans_with_filings(conn, _SAMPLE_CONTRIBUTION_LOAN_PATH, year=2026, year_from=2022, limit=7)

    assert internal.call_count == 3
    assert internal.call_args_list[0].kwargs["data_type"] == "contributions"
    assert internal.call_args_list[1].kwargs["data_type"] == "expenditures"
    assert internal.call_args_list[2].kwargs["data_type"] == "loans"


def test_parse_optional_ne_date_accepts_mmddyyyy() -> None:
    assert load._parse_optional_ne_date("03/29/2026") == date(2026, 3, 29)


def test_parse_required_ne_amount_accepts_currency_format() -> None:
    assert load._parse_required_ne_amount("$1,234.50", "Receipt Amount") == Decimal("1234.50")


class TestNeSupportOppose:
    """Unit tests for _ne_support_oppose."""

    def test_support_returns_s(self) -> None:
        row = {"Support Or Oppose": "Support"}
        assert load._ne_support_oppose(row) == "S"

    def test_oppose_returns_o(self) -> None:
        row = {"Support Or Oppose": "Oppose"}
        assert load._ne_support_oppose(row) == "O"

    def test_case_insensitive_support(self) -> None:
        row = {"Support Or Oppose": "SUPPORT"}
        assert load._ne_support_oppose(row) == "S"

    def test_case_insensitive_oppose(self) -> None:
        row = {"Support Or Oppose": "oppose"}
        assert load._ne_support_oppose(row) == "O"

    def test_s_shorthand(self) -> None:
        row = {"Support Or Oppose": "S"}
        assert load._ne_support_oppose(row) == "S"

    def test_o_shorthand(self) -> None:
        row = {"Support Or Oppose": "O"}
        assert load._ne_support_oppose(row) == "O"

    def test_empty_returns_none(self) -> None:
        row = {"Support Or Oppose": ""}
        assert load._ne_support_oppose(row) is None

    def test_none_returns_none(self) -> None:
        row = {"Support Or Oppose": None}
        assert load._ne_support_oppose(row) is None

    def test_unexpected_token_raises(self) -> None:
        row = {"Support Or Oppose": "Maybe"}
        with pytest.raises(ValueError, match="support/oppose"):
            load._ne_support_oppose(row)


class TestNeExpenditureIeClassification:
    """Verify IE rows from fixture get correct transaction_type and support_oppose."""

    def _stub_db_calls(self, monkeypatch) -> list:
        captured = []
        monkeypatch.setattr(
            load,
            "upsert_transaction",
            lambda conn, txn: captured.append(txn),
        )
        monkeypatch.setattr(
            load,
            "resolve_transaction_counterparty_ids",
            lambda conn, **kw: (None, None),
        )
        monkeypatch.setattr(load, "_resolve_ne_transaction_address_id", lambda conn, **kw: None)
        return captured

    def test_support_row_gets_ie_type_and_s(self, monkeypatch) -> None:
        captured = self._stub_db_calls(monkeypatch)
        row = {
            "Expenditure ID": "2003",
            "Org ID": "9001",
            "Filer Type": "Independent Committee",
            "Filer Name": "NE Citizens PAC",
            "Candidate Name": "",
            "Expenditure Transaction Type": "Independent Expenditure",
            "Expenditure Sub Type": "Unknown",
            "Expenditure Date": "03/25/2026",
            "Expenditure Amount": "5000.00",
            "Description": "TV ads supporting candidate",
            "Payee or Recipient or In-Kind Contributor Type": "Business",
            "Payee or Recipient or In-Kind Contributor Name": "MEDIA CORP",
            "First Name": "",
            "Middle Name": "",
            "Suffix": "",
            "Address 1": "300 MAIN ST",
            "Address 2": "",
            "City": "LINCOLN",
            "State": "NE",
            "Zip": "68501",
            "Filed Date": "03/26/2026",
            "Support Or Oppose": "Support",
            "Candidate Name or Ballot Issue": "Jane Smith",
            "Jurisdiction - Office - District or Ballot Description": "State Senate - District 5",
            "Amended": "N",
            "Employer": "",
            "Occupation": "",
            "Principal Place of Business": "",
        }
        filing_id, committee_id, source_record_id = uuid4(), uuid4(), uuid4()
        load._upsert_ne_transaction_with_filing(
            MagicMock(),
            row,
            filing_id=filing_id,
            committee_id=committee_id,
            source_record_id=source_record_id,
            data_type="expenditures",
        )
        assert len(captured) == 1
        assert captured[0].transaction_type == "Independent Expenditure"
        assert captured[0].support_oppose == "S"

    def test_oppose_row_gets_ie_type_and_o(self, monkeypatch) -> None:
        captured = self._stub_db_calls(monkeypatch)
        row = {
            "Expenditure ID": "2004",
            "Org ID": "9001",
            "Filer Type": "Independent Committee",
            "Filer Name": "NE Citizens PAC",
            "Candidate Name": "",
            "Expenditure Transaction Type": "Independent Expenditure",
            "Expenditure Sub Type": "Unknown",
            "Expenditure Date": "04/01/2026",
            "Expenditure Amount": "3500.00",
            "Description": "Mailers opposing candidate",
            "Payee or Recipient or In-Kind Contributor Type": "Business",
            "Payee or Recipient or In-Kind Contributor Name": "PRINT SHOP INC",
            "First Name": "",
            "Middle Name": "",
            "Suffix": "",
            "Address 1": "400 OAK AVE",
            "Address 2": "",
            "City": "OMAHA",
            "State": "NE",
            "Zip": "68101",
            "Filed Date": "04/02/2026",
            "Support Or Oppose": "Oppose",
            "Candidate Name or Ballot Issue": "Bob Jones",
            "Jurisdiction - Office - District or Ballot Description": "Governor",
            "Amended": "N",
            "Employer": "",
            "Occupation": "",
            "Principal Place of Business": "",
        }
        filing_id, committee_id, source_record_id = uuid4(), uuid4(), uuid4()
        load._upsert_ne_transaction_with_filing(
            MagicMock(),
            row,
            filing_id=filing_id,
            committee_id=committee_id,
            source_record_id=source_record_id,
            data_type="expenditures",
        )
        assert len(captured) == 1
        assert captured[0].transaction_type == "Independent Expenditure"
        assert captured[0].support_oppose == "O"

    def test_ie_transaction_type_with_null_support_oppose_gets_ie(self, monkeypatch) -> None:
        """IE classification should fire when transaction type says IE even without support/oppose."""
        captured = self._stub_db_calls(monkeypatch)
        row = {
            "Expenditure ID": "2005",
            "Org ID": "9001",
            "Filer Type": "Independent Committee",
            "Filer Name": "NE Citizens PAC",
            "Candidate Name": "",
            "Expenditure Transaction Type": "Independent Expenditure",
            "Expenditure Sub Type": "Unknown",
            "Expenditure Date": "03/25/2026",
            "Expenditure Amount": "1500.00",
            "Description": "IE with no support/oppose",
            "Payee or Recipient or In-Kind Contributor Type": "Business",
            "Payee or Recipient or In-Kind Contributor Name": "AD AGENCY LLC",
            "First Name": "",
            "Middle Name": "",
            "Suffix": "",
            "Address 1": "500 PINE ST",
            "Address 2": "",
            "City": "LINCOLN",
            "State": "NE",
            "Zip": "68501",
            "Filed Date": "03/26/2026",
            "Support Or Oppose": "",
            "Candidate Name or Ballot Issue": "",
            "Jurisdiction - Office - District or Ballot Description": "",
            "Amended": "N",
            "Employer": "",
            "Occupation": "",
            "Principal Place of Business": "",
        }
        filing_id, committee_id, source_record_id = uuid4(), uuid4(), uuid4()
        load._upsert_ne_transaction_with_filing(
            MagicMock(),
            row,
            filing_id=filing_id,
            committee_id=committee_id,
            source_record_id=source_record_id,
            data_type="expenditures",
        )
        assert len(captured) == 1
        assert captured[0].transaction_type == "Independent Expenditure"
        assert captured[0].support_oppose is None

    def test_blank_support_oppose_campaign_expense_stays_expenditure(self, monkeypatch) -> None:
        captured = self._stub_db_calls(monkeypatch)
        row = {
            "Expenditure ID": "2002",
            "Org ID": "8001",
            "Filer Type": "Candidate Committee",
            "Filer Name": "Committee B",
            "Candidate Name": "Candidate B",
            "Expenditure Transaction Type": "Campaign Expense",
            "Expenditure Sub Type": "Unknown",
            "Expenditure Date": "03/18/2026",
            "Expenditure Amount": "145.20",
            "Description": "new expense",
            "Payee or Recipient or In-Kind Contributor Type": "Individual",
            "Payee or Recipient or In-Kind Contributor Name": "RECIPIENT",
            "First Name": "DREW",
            "Middle Name": "",
            "Suffix": "",
            "Address 1": "202 MARKET ST",
            "Address 2": "",
            "City": "OMAHA",
            "State": "NE",
            "Zip": "68101",
            "Filed Date": "03/19/2026",
            "Support Or Oppose": "",
            "Candidate Name or Ballot Issue": "",
            "Jurisdiction - Office - District or Ballot Description": "",
            "Amended": "N",
            "Employer": "Self",
            "Occupation": "Consultant",
            "Principal Place of Business": "",
        }
        filing_id, committee_id, source_record_id = uuid4(), uuid4(), uuid4()
        load._upsert_ne_transaction_with_filing(
            MagicMock(),
            row,
            filing_id=filing_id,
            committee_id=committee_id,
            source_record_id=source_record_id,
            data_type="expenditures",
        )
        assert len(captured) == 1
        assert captured[0].transaction_type == "expenditure"
        assert captured[0].support_oppose is None
