"""Unit tests for Ohio campaign finance load helpers.

Tests pure helper functions only — no database required.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from core.types.python.models import compute_record_hash
from domains.campaign_finance.jurisdictions.states.OH.scraper import _load_column_for_semantic_path
from domains.campaign_finance.jurisdictions.states.OH.scraper.load import (
    LoadResult,
    _oh_amendment_indicator,
    _oh_counterparty_employer,
    _oh_filing_fec_id,
    _oh_source_record_key,
    _oh_transaction_type,
    _parse_oh_date,
)
from domains.campaign_finance.jurisdictions.states.OH.scraper.parse import parse_contributions, parse_expenditures

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"


def _column(data_type: str, semantic_path: str) -> str:
    return _load_column_for_semantic_path(data_type, semantic_path)


def _contribution_rows() -> list[dict[str, str | None]]:
    return list(parse_contributions(_FIXTURE_DIR / "sample_contributions.csv"))


def _expenditure_rows() -> list[dict[str, str | None]]:
    return list(parse_expenditures(_FIXTURE_DIR / "sample_expenditures.csv"))


# --- _oh_source_record_key: deterministic hash (no native row ID) ---


def test_source_record_key_is_deterministic() -> None:
    """Same row produces the same hash on repeated calls."""
    row = _contribution_rows()[0]
    key1 = _oh_source_record_key(row)
    key2 = _oh_source_record_key(row)
    expected = compute_record_hash(dict(row))

    assert key1 == key2
    assert key1 == expected
    assert len(key1) == 64  # SHA-256 hex digest


def test_source_record_key_differs_for_different_rows() -> None:
    """Different rows produce different hashes."""
    rows = _contribution_rows()
    key0 = _oh_source_record_key(rows[0])
    key1 = _oh_source_record_key(rows[1])
    assert key0 != key1


# --- _oh_filing_fec_id: OH-{MASTER_KEY}-{RPT_YEAR}-{REPORT_KEY}-{data_type} ---


def test_filing_fec_id_contribution_format() -> None:
    """Filing fec_id includes REPORT_KEY to preserve per-report uniqueness."""
    row = _contribution_rows()[0]
    fec_id = _oh_filing_fec_id(row, data_type="contributions")
    assert fec_id == "OH-12345-2022-67890-contributions"


def test_filing_fec_id_expenditure_format() -> None:
    """Expenditure fec_id uses the expenditures data_type."""
    row = _expenditure_rows()[0]
    fec_id = _oh_filing_fec_id(row, data_type="expenditures")
    assert fec_id == "OH-12345-2022-67890-expenditures"


def test_filing_fec_id_differs_for_distinct_report_keys_in_same_committee_year() -> None:
    """Different REPORT_KEY values must not collapse into the same filing id."""
    row = dict(_contribution_rows()[0])
    report_id_column = _column("contributions", "transaction.report_id")

    original_filing_fec_id = _oh_filing_fec_id(row, data_type="contributions")
    row[report_id_column] = "67891"

    assert _oh_filing_fec_id(row, data_type="contributions") != original_filing_fec_id


# --- _parse_oh_date: MM/DD/YYYY format ---


def test_parse_oh_date_valid() -> None:
    """Parses MM/DD/YYYY format correctly."""
    assert _parse_oh_date("06/14/2022") == date(2022, 6, 14)


def test_parse_oh_date_leading_zeros() -> None:
    """Handles leading zeros in month/day."""
    assert _parse_oh_date("01/01/2023") == date(2023, 1, 1)


def test_parse_oh_date_none_for_empty() -> None:
    """Returns None for empty string."""
    assert _parse_oh_date("") is None


def test_parse_oh_date_none_for_null() -> None:
    """Returns None for None."""
    assert _parse_oh_date(None) is None


def test_parse_oh_date_none_for_whitespace() -> None:
    """Returns None for whitespace-only."""
    assert _parse_oh_date("   ") is None


# --- _oh_amendment_indicator: always "N" (no verified field) ---


def test_amendment_indicator_returns_n() -> None:
    """Returns 'N' for all rows — no amendment field verified in OH bulk CSVs."""
    row = _contribution_rows()[0]
    assert _oh_amendment_indicator(row) == "N"


def test_amendment_indicator_returns_n_for_expenditure() -> None:
    """Returns 'N' for expenditure rows as well."""
    row = _expenditure_rows()[0]
    assert _oh_amendment_indicator(row) == "N"


# --- _oh_transaction_type ---


def test_transaction_type_from_data_type() -> None:
    """Derives transaction type from data_type when SHORT_DESCRIPTION not useful."""
    row = _contribution_rows()[0]
    assert _oh_transaction_type(row, data_type="contributions") == "contribution"


def test_transaction_type_expenditure() -> None:
    """Expenditure data_type produces 'expenditure'."""
    row = _expenditure_rows()[0]
    assert _oh_transaction_type(row, data_type="expenditures") == "expenditure"


def test_transaction_type_uses_short_description_when_informative() -> None:
    """SHORT_DESCRIPTION can override the default singularized data_type value."""
    row = dict(_contribution_rows()[0])
    row[_column("contributions", "oh.short_description")] = "Expenditures"

    assert _oh_transaction_type(row, data_type="contributions") == "expenditure"


# --- _oh_counterparty_employer: combined EMP_OCCUPATION field ---


def test_counterparty_employer_returns_none_for_empty() -> None:
    """Returns None when EMP_OCCUPATION is empty/missing."""
    row = _contribution_rows()[0]
    # Row 0's EMP_OCCUPATION is empty in fixture
    result = _oh_counterparty_employer(row, data_type="contributions")
    assert result is None


def test_counterparty_employer_returns_normalized_value() -> None:
    """Returns normalized EMP_OCCUPATION value when populated."""
    row = dict(_contribution_rows()[1])
    # Row 1 has EMP_OCCUPATION mapped in fixture — let's inject a value
    row[_column("contributions", "oh.donor_employer_occupation")] = "  Acme Corp / Accountant  "
    result = _oh_counterparty_employer(row, data_type="contributions")
    assert result == "Acme Corp / Accountant"


def test_counterparty_employer_returns_none_for_expenditures() -> None:
    """Expenditures have no EMP_OCCUPATION field — should return None."""
    row = _expenditure_rows()[0]
    result = _oh_counterparty_employer(row, data_type="expenditures")
    assert result is None


# --- LoadResult dataclass ---


def test_load_result_is_dataclass() -> None:
    """LoadResult is importable and constructible."""
    result = LoadResult(
        inserted=10,
        skipped=2,
        quarantined=1,
        superseded=0,
        errors=0,
        elapsed_seconds=1.5,
    )
    assert result.inserted == 10
    assert result.skipped == 2
    assert result.quarantined == 1
    assert result.elapsed_seconds == 1.5
