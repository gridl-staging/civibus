from __future__ import annotations

import contextlib
import csv
from contextlib import ExitStack
from datetime import date
from pathlib import Path
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
from domains.campaign_finance.jurisdictions.states.NJ.scraper import load as nj_load
from domains.campaign_finance.jurisdictions.states.NJ.scraper.load import (
    LoadResult,
    _build_nj_filing_fec_id,
    _normalized_column_text,
    _parse_nj_amount,
    _parse_nj_date,
    load_nj_contributions_with_filings,
)
from domains.campaign_finance.jurisdictions.states.NJ.scraper.load_test_support import (
    write_nj_contribution_fixture,
)
from domains.campaign_finance.jurisdictions.states.NJ.scraper.parse import parse_contributions


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


def test_load_nj_relational_contributions_drops_filing_cached_by_rolled_back_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    connection.info.transaction_status = psycopg.pq.TransactionStatus.IDLE
    connection.transaction.side_effect = lambda: contextlib.nullcontext()
    rows = [{"EntityName": "Committee A"}, {"EntityName": "Committee A"}]
    source_record_ids = [uuid4(), uuid4()]
    filing_entries = [
        nj_load._NJFilingLookupEntry(uuid4(), uuid4(), source_record_id) for source_record_id in source_record_ids
    ]
    observed_filing_lookups: list[dict[str, nj_load._NJFilingLookupEntry]] = []

    monkeypatch.setattr(nj_load, "_select_nj_source_record_id", MagicMock(side_effect=source_record_ids))
    monkeypatch.setattr(nj_load, "commit_managed_transaction", MagicMock())
    monkeypatch.setattr(nj_load, "_build_nj_filing_fec_id", MagicMock(return_value="NJ-filing"))

    def cache_new_filing(_conn, _row, *, source_record_id, filing_lookup):
        observed_filing_lookups.append(dict(filing_lookup))
        entry = filing_entries[len(observed_filing_lookups) - 1]
        assert entry.source_record_id == source_record_id
        filing_lookup["NJ-filing"] = entry
        return entry

    monkeypatch.setattr(nj_load, "_upsert_nj_filing", cache_new_filing)
    monkeypatch.setattr(
        nj_load,
        "_upsert_nj_contribution_with_filing",
        MagicMock(side_effect=[RuntimeError("row rollback"), None]),
    )

    errors = nj_load._load_nj_relational_contributions(connection, rows, data_source_id=uuid4(), limit=None)

    assert errors == 1
    assert observed_filing_lookups == [{}, {}]

    monkeypatch.setattr(nj_load, "_select_nj_source_record_id", MagicMock(return_value=uuid4()))
    monkeypatch.setattr(nj_load, "_upsert_nj_filing", MagicMock(side_effect=ValueError("malformed filing")))
    monkeypatch.setattr(
        nj_load,
        "_build_nj_filing_fec_id",
        MagicMock(side_effect=ValueError("filing key unavailable")),
    )

    # Cleanup must not replace the row error when the malformed fields also prevent the
    # filing key from being reconstructed.
    assert (
        nj_load._load_nj_relational_contributions(
            connection,
            [{"EntityName": "Committee B"}],
            data_source_id=uuid4(),
            limit=None,
        )
        == 1
    )


def test_upsert_nj_contribution_uses_source_record_key_as_transaction_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = {"EntityName": "Committee A", "ContributionAmount": "125.00"}
    upsert_transaction = MagicMock()
    monkeypatch.setattr(nj_load, "resolve_transaction_counterparty_ids", MagicMock(return_value=(None, None)))
    monkeypatch.setattr(nj_load, "_resolve_nj_transaction_address_id", MagicMock(return_value=None))
    monkeypatch.setattr(nj_load, "upsert_transaction", upsert_transaction)

    nj_load._upsert_nj_contribution_with_filing(
        MagicMock(),
        row,
        filing_id=uuid4(),
        committee_id=uuid4(),
        source_record_id=uuid4(),
    )

    transaction = upsert_transaction.call_args.args[1]
    assert transaction.transaction_identifier == nj_load._nj_source_record_key(row)


# --- Stage 4: the entry point owns its outer transaction and commits each batch ---
#
# `_EXPECTED_DURABLE_BATCH_ROWS` is a frozen literal, deliberately NOT read from a live
# loader constant: the boundary these specimens prove is exactly 1,000 rows, and an
# expectation derived from the loader could never go red against a broken loader.

_EXPECTED_DURABLE_BATCH_ROWS = 1_000
_NJ_BULK_ROW_COUNT = _EXPECTED_DURABLE_BATCH_ROWS + 1
# The caller-owned invariant does not depend on crossing the batch boundary, so it uses a
# small fixture to keep the full base + relational load off the suite's critical path.
_NJ_CALLER_ARM_ROW_COUNT = 5


