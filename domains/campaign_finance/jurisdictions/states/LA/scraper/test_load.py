from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

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


@pytest.mark.parametrize(("report_code", "schedule"), [("F305", "E-1"), ("F306", "E-4")])
def test_la_is_independent_expenditure_true_for_f305_f306_contract_rows(report_code: str, schedule: str) -> None:
    row = {"ReportCode": report_code, "Schedule": schedule}
    assert load._la_is_independent_expenditure(row) is True


@pytest.mark.parametrize("schedule", ["E-1", "E-2", "E-3", "E-4"])
def test_la_is_independent_expenditure_false_for_form_202_schedules(schedule: str) -> None:
    row = {"ReportCode": "F202", "Schedule": schedule}
    assert load._la_is_independent_expenditure(row) is False


@pytest.mark.parametrize("raw_value", ["", None])
def test_la_is_independent_expenditure_false_for_blank_or_null_report_code(raw_value: str | None) -> None:
    row = {"ReportCode": raw_value, "Schedule": "E-1"}
    assert load._la_is_independent_expenditure(row) is False


@pytest.mark.parametrize("report_code", ["X99", "F999", "UNKNOWN"])
def test_la_is_independent_expenditure_false_for_unknown_report_code(report_code: str) -> None:
    row = {"ReportCode": report_code, "Schedule": "E-1"}
    assert load._la_is_independent_expenditure(row) is False


def test_la_ie_classification_missing_report_code_is_not_ie() -> None:
    row: dict[str, str | None] = {"RecipientName": "VENDOR", "Schedule": "E-4"}
    assert load._la_is_independent_expenditure(row) is False


@pytest.mark.parametrize(
    ("data_type", "expected_transaction_type", "row"),
    [
        (
            "contributions",
            "contribution",
            {
                "FilerNumber": "99999",
                "FilerLastName": "TEST COMMITTEE",
                "FilerFirstName": "",
                "ReportCode": "F305",
                "ReportType": "AN",
                "ReportNumber": "1",
                "ContributorName": "SYNTHETIC DONOR",
                "ContributionDate": "03/29/2026",
                "ContributionAmt": "250.00",
                "ContributionDescription": "Synthetic contribution row",
            },
        ),
        (
            "loans",
            "loan",
            {
                "FilerNumber": "99999",
                "FilerLastName": "TEST COMMITTEE",
                "FilerFirstName": "",
                "ReportCode": "F305",
                "ReportType": "AN",
                "ReportNumber": "1",
                "LoanHolderName": "SYNTHETIC LENDER",
                "LoanDate": "03/29/2026",
                "LoanAmt": "750.00",
                "LoanDescription": "Synthetic loan row",
            },
        ),
    ],
)
def test_upsert_la_transaction_non_expenditures_do_not_call_ie_classifier(
    monkeypatch: pytest.MonkeyPatch,
    data_type: str,
    expected_transaction_type: str,
    row: dict[str, str],
) -> None:
    captured: list[object] = []
    monkeypatch.setattr(load, "upsert_transaction", lambda _conn, txn: captured.append(txn))
    monkeypatch.setattr(load, "resolve_transaction_counterparty_ids", lambda _conn, **_kw: (None, None))
    monkeypatch.setattr(load, "_resolve_la_transaction_address_id", lambda _conn, **_kw: None)
    monkeypatch.setattr(load, "_counterparty_name_raw", lambda _row, **_kw: "SYNTHETIC COUNTERPARTY")
    monkeypatch.setitem(load._LA_EXTRACT_FN, data_type, lambda _row: {"address": None})

    def _raise_if_called(_row: dict[str, str | None]) -> bool:
        raise AssertionError("_la_is_independent_expenditure should not run for non-expenditure rows")

    monkeypatch.setattr(load, "_la_is_independent_expenditure", _raise_if_called)

    if data_type == "loans":
        real_load_column = load._load_column_for_semantic_path

        def _load_column_for_semantic_path(data_type_arg: str, semantic_path: str) -> str:
            if data_type_arg == "loans" and semantic_path == "transaction.description":
                return "LoanDescription"
            return real_load_column(data_type_arg, semantic_path)

        monkeypatch.setattr(load, "_load_column_for_semantic_path", _load_column_for_semantic_path)

    load._upsert_la_transaction_with_filing(
        MagicMock(),
        row,
        filing_id=uuid4(),
        committee_id=uuid4(),
        source_record_id=uuid4(),
        data_type=data_type,
    )

    assert len(captured) == 1
    assert captured[0].transaction_type == expected_transaction_type


