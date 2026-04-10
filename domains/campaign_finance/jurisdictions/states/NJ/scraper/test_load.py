from __future__ import annotations

import contextlib
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import psycopg
import pytest

from domains.campaign_finance.jurisdictions.states.NJ.scraper import load as nj_load
from domains.campaign_finance.jurisdictions.states.NJ.scraper.load import (
    LoadResult,
    _build_nj_filing_fec_id,
    _parse_nj_amount,
    _parse_nj_date,
    load_nj_contributions_with_filings,
)


def _build_load_result() -> LoadResult:
    return LoadResult(
        inserted=3,
        skipped=1,
        quarantined=0,
        superseded=0,
        errors=0,
        elapsed_seconds=0.25,
    )


def test_parse_nj_date_supports_mmddyyyy() -> None:
    assert _parse_nj_date("03/25/2026") == date(2026, 3, 25)


def test_parse_nj_date_supports_iso_format() -> None:
    assert _parse_nj_date("2026-03-25") == date(2026, 3, 25)


def test_parse_nj_date_returns_none_for_empty() -> None:
    assert _parse_nj_date(None) is None
    assert _parse_nj_date("") is None


def test_parse_nj_amount_handles_comma_separated_values() -> None:
    from decimal import Decimal

    assert _parse_nj_amount("1,500.00") == Decimal("1500.00")
    assert _parse_nj_amount("250") == Decimal("250")


def test_parse_nj_amount_raises_for_invalid() -> None:
    with pytest.raises(ValueError, match="invalid"):
        _parse_nj_amount("not-a-number")


def test_build_nj_filing_fec_id_uses_entity_and_year() -> None:
    row = {
        "EntityName": "Friends of Civibus",
        "ContributionDate": "03/25/2026",
        "ElectionYear": "2026",
    }
    filing_id = _build_nj_filing_fec_id(row)
    assert filing_id == "NJ-Friends of Civibus-2026-contributions"


def test_load_nj_contributions_with_filings_runs_base_and_relational_passes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    connection = MagicMock()
    connection.info.transaction_status = psycopg.pq.TransactionStatus.IDLE
    expected_result = _build_load_result()
    data_source_id = "ds-id"
    path = tmp_path / "contributions.csv"

    ensure_data_source = MagicMock(return_value=data_source_id)
    load_file = MagicMock(return_value=expected_result)
    parse_contributions = MagicMock(return_value=iter([{"IsIndividual": "True"}, {"IsIndividual": "False"}]))
    load_relational = MagicMock(return_value=2)

    monkeypatch.setattr(nj_load, "ensure_nj_data_source", ensure_data_source)
    monkeypatch.setattr(nj_load, "_load_nj_file", load_file)
    monkeypatch.setattr(nj_load, "parse_contributions", parse_contributions)
    monkeypatch.setattr(nj_load, "_load_nj_relational_contributions", load_relational)

    result = load_nj_contributions_with_filings(connection, path, limit=2)

    assert result == expected_result
    assert result.errors == 2
    ensure_data_source.assert_called_once_with(connection, data_type="contributions")
    load_file.assert_called_once_with(connection, path, data_source_id=data_source_id, limit=2)
    parse_contributions.assert_called_once_with(path)
    load_relational.assert_called_once()


def test_load_nj_relational_contributions_counts_row_errors_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    connection.info.transaction_status = psycopg.pq.TransactionStatus.IDLE
    connection.transaction.side_effect = lambda: contextlib.nullcontext()

    rows = [{"EntityName": "Committee A"}, {"EntityName": "Committee B"}]
    source_record_ids = [uuid4(), uuid4()]
    monkeypatch.setattr(nj_load, "_select_nj_source_record_id", MagicMock(side_effect=source_record_ids))
    monkeypatch.setattr(nj_load, "commit_managed_transaction", MagicMock())

    filing_entry = nj_load._NJFilingLookupEntry(
        filing_id=uuid4(),
        committee_id=uuid4(),
        source_record_id=source_record_ids[1],
    )
    upsert_filing = MagicMock(side_effect=[RuntimeError("boom"), filing_entry])
    upsert_contribution = MagicMock()
    monkeypatch.setattr(nj_load, "_upsert_nj_filing", upsert_filing)
    monkeypatch.setattr(nj_load, "_upsert_nj_contribution_with_filing", upsert_contribution)

    errors = nj_load._load_nj_relational_contributions(connection, rows, data_source_id=uuid4(), limit=None)

    assert errors == 1
    assert upsert_filing.call_count == 2
    upsert_contribution.assert_called_once_with(
        connection,
        rows[1],
        filing_id=filing_entry.filing_id,
        committee_id=filing_entry.committee_id,
        source_record_id=source_record_ids[1],
    )