def test_write_nj_contribution_fixture_produces_unique_keys_and_one_committee(tmp_path: Path) -> None:
    """The bulk writer gives every row a distinct source-record key but one committee."""
    fixture = write_nj_contribution_fixture(tmp_path, row_count=_NJ_BULK_ROW_COUNT)

    assert len(fixture.source_record_keys) == _NJ_BULK_ROW_COUNT
    assert len(set(fixture.source_record_keys)) == _NJ_BULK_ROW_COUNT

    with fixture.input_path.open(encoding="utf-8", newline="") as csv_file:
        written_rows = list(csv.DictReader(csv_file))
    assert len(written_rows) == _NJ_BULK_ROW_COUNT
    assert {row["EntityName"] for row in written_rows} == {fixture.committee_native_id}
    assert len({row["ElectionYear"] for row in written_rows}) == 1

    parsed_rows = list(parse_contributions(fixture.input_path))
    assert {_build_nj_filing_fec_id(row) for row in parsed_rows} == {_build_nj_filing_fec_id(parsed_rows[0])}
    assert fixture.committee_native_id == _normalized_column_text(parsed_rows[0], "committee.name")


@pytest.mark.integration
def test_load_nj_contributions_with_filings_commits_source_record_batch_mid_loop(
    db_conn: psycopg.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An interrupt after 1,000 source records leaves exactly those 1,000 durable.

    With the pre-Stage-4 ordering the entry point resolved the data source before sampling
    transaction status, so it read INTRANS and turned the base pass's 1,000-row commit into
    a no-op. This interruption then discarded all 1,000 rows and an observer saw zero.
    """
    with ExitStack() as resources:
        fixture = seed_written_bulk_fixture(
            resources,
            db_conn,
            lambda: write_nj_contribution_fixture(tmp_path, row_count=_NJ_BULK_ROW_COUNT),
            row_count=_NJ_BULK_ROW_COUNT,
        )
        write_counts = install_write_interrupt(
            monkeypatch,
            nj_load,
            "try_insert_source_record",
            raise_after_writes=_EXPECTED_DURABLE_BATCH_ROWS,
        )

        with pytest.raises(BulkFixtureInterruption):
            load_nj_contributions_with_filings(db_conn, fixture.input_path)
        db_conn.rollback()

        assert write_counts["writes"] == _NJ_BULK_ROW_COUNT
        assert bulk_fixture_row_counts(fixture) == (_EXPECTED_DURABLE_BATCH_ROWS, 0)


@pytest.mark.integration
def test_load_nj_contributions_with_filings_commits_relational_batch_mid_loop(
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
            lambda: write_nj_contribution_fixture(tmp_path, row_count=_NJ_BULK_ROW_COUNT),
            row_count=_NJ_BULK_ROW_COUNT,
        )
        write_counts = install_write_interrupt(
            monkeypatch,
            nj_load,
            "_upsert_nj_contribution_with_filing",
            raise_after_writes=_EXPECTED_DURABLE_BATCH_ROWS,
        )

        with pytest.raises(BulkFixtureInterruption):
            load_nj_contributions_with_filings(db_conn, fixture.input_path)
        db_conn.rollback()

        assert write_counts["writes"] == _NJ_BULK_ROW_COUNT
        assert bulk_fixture_row_counts(fixture) == (_NJ_BULK_ROW_COUNT, _EXPECTED_DURABLE_BATCH_ROWS)


@pytest.mark.integration
def test_load_nj_contributions_with_filings_writes_into_caller_transaction(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    """An INTRANS caller owns the NJ transaction; the loader writes but never commits."""
    with ExitStack() as resources:
        fixture = seed_written_bulk_fixture(
            resources,
            db_conn,
            lambda: write_nj_contribution_fixture(tmp_path, row_count=_NJ_CALLER_ARM_ROW_COUNT),
            row_count=_NJ_CALLER_ARM_ROW_COUNT,
        )
        db_conn.execute("BEGIN")
        assert_loader_arm_is_caller_owned(
            fixture,
            db_conn,
            expected_source_records=_NJ_CALLER_ARM_ROW_COUNT,
            run_loader=lambda: load_nj_contributions_with_filings(db_conn, fixture.input_path),
        )


@pytest.mark.integration
def test_cli_load_path_hands_the_loader_an_idle_connection(db_conn: psycopg.Connection) -> None:
    """`cli._load_path` hands the loader an IDLE connection."""
    from domains.campaign_finance.jurisdictions.states.NJ.scraper import cli

    observed_transaction_status: list[object] = []

    def _recording_loader(conn: psycopg.Connection, input_path: Path, *, limit: int | None) -> LoadResult:
        observed_transaction_status.append(conn.info.transaction_status)
        return LoadResult(inserted=0, skipped=0, quarantined=0, superseded=0, errors=0, elapsed_seconds=0.0)

    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(cli, "load_nj_contributions_with_filings", _recording_loader)
        connection = get_connection()
        try:
            cli._load_path(connection, Path("unused.csv"), data_type="contributions", limit=3)
        finally:
            connection.rollback()
            connection.close()

    assert observed_transaction_status == [psycopg.pq.TransactionStatus.IDLE]