@pytest.mark.parametrize(
    ("report_code", "schedule", "expected_transaction_type"),
    [
        ("F305", "E-1", "Independent Expenditure"),
        ("F306", "E-4", "Independent Expenditure"),
        ("F202", "E-1", "expenditure"),
    ],
)
def test_upsert_la_transaction_sets_expected_expenditure_type(
    monkeypatch: pytest.MonkeyPatch,
    report_code: str,
    schedule: str,
    expected_transaction_type: str,
) -> None:
    captured: list[object] = []
    monkeypatch.setattr(load, "upsert_transaction", lambda _conn, txn: captured.append(txn))
    monkeypatch.setattr(load, "resolve_transaction_counterparty_ids", lambda _conn, **_kw: (None, None))
    monkeypatch.setattr(load, "_resolve_la_transaction_address_id", lambda _conn, **_kw: None)
    monkeypatch.setattr(load, "_counterparty_name_raw", lambda _row, **_kw: "SYNTHETIC PAYEE")
    monkeypatch.setitem(load._LA_EXTRACT_FN, "expenditures", lambda _row: {"address": None})

    row = {
        "Schedule": schedule,
        "FilerNumber": "99999",
        "FilerLastName": "TEST COMMITTEE",
        "FilerFirstName": "",
        "ReportCode": report_code,
        "ReportType": "AN",
        "ReportNumber": "1",
        "RecipientName": "SYNTHETIC PAYEE",
        "ExpenditureDate": "03/29/2026",
        "ExpenditureAmt": "500.00",
        "ExpenditureDescription": "Synthetic test row",
    }
    load._upsert_la_transaction_with_filing(
        MagicMock(),
        row,
        filing_id=uuid4(),
        committee_id=uuid4(),
        source_record_id=uuid4(),
        data_type="expenditures",
    )

    assert len(captured) == 1
    assert captured[0].transaction_type == expected_transaction_type


def test_upsert_la_transaction_unknown_report_code_stays_expenditure(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[object] = []
    monkeypatch.setattr(load, "upsert_transaction", lambda _conn, txn: captured.append(txn))
    monkeypatch.setattr(load, "resolve_transaction_counterparty_ids", lambda _conn, **_kw: (None, None))
    monkeypatch.setattr(load, "_resolve_la_transaction_address_id", lambda _conn, **_kw: None)
    monkeypatch.setattr(load, "_counterparty_name_raw", lambda _row, **_kw: "SYNTHETIC PAYEE")
    monkeypatch.setitem(load._LA_EXTRACT_FN, "expenditures", lambda _row: {"address": None})

    row = {
        "Schedule": "E-1",
        "FilerNumber": "99999",
        "FilerLastName": "TEST COMMITTEE",
        "FilerFirstName": "",
        "ReportCode": "X99",
        "ReportType": "AN",
        "ReportNumber": "1",
        "RecipientName": "SYNTHETIC PAYEE",
        "ExpenditureDate": "03/29/2026",
        "ExpenditureAmt": "500.00",
        "ExpenditureDescription": "Synthetic test row",
    }
    load._upsert_la_transaction_with_filing(
        MagicMock(),
        row,
        filing_id=uuid4(),
        committee_id=uuid4(),
        source_record_id=uuid4(),
        data_type="expenditures",
    )

    assert len(captured) == 1
    assert captured[0].transaction_type == "expenditure"
