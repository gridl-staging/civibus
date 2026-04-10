from __future__ import annotations

from datetime import date
from pathlib import Path
import contextlib
from unittest.mock import MagicMock
from uuid import uuid4

import psycopg

import pytest

from domains.campaign_finance.jurisdictions.states.WI.scraper import load as wi_load
from domains.campaign_finance.jurisdictions.states.WI.scraper.load import (
    LoadResult,
    _build_wi_filing_fec_id,
    _normalize_support_stance,
    _parse_wi_date,
    load_wi_transactions_with_filings,
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


def test_parse_wi_date_supports_mmddyyyy() -> None:
    assert _parse_wi_date("03/25/2026") == date(2026, 3, 25)


def test_normalize_support_stance_maps_common_values() -> None:
    assert _normalize_support_stance("Support") == "S"
    assert _normalize_support_stance("Oppose") == "O"
    assert _normalize_support_stance("") is None
    assert _normalize_support_stance(None) is None
    assert _normalize_support_stance("Neither") is None


def test_build_wi_filing_fec_id_uses_registrant_id_and_year() -> None:
    row = {
        "Registrant ID": "0106914",
        "Date": "03/25/2026",
    }

    assert _build_wi_filing_fec_id(row) == "WI-0106914-2026-transactions"


def test_build_wi_filing_fec_id_falls_back_to_communication_date() -> None:
    row = {
        "Registrant ID": "0106914",
        "Date": None,
        "Communication Date": "03/26/2026",
    }

    assert _build_wi_filing_fec_id(row) == "WI-0106914-2026-transactions"


def test_build_wi_filing_uses_communication_date_when_date_missing() -> None:
    filing = wi_load._build_wi_filing(
        {
            "Registrant ID": "0106914",
            "Registrant Name": "Friends of Civibus",
            "Date": None,
            "Communication Date": "03/26/2026",
        },
        committee_id=uuid4(),
        source_record_id=uuid4(),
    )

    assert filing.receipt_date == date(2026, 3, 26)
    assert filing.accepted_date == date(2026, 3, 26)


def test_load_wi_transactions_with_filings_runs_base_and_relational_passes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    connection = MagicMock()
    expected_result = _build_load_result()
    data_source_id = "ds-id"
    path = tmp_path / "transactions.csv"

    ensure_data_source = MagicMock(return_value=data_source_id)
    load_file = MagicMock(return_value=expected_result)
    parse_transactions = MagicMock(return_value=iter([{"ID": "1"}, {"ID": "2"}]))
    load_relational = MagicMock(return_value=2)

    monkeypatch.setattr(wi_load, "ensure_wi_data_source", ensure_data_source)
    monkeypatch.setattr(wi_load, "_load_wi_file", load_file)
    monkeypatch.setattr(wi_load, "parse_transactions", parse_transactions)
    monkeypatch.setattr(wi_load, "_load_wi_relational_transactions", load_relational)

    result = load_wi_transactions_with_filings(connection, path, limit=2)

    assert result == expected_result
    assert result.errors == 2
    ensure_data_source.assert_called_once_with(connection, data_type="transactions")
    load_file.assert_called_once_with(connection, path, data_source_id=data_source_id, limit=2)
    parse_transactions.assert_called_once_with(path)
    load_relational.assert_called_once()
    assert load_relational.call_args.args[0] is connection
    assert load_relational.call_args.kwargs == {"data_source_id": data_source_id, "limit": 2}


def test_load_wi_relational_transactions_counts_row_errors_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    connection.info.transaction_status = psycopg.pq.TransactionStatus.IDLE
    connection.transaction.side_effect = lambda: contextlib.nullcontext()

    rows = [{"Registrant ID": "001"}, {"Registrant ID": "002"}]
    source_record_ids = [uuid4(), uuid4()]
    monkeypatch.setattr(wi_load, "_select_wi_source_record_id", MagicMock(side_effect=source_record_ids))
    monkeypatch.setattr(wi_load, "commit_managed_transaction", MagicMock())

    filing_entry = wi_load._WIFilingLookupEntry(
        filing_id=uuid4(),
        committee_id=uuid4(),
        source_record_id=source_record_ids[1],
    )
    # First row raises, second row succeeds
    upsert_filing = MagicMock(side_effect=[RuntimeError("boom"), filing_entry])
    upsert_transaction = MagicMock()
    monkeypatch.setattr(wi_load, "_upsert_wi_filing", upsert_filing)
    monkeypatch.setattr(wi_load, "_upsert_wi_transaction_with_filing", upsert_transaction)

    errors = wi_load._load_wi_relational_transactions(connection, rows, data_source_id=uuid4(), limit=None)

    assert errors == 1
    assert upsert_filing.call_count == 2
    # Only the second row should have proceeded to transaction upsert
    upsert_transaction.assert_called_once_with(
        connection,
        rows[1],
        filing_id=filing_entry.filing_id,
        committee_id=filing_entry.committee_id,
        source_record_id=source_record_ids[1],
    )


def test_load_wi_relational_transactions_drops_stale_filing_lookup_after_row_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    connection.info.transaction_status = psycopg.pq.TransactionStatus.IDLE
    connection.transaction.side_effect = lambda: contextlib.nullcontext()

    rows = [{"Registrant ID": "001"}, {"Registrant ID": "001"}]
    source_record_ids = [uuid4(), uuid4()]
    monkeypatch.setattr(wi_load, "_select_wi_source_record_id", MagicMock(side_effect=source_record_ids))
    monkeypatch.setattr(wi_load, "commit_managed_transaction", MagicMock())
    monkeypatch.setattr(wi_load, "_build_wi_filing_fec_id", MagicMock(return_value="WI-001-2026-transactions"))

    first_entry = wi_load._WIFilingLookupEntry(
        filing_id=uuid4(), committee_id=uuid4(), source_record_id=source_record_ids[0]
    )
    second_entry = wi_load._WIFilingLookupEntry(
        filing_id=uuid4(),
        committee_id=uuid4(),
        source_record_id=source_record_ids[1],
    )
    created_entries: list[wi_load._WIFilingLookupEntry] = []

    def fake_upsert_wi_filing(
        _conn,
        _row,
        *,
        source_record_id,
        filing_lookup,
    ) -> wi_load._WIFilingLookupEntry:
        if "WI-001-2026-transactions" in filing_lookup:
            return filing_lookup["WI-001-2026-transactions"]
        entry = first_entry if not created_entries else second_entry
        filing_lookup["WI-001-2026-transactions"] = entry
        created_entries.append(entry)
        return entry

    def fake_upsert_wi_transaction_with_filing(
        _conn,
        _row,
        *,
        filing_id,
        committee_id,
        source_record_id,
    ) -> None:
        if filing_id == first_entry.filing_id:
            raise RuntimeError("boom")
        assert filing_id == second_entry.filing_id
        assert committee_id == second_entry.committee_id
        assert source_record_id == source_record_ids[1]

    monkeypatch.setattr(wi_load, "_upsert_wi_filing", fake_upsert_wi_filing)
    monkeypatch.setattr(wi_load, "_upsert_wi_transaction_with_filing", fake_upsert_wi_transaction_with_filing)

    errors = wi_load._load_wi_relational_transactions(connection, rows, data_source_id=uuid4(), limit=None)

    assert errors == 1
    assert created_entries == [first_entry, second_entry]


def test_resolve_wi_transaction_address_id_uses_parameterized_sql() -> None:
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    expected_address_id = uuid4()
    cursor.fetchone.return_value = (expected_address_id,)

    test_source_record_id = uuid4()
    resolved_address_id = wi_load._resolve_wi_transaction_address_id(connection, source_record_id=test_source_record_id)

    assert resolved_address_id == expected_address_id
    executed_query = cursor.execute.call_args.args[0]
    executed_params = cursor.execute.call_args.args[1]
    # Constants must be parameterized, not embedded as SQL literals
    assert "entity_type = %s" in executed_query
    assert "extraction_role = %s" in executed_query
    assert executed_params == (test_source_record_id, "address", "contributor_address")


class TestWiIeClassification:
    """Verify embedded WI IE rows get transaction_type overrides."""

    @pytest.fixture
    def captured_transactions(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> list[wi_load.Transaction]:
        captured: list[wi_load.Transaction] = []
        monkeypatch.setattr(
            wi_load,
            "upsert_transaction",
            lambda conn, txn: captured.append(txn),
        )
        monkeypatch.setattr(
            wi_load,
            "resolve_transaction_counterparty_ids",
            lambda conn, **kwargs: (None, None),
        )
        monkeypatch.setattr(wi_load, "_resolve_wi_transaction_address_id", lambda conn, **kwargs: None)
        return captured

    def test_support_stance_sets_independent_expenditure_type(
        self,
        captured_transactions: list[wi_load.Transaction],
    ) -> None:

        wi_load._upsert_wi_transaction_with_filing(
            MagicMock(),
            {
                "Transaction Type": "Contribution",
                "Support Stance": "Support",
                "Amount": "125.00",
                "Date": "03/26/2026",
                "Registrant ID": "0106914",
                "Registrant Name": "Friends of Civibus",
                "Contributor Name (-> Related Payer Name if applicable)": "Jane A. Donor",
            },
            filing_id=uuid4(),
            committee_id=uuid4(),
            source_record_id=uuid4(),
        )

        assert len(captured_transactions) == 1
        assert captured_transactions[0].transaction_type == "Independent Expenditure"
        assert captured_transactions[0].support_oppose == "S"

    def test_blank_support_stance_keeps_original_transaction_type(
        self,
        captured_transactions: list[wi_load.Transaction],
    ) -> None:

        wi_load._upsert_wi_transaction_with_filing(
            MagicMock(),
            {
                "Transaction Type": "Contribution",
                "Support Stance": "",
                "Amount": "125.00",
                "Date": "03/26/2026",
                "Registrant ID": "0106914",
                "Registrant Name": "Friends of Civibus",
                "Contributor Name (-> Related Payer Name if applicable)": "Jane A. Donor",
            },
            filing_id=uuid4(),
            committee_id=uuid4(),
            source_record_id=uuid4(),
        )

        assert len(captured_transactions) == 1
        assert captured_transactions[0].transaction_type == "Contribution"
        assert captured_transactions[0].support_oppose is None


def test_upsert_wi_transaction_uses_communication_date_when_date_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upsert_transaction = MagicMock()
    monkeypatch.setattr(wi_load, "resolve_transaction_counterparty_ids", MagicMock(return_value=(None, None)))
    monkeypatch.setattr(wi_load, "_resolve_wi_transaction_address_id", MagicMock(return_value=None))
    monkeypatch.setattr(wi_load, "upsert_transaction", upsert_transaction)

    wi_load._upsert_wi_transaction_with_filing(
        MagicMock(),
        {
            "Transaction Type": "Contribution",
            "Amount": "125.00",
            "Date": None,
            "Communication Date": "03/26/2026",
        },
        filing_id=uuid4(),
        committee_id=uuid4(),
        source_record_id=uuid4(),
    )

    transaction = upsert_transaction.call_args.args[1]
    assert transaction.transaction_date == date(2026, 3, 26)


def test_upsert_wi_transaction_uses_normalized_extracted_address_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upsert_transaction = MagicMock()
    monkeypatch.setattr(wi_load, "resolve_transaction_counterparty_ids", MagicMock(return_value=(None, None)))
    monkeypatch.setattr(wi_load, "_resolve_wi_transaction_address_id", MagicMock(return_value=None))
    monkeypatch.setattr(
        wi_load,
        "extract_wi_transaction",
        MagicMock(
            return_value={
                "contributor_person": None,
                "contributor_org": None,
                "committee": None,
                "address": wi_load.Address(
                    raw_address="123 Main St, Madison, WI, 53703",
                    city="Madison",
                    state="WI",
                    zip5="53703",
                ),
            }
        ),
    )
    monkeypatch.setattr(wi_load, "upsert_transaction", upsert_transaction)

    wi_load._upsert_wi_transaction_with_filing(
        MagicMock(),
        {
            "Transaction Type": "Contribution",
            "Amount": "125.00",
            "Date": "03/26/2026",
            "Contributor Name (-> Related Payer Name if applicable)": "Jane A. Donor",
            "Contributor City": "Madison",
            "Contributor State": "Wisconsin",
            "Contributor Zip": "53703",
        },
        filing_id=uuid4(),
        committee_id=uuid4(),
        source_record_id=uuid4(),
    )

    transaction = upsert_transaction.call_args.args[1]
    assert transaction.contributor_state == "WI"
