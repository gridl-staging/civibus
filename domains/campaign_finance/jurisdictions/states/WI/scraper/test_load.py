from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
import contextlib
from contextlib import ExitStack
from unittest.mock import MagicMock
from uuid import uuid4

import psycopg

import pytest

from core.db import get_connection
from domains.campaign_finance.jurisdictions._bulk_fixture_support import (
    BulkFixtureInterruption,
    assert_loader_arm_is_caller_owned,
    bulk_fixture_row_counts,
    install_write_interrupt,
    seed_written_bulk_fixture,
)
from domains.campaign_finance.jurisdictions.states.WI.scraper import load as wi_load
from domains.campaign_finance.jurisdictions.states.WI.scraper.load import (
    LoadResult,
    _build_wi_filing_fec_id,
    _normalize_support_stance,
    _parse_wi_date,
    load_wi_transactions_with_filings,
)
from domains.campaign_finance.jurisdictions.states.WI.scraper.load_test_support import (
    write_wi_transaction_fixture,
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


# --- Stage 1: the base pass commits each completed source-record batch mid-loop ---
#
# `_EXPECTED_DURABLE_BATCH_ROWS` is a frozen literal, deliberately NOT read from a live
# loader constant: the boundary these specimens prove is exactly 1,000 rows, and an
# expectation derived from the loader could never go red against a broken loader.

_EXPECTED_DURABLE_BATCH_ROWS = 1_000
_WI_BULK_ROW_COUNT = _EXPECTED_DURABLE_BATCH_ROWS + 1
# The caller-owned invariant does not depend on crossing the batch boundary, so it uses a
# small fixture to keep the full base+relational load off the suite's critical path.
_WI_CALLER_ARM_ROW_COUNT = 5


def test_write_wi_transaction_fixture_produces_unique_keys_and_one_registrant(tmp_path: Path) -> None:
    """The bulk writer gives every row a distinct source-record key but one shared committee."""
    fixture = write_wi_transaction_fixture(tmp_path, row_count=_WI_BULK_ROW_COUNT)

    assert len(fixture.source_record_keys) == _WI_BULK_ROW_COUNT
    assert len(set(fixture.source_record_keys)) == _WI_BULK_ROW_COUNT

    with fixture.input_path.open(encoding="utf-8", newline="") as csv_file:
        registrant_ids = {row["Registrant ID"] for row in csv.DictReader(csv_file)}
    assert registrant_ids == {fixture.committee_native_id}


def test_load_wi_transactions_with_filings_commits_source_record_batch_mid_loop(
    db_conn: psycopg.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An interrupt after 1,000 source records leaves exactly those 1,000 durable.

    With the pre-Stage-1 ordering the entry point resolved the data source before sampling
    the transaction status, so it read INTRANS, decided it did not manage the outer
    transaction, and turned every `commit_managed_transaction` — including the base pass's
    1,000-row boundary — into a no-op. This interruption then discarded all 1,000 rows and an
    independent connection saw zero.
    """
    with ExitStack() as resources:
        fixture = seed_written_bulk_fixture(
            resources,
            db_conn,
            lambda: write_wi_transaction_fixture(tmp_path, row_count=_WI_BULK_ROW_COUNT),
            row_count=_WI_BULK_ROW_COUNT,
        )
        write_counts = install_write_interrupt(
            monkeypatch,
            wi_load,
            "try_insert_source_record",
            raise_after_writes=_EXPECTED_DURABLE_BATCH_ROWS,
        )

        with pytest.raises(BulkFixtureInterruption):
            load_wi_transactions_with_filings(db_conn, fixture.input_path)
        db_conn.rollback()

        # The base pass flushed its first full batch at row 1,000 and was interrupted on row
        # 1,001, so exactly that batch of source records is durable. The relational pass never
        # started, so no transaction rows exist.
        assert write_counts["writes"] == _WI_BULK_ROW_COUNT
        source_record_count, transaction_count = bulk_fixture_row_counts(fixture)
        assert source_record_count == _EXPECTED_DURABLE_BATCH_ROWS
        assert transaction_count == 0


@pytest.mark.integration
def test_load_wi_transactions_with_filings_commits_relational_batch_mid_loop(
    db_conn: psycopg.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An interrupt after 1,000 relational rows leaves exactly those 1,000 durable.

    Before the relational boundary fix the relational pass committed once, at the end of
    the job, so this interruption discarded every linked row and an observer saw zero.
    """
    with ExitStack() as resources:
        fixture = seed_written_bulk_fixture(
            resources,
            db_conn,
            lambda: write_wi_transaction_fixture(tmp_path, row_count=_WI_BULK_ROW_COUNT),
            row_count=_WI_BULK_ROW_COUNT,
        )
        write_counts = install_write_interrupt(
            monkeypatch,
            wi_load,
            "_upsert_wi_transaction_with_filing",
            raise_after_writes=_EXPECTED_DURABLE_BATCH_ROWS,
        )

        with pytest.raises(BulkFixtureInterruption):
            load_wi_transactions_with_filings(db_conn, fixture.input_path)
        db_conn.rollback()

        assert write_counts["writes"] == _WI_BULK_ROW_COUNT
        assert bulk_fixture_row_counts(fixture) == (_WI_BULK_ROW_COUNT, _EXPECTED_DURABLE_BATCH_ROWS)


def test_load_wi_transactions_with_filings_writes_into_caller_transaction(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    """A caller-supplied INTRANS connection owns the commit: the loader writes but never commits.

    Holds both before and after the Stage 1 ordering fix — when the caller hands over an open
    transaction the entry point must observe it does not manage it — so it is a standing
    invariant, not part of the red evidence.
    """
    with ExitStack() as resources:
        fixture = seed_written_bulk_fixture(
            resources,
            db_conn,
            lambda: write_wi_transaction_fixture(tmp_path, row_count=_WI_CALLER_ARM_ROW_COUNT),
            row_count=_WI_CALLER_ARM_ROW_COUNT,
        )
        db_conn.execute("BEGIN")
        assert_loader_arm_is_caller_owned(
            fixture,
            db_conn,
            expected_source_records=_WI_CALLER_ARM_ROW_COUNT,
            run_loader=lambda: load_wi_transactions_with_filings(db_conn, fixture.input_path),
        )


def test_cli_load_path_hands_the_loader_an_idle_connection(db_conn: psycopg.Connection) -> None:
    """`cli._load_path` must hand the loader an IDLE connection.

    A data-source lookup left open would make the loader read INTRANS and silently drop its
    1,000-row commit boundary — the exact defect Stage 1 fixes inside the entry point.
    """
    from domains.campaign_finance.jurisdictions.states.WI.scraper import cli

    observed_transaction_status: list[object] = []

    def _recording_loader(conn: psycopg.Connection, input_path: Path, *, limit: int | None) -> LoadResult:
        observed_transaction_status.append(conn.info.transaction_status)
        return LoadResult(inserted=0, skipped=0, quarantined=0, superseded=0, errors=0, elapsed_seconds=0.0)

    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(cli, "load_wi_transactions_with_filings", _recording_loader)
        connection = get_connection()
        try:
            cli._load_path(connection, Path("unused.csv"), data_type="transactions", limit=3)
        finally:
            connection.rollback()
            connection.close()

    assert observed_transaction_status == [psycopg.pq.TransactionStatus.IDLE]
