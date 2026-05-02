"""Unit tests for PHL Carto SQL row parser."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from domains.campaign_finance.jurisdictions.cities.PHL.scraper.parse import (
    PHLCampaignFinanceRow,
    parse_phl_carto_row,
    parse_phl_carto_rows,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
_CONTRIBUTIONS_FIXTURE = FIXTURES_DIR / "campfin_contributions_sample_2026_04_25.json"
_EXPENDITURES_FIXTURE = FIXTURES_DIR / "campfin_expenditures_sample_2026_04_25.json"


def _load_fixture_rows(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload["rows"]
    assert isinstance(rows, list) and rows, f"fixture {path} has no rows"
    return rows


def test_parse_contribution_row_round_trips_canonical_fields() -> None:
    """A live-captured Carto contribution row maps cleanly into the typed model
    with the documented field-mapping subset (per config.yaml::field_mappings).
    Asserts against actual values, not just absence-of-error."""
    raw = _load_fixture_rows(_CONTRIBUTIONS_FIXTURE)[0]
    parsed = parse_phl_carto_row(raw, is_expenditure=False)

    assert isinstance(parsed, PHLCampaignFinanceRow)
    # Every required field must come straight from the source — no synthesis.
    assert parsed.transaction_id == str(raw["transaction_id"])
    assert isinstance(parsed.transaction_date, date)
    assert isinstance(parsed.transaction_amount, Decimal)
    assert parsed.transaction_amount == Decimal(str(raw["transaction_amount"]))
    assert parsed.is_expenditure is False
    assert parsed.filer_name == raw["filer_name"]
    assert parsed.counterparty_name == raw["donor_name"]


def test_parse_expenditure_row_pulls_payee_columns_not_donor() -> None:
    """The PHL Carto schema uses payee_* on the expenditures table and donor_*
    on the contributions table; the parser MUST pick the right side based
    on `is_expenditure`."""
    raw = _load_fixture_rows(_EXPENDITURES_FIXTURE)[0]
    parsed = parse_phl_carto_row(raw, is_expenditure=True)

    assert parsed.is_expenditure is True
    assert parsed.counterparty_name == raw["payee_name"]
    # Expenditure rows do not carry a donor_name column at all; the parser
    # must not silently fall back to it.
    assert "donor_name" not in raw


def test_parse_phl_carto_rows_skips_rows_with_null_required_fields() -> None:
    """Carto can return rows with NULL transaction_id or amount; those rows
    must be SKIPPED (not raised) so the loader does not crash on a single
    bad row in a batch."""
    rows = [
        {"transaction_id": None, "transaction_amount": 100, "transaction_date": "2026-01-01",
         "filer_name": "X", "donor_name": "Y"},
        {"transaction_id": "T1", "transaction_amount": None, "transaction_date": "2026-01-01",
         "filer_name": "X", "donor_name": "Y"},
        {"transaction_id": "T2", "transaction_amount": 250, "transaction_date": "2026-01-02",
         "filer_name": "X", "donor_name": "Y"},
    ]
    parsed = list(parse_phl_carto_rows(rows, is_expenditure=False))
    assert len(parsed) == 1
    assert parsed[0].transaction_id == "T2"
    assert parsed[0].transaction_amount == Decimal("250")


def test_parse_carto_iso_z_date() -> None:
    """Carto returns ISO-8601 with trailing 'Z'; the parser MUST handle it
    and yield a date (not datetime)."""
    raw = {
        "transaction_id": "T",
        "transaction_amount": 1,
        "transaction_date": "2026-03-30T04:00:00Z",
        "filer_name": "X",
        "donor_name": "Y",
    }
    parsed = parse_phl_carto_row(raw, is_expenditure=False)
    assert parsed.transaction_date == date(2026, 3, 30)


def test_parse_amount_rejects_non_numeric() -> None:
    """Pydantic validator MUST reject non-numeric amounts as ValueError so the
    loader can bucket the row as quarantined."""
    raw = {
        "transaction_id": "T",
        "transaction_amount": "not a number",
        "transaction_date": "2026-03-30",
        "filer_name": "X",
        "donor_name": "Y",
    }
    # Tightened from `pytest.raises(Exception)` so the test cannot pass on
    # an unrelated exception (KeyError from a typo, AttributeError on a
    # refactor, etc). Pydantic raises ValidationError on type-coercion
    # failure for a Decimal field — that is the contract being pinned.
    with pytest.raises(ValidationError):
        parse_phl_carto_row(raw, is_expenditure=False)


def test_parse_full_contributions_fixture_yields_5_rows() -> None:
    """Every fixture row (5 total) must parse without error; pins the live
    schema contract against future Carto-side changes."""
    rows = _load_fixture_rows(_CONTRIBUTIONS_FIXTURE)
    parsed = list(parse_phl_carto_rows(rows, is_expenditure=False))
    assert len(parsed) == 5
    # Every parsed row carries the canonical identity fields.
    assert all(p.transaction_id and p.transaction_amount for p in parsed)


def test_parse_full_expenditures_fixture_yields_5_rows() -> None:
    rows = _load_fixture_rows(_EXPENDITURES_FIXTURE)
    parsed = list(parse_phl_carto_rows(rows, is_expenditure=True))
    assert len(parsed) == 5
    assert all(p.is_expenditure for p in parsed)
