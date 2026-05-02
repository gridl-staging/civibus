"""Tests for Virginia campaign finance DB loader.

Covers pure helper functions (no DB required) and transaction_type invariants.
"""

from __future__ import annotations

import inspect
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from domains.campaign_finance.jurisdictions.states.VA.scraper import load
from domains.campaign_finance.jurisdictions.states.VA.scraper.load import (
    _build_contributor_name,
    _build_va_filing_fec_id,
    _parse_va_amount,
    _parse_va_date,
    _va_source_record_key,
)


# ---------------------------------------------------------------------------
# _parse_va_date
# ---------------------------------------------------------------------------


class TestParseVaDate:
    def test_mm_dd_yyyy(self) -> None:
        assert _parse_va_date("01/15/2025") is not None
        assert _parse_va_date("01/15/2025").isoformat() == "2025-01-15"

    def test_iso_with_time(self) -> None:
        assert _parse_va_date("2025-01-15 00:00:00.000000") is not None
        assert _parse_va_date("2025-01-15 00:00:00.000000").isoformat() == "2025-01-15"

    def test_iso_date_only(self) -> None:
        assert _parse_va_date("2025-01-15") is not None
        assert _parse_va_date("2025-01-15").isoformat() == "2025-01-15"

    def test_nanosecond_timestamp_trimmed(self) -> None:
        result = _parse_va_date("2025-01-15 00:00:00.000000000")
        assert result is not None
        assert result.isoformat() == "2025-01-15"

    def test_none_returns_none(self) -> None:
        assert _parse_va_date(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert _parse_va_date("") is None

    def test_whitespace_returns_none(self) -> None:
        assert _parse_va_date("   ") is None

    def test_invalid_string_returns_none(self) -> None:
        assert _parse_va_date("not-a-date") is None

    def test_partial_date_returns_none(self) -> None:
        assert _parse_va_date("2025-13-40") is None


# ---------------------------------------------------------------------------
# _parse_va_amount
# ---------------------------------------------------------------------------


class TestParseVaAmount:
    def test_plain_number(self) -> None:
        assert _parse_va_amount("100.50") == Decimal("100.50")

    def test_dollar_sign(self) -> None:
        assert _parse_va_amount("$1,234.56") == Decimal("1234.56")

    def test_commas_stripped(self) -> None:
        assert _parse_va_amount("1,000,000.00") == Decimal("1000000.00")

    def test_none_returns_zero(self) -> None:
        assert _parse_va_amount(None) == Decimal(0)

    def test_empty_string_returns_zero(self) -> None:
        assert _parse_va_amount("") == Decimal(0)

    def test_whitespace_returns_zero(self) -> None:
        assert _parse_va_amount("   ") == Decimal(0)

    def test_invalid_returns_zero(self) -> None:
        assert _parse_va_amount("not-a-number") == Decimal(0)

    def test_negative_amount(self) -> None:
        assert _parse_va_amount("-500.00") == Decimal("-500.00")

    def test_quantized_to_cents(self) -> None:
        result = _parse_va_amount("99.999")
        assert result == Decimal("100.00")


# ---------------------------------------------------------------------------
# _build_contributor_name
# ---------------------------------------------------------------------------


class TestBuildContributorName:
    def test_full_name(self) -> None:
        row = {"FirstName": "Jane", "MiddleName": "A", "LastOrCompanyName": "Smith"}
        assert _build_contributor_name(row) == "Jane A Smith"

    def test_first_and_last_only(self) -> None:
        row = {"FirstName": "Jane", "MiddleName": None, "LastOrCompanyName": "Smith"}
        assert _build_contributor_name(row) == "Jane Smith"

    def test_last_only(self) -> None:
        row = {"FirstName": None, "MiddleName": None, "LastOrCompanyName": "Acme Corp"}
        assert _build_contributor_name(row) == "Acme Corp"

    def test_first_only(self) -> None:
        row = {"FirstName": "Jane", "MiddleName": None, "LastOrCompanyName": None}
        assert _build_contributor_name(row) == "Jane"

    def test_all_empty_returns_none(self) -> None:
        row = {"FirstName": "", "MiddleName": "", "LastOrCompanyName": ""}
        assert _build_contributor_name(row) is None

    def test_all_none_returns_none(self) -> None:
        row = {"FirstName": None, "MiddleName": None, "LastOrCompanyName": None}
        assert _build_contributor_name(row) is None

    def test_missing_keys_returns_none(self) -> None:
        assert _build_contributor_name({}) is None

    def test_whitespace_only_fields_returns_none(self) -> None:
        row = {"FirstName": "  ", "MiddleName": "  ", "LastOrCompanyName": "  "}
        assert _build_contributor_name(row) is None


# ---------------------------------------------------------------------------
# _va_source_record_key
# ---------------------------------------------------------------------------


class TestVaSourceRecordKey:
    def test_contributions_uses_schedule_a_id(self) -> None:
        row = {"ScheduleAId": "12345", "ScheduleDId": "99999"}
        result = _va_source_record_key(row, "contributions")
        assert result == "va-contributions-12345"

    def test_expenditures_uses_schedule_d_id(self) -> None:
        row = {"ScheduleAId": "12345", "ScheduleDId": "99999"}
        result = _va_source_record_key(row, "expenditures")
        assert result == "va-expenditures-99999"

    def test_missing_id_falls_back_to_hash(self) -> None:
        row = {"SomeField": "value"}
        result = _va_source_record_key(row, "contributions")
        assert not result.startswith("va-contributions-")
        assert len(result) > 0

    def test_none_id_falls_back_to_hash(self) -> None:
        row = {"ScheduleAId": None, "SomeField": "value"}
        result = _va_source_record_key(row, "contributions")
        assert not result.startswith("va-contributions-")

    def test_empty_id_falls_back_to_hash(self) -> None:
        row = {"ScheduleAId": "", "SomeField": "value"}
        result = _va_source_record_key(row, "contributions")
        assert not result.startswith("va-contributions-")

    def test_hash_is_deterministic(self) -> None:
        row = {"ScheduleAId": None, "Field1": "a", "Field2": "b"}
        assert _va_source_record_key(row, "contributions") == _va_source_record_key(row, "contributions")


# ---------------------------------------------------------------------------
# _build_va_filing_fec_id
# ---------------------------------------------------------------------------


class TestBuildVaFilingFecId:
    def test_valid_report_id_contributions(self) -> None:
        row = {"ReportId": "7890"}
        assert _build_va_filing_fec_id(row, "contributions") == "VA-7890-contributions"

    def test_valid_report_id_expenditures(self) -> None:
        row = {"ReportId": "7890"}
        assert _build_va_filing_fec_id(row, "expenditures") == "VA-7890-expenditures"

    def test_none_report_id_raises(self) -> None:
        row = {"ReportId": None}
        with pytest.raises(ValueError, match="missing ReportId"):
            _build_va_filing_fec_id(row, "contributions")

    def test_missing_report_id_key_raises(self) -> None:
        with pytest.raises(ValueError, match="missing ReportId"):
            _build_va_filing_fec_id({}, "contributions")

    def test_empty_report_id_raises(self) -> None:
        row = {"ReportId": ""}
        with pytest.raises(ValueError, match="missing ReportId"):
            _build_va_filing_fec_id(row, "contributions")

    def test_whitespace_report_id_raises(self) -> None:
        row = {"ReportId": "   "}
        with pytest.raises(ValueError, match="missing ReportId"):
            _build_va_filing_fec_id(row, "contributions")


# ---------------------------------------------------------------------------
# transaction_type invariants + CommitteeType regression guard
# ---------------------------------------------------------------------------


class _FakeTransactionContext:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeConnection:
    def __init__(self) -> None:
        self.info = SimpleNamespace(
            transaction_status=__import__("psycopg").pq.TransactionStatus.IDLE,
        )
        self.commit = MagicMock()
        self.rollback = MagicMock()

    def transaction(self) -> _FakeTransactionContext:
        return _FakeTransactionContext()


class TestTransactionTypeInvariants:
    def test_contribution_transaction_type_is_contribution(self, monkeypatch) -> None:
        captured = []

        def _capture_upsert(_conn, txn):
            captured.append(txn)

        monkeypatch.setattr(load, "upsert_transaction", _capture_upsert)
        monkeypatch.setattr(
            load,
            "resolve_transaction_counterparty_ids",
            MagicMock(return_value=(None, None)),
        )
        monkeypatch.setattr(
            load,
            "extract_va_contribution",
            MagicMock(
                return_value={
                    "donor_person": None,
                    "donor_org": None,
                    "address": None,
                }
            ),
        )

        row = {
            "ScheduleAId": "100",
            "TransactionDate": "01/01/2025",
            "Amount": "500.00",
            "FirstName": "Test",
            "MiddleName": None,
            "LastOrCompanyName": "Donor",
            "NameOfEmployer": None,
            "OccupationOrTypeOfBusiness": None,
        }

        from domains.campaign_finance.jurisdictions.states.VA.scraper.load import (
            _upsert_va_contribution_transaction,
        )

        _upsert_va_contribution_transaction(
            _FakeConnection(),
            row,
            filing_id=uuid4(),
            committee_id=uuid4(),
            source_record_id=uuid4(),
        )

        assert len(captured) == 1
        assert captured[0].transaction_type == "contribution"

    def test_expenditure_transaction_type_is_expenditure(self, monkeypatch) -> None:
        captured = []

        def _capture_upsert(_conn, txn):
            captured.append(txn)

        monkeypatch.setattr(load, "upsert_transaction", _capture_upsert)
        monkeypatch.setattr(
            load,
            "resolve_transaction_counterparty_ids",
            MagicMock(return_value=(None, None)),
        )
        monkeypatch.setattr(
            load,
            "extract_va_expenditure",
            MagicMock(
                return_value={
                    "payee_person": None,
                    "payee_org": None,
                    "address": None,
                }
            ),
        )

        row = {
            "ScheduleDId": "200",
            "TransactionDate": "01/01/2025",
            "Amount": "300.00",
            "FirstName": "Test",
            "MiddleName": None,
            "LastOrCompanyName": "Vendor",
            "ItemOrService": "Supplies",
        }

        from domains.campaign_finance.jurisdictions.states.VA.scraper.load import (
            _upsert_va_expenditure_transaction,
        )

        _upsert_va_expenditure_transaction(
            _FakeConnection(),
            row,
            filing_id=uuid4(),
            committee_id=uuid4(),
            source_record_id=uuid4(),
        )

        assert len(captured) == 1
        assert captured[0].transaction_type == "expenditure"

    def test_no_committee_type_in_load_module(self) -> None:
        source = inspect.getsource(load)
        assert "CommitteeType" not in source, (
            "load.py must not reference CommitteeType — IE classification via "
            "CommitteeType was proven unviable in Stage 1"
        )
