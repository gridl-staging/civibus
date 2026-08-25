"""Tests for Virginia campaign finance DB loader.

Covers pure helper functions (no DB required), transaction_type invariants, and the
DB-backed commit-boundary specimens that prove the loader entry point owns its own
outer transaction.
"""

from __future__ import annotations

import csv
import inspect
from contextlib import ExitStack
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
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
from domains.campaign_finance.jurisdictions.states.VA.scraper import load
from domains.campaign_finance.jurisdictions.states.VA.scraper.load import (
    LoadResult,
    _build_contributor_name,
    _build_va_filing_fec_id,
    _parse_va_amount,
    _parse_va_date,
    _va_source_record_key,
    load_va_contributions_with_filings,
)
from domains.campaign_finance.jurisdictions.states.VA.scraper.load_test_support import (
    write_va_contribution_fixture,
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


# ---------------------------------------------------------------------------
# Stage 2: the entry point owns its outer transaction and commits each batch
# ---------------------------------------------------------------------------
#
# `_EXPECTED_DURABLE_BATCH_ROWS` is a frozen literal, deliberately NOT read from a live
# loader constant: the boundary these specimens prove is exactly 1,000 rows, and an
# expectation derived from the loader could never go red against a broken loader.

_EXPECTED_DURABLE_BATCH_ROWS = 1_000
_VA_BULK_ROW_COUNT = _EXPECTED_DURABLE_BATCH_ROWS + 1
# The caller-owned invariant does not depend on crossing the batch boundary, so it uses a
# small fixture to keep the full phase 1 + phase 2 load off the suite's critical path.
_VA_CALLER_ARM_ROW_COUNT = 5


def test_write_va_contribution_fixture_produces_unique_keys_and_one_committee(tmp_path: Path) -> None:
    """The bulk writer gives every row a distinct source-record key but one shared committee."""
    fixture = write_va_contribution_fixture(tmp_path, row_count=_VA_BULK_ROW_COUNT)

    assert len(fixture.source_record_keys) == _VA_BULK_ROW_COUNT
    assert len(set(fixture.source_record_keys)) == _VA_BULK_ROW_COUNT

    with fixture.input_path.open(encoding="utf-8", newline="") as csv_file:
        written_rows = list(csv.DictReader(csv_file))
    assert {row["CommitteeContactId"] for row in written_rows} == {fixture.committee_native_id}
    assert {row["ReportId"] for row in written_rows} == {f"REPORT{fixture.run_suffix}"}


def test_load_va_contributions_with_filings_commits_source_record_batch_mid_loop(
    db_conn: psycopg.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An interrupt after 1,000 source records leaves exactly those 1,000 durable.

    With the pre-Stage-2 ordering `_load_va_file` resolved the data source before sampling
    the transaction status, so it read INTRANS, decided it did not manage the outer
    transaction, and turned every `commit_managed_transaction` — including phase 1's
    1,000-row boundary — into a no-op. This interruption then discarded all 1,000 rows and
    an independent connection saw zero.
    """
    with ExitStack() as resources:
        fixture = seed_written_bulk_fixture(
            resources,
            db_conn,
            lambda: write_va_contribution_fixture(tmp_path, row_count=_VA_BULK_ROW_COUNT),
            row_count=_VA_BULK_ROW_COUNT,
        )
        write_counts = install_write_interrupt(
            monkeypatch,
            load,
            "try_insert_source_record",
            raise_after_writes=_EXPECTED_DURABLE_BATCH_ROWS,
        )

        with pytest.raises(BulkFixtureInterruption):
            load_va_contributions_with_filings(db_conn, fixture.input_path)
        db_conn.rollback()

        # Phase 1 flushed its first full batch at row 1,000 and was interrupted on row 1,001,
        # so exactly that batch of source records is durable. Phase 2 never started, so no
        # cf.transaction rows exist.
        assert write_counts["writes"] == _VA_BULK_ROW_COUNT
        source_record_count, transaction_count = bulk_fixture_row_counts(fixture)
        assert source_record_count == _EXPECTED_DURABLE_BATCH_ROWS
        assert transaction_count == 0


@pytest.mark.integration
def test_load_va_contributions_with_filings_commits_relational_batch_mid_loop(
    db_conn: psycopg.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An interrupt after 1,000 relational rows leaves exactly those 1,000 durable.

    Before the relational boundary fix, an interruption on transaction 1,001 discarded
    every linked row because the pass committed only at the end of the job.
    `BulkFixtureInterruption` subclasses `BaseException` on purpose: that is what carries it
    past `try_row_without_savepoint`'s `except Exception` (`load_utils.py:189`) and past
    `_load_va_file`'s `except Exception` rollback arm, so the interrupt
    propagates as a genuine interruption instead of being counted as a row error.
    """
    with ExitStack() as resources:
        fixture = seed_written_bulk_fixture(
            resources,
            db_conn,
            lambda: write_va_contribution_fixture(tmp_path, row_count=_VA_BULK_ROW_COUNT),
            row_count=_VA_BULK_ROW_COUNT,
        )
        # Bind the interrupt on the module global before the entry-point call: `_load_va_phase2`
        # captures `txn_upserter` from this attribute at function entry. Only the
        # contributions arm runs for this fixture, so `_upsert_va_expenditure_transaction` is
        # left alone.
        write_counts = install_write_interrupt(
            monkeypatch,
            load,
            "_upsert_va_contribution_transaction",
            raise_after_writes=_EXPECTED_DURABLE_BATCH_ROWS,
        )

        with pytest.raises(BulkFixtureInterruption):
            load_va_contributions_with_filings(db_conn, fixture.input_path)
        db_conn.rollback()

        # Phase 1 ran to completion so all 1,001 source records are durable; the relational
        # pass was interrupted on transaction 1,001, so exactly its first full batch survives.
        assert write_counts["writes"] == _VA_BULK_ROW_COUNT
        assert bulk_fixture_row_counts(fixture) == (_VA_BULK_ROW_COUNT, _EXPECTED_DURABLE_BATCH_ROWS)


def test_load_va_contributions_with_filings_writes_into_caller_transaction(
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> None:
    """A caller-supplied INTRANS connection owns the commit: the loader writes but never commits.

    Holds both before and after the Stage 2 ordering fix — when the caller hands over an open
    transaction the entry point must observe it does not manage it — so it is a standing
    invariant, not part of the red evidence.
    """
    with ExitStack() as resources:
        fixture = seed_written_bulk_fixture(
            resources,
            db_conn,
            lambda: write_va_contribution_fixture(tmp_path, row_count=_VA_CALLER_ARM_ROW_COUNT),
            row_count=_VA_CALLER_ARM_ROW_COUNT,
        )
        db_conn.execute("BEGIN")
        assert_loader_arm_is_caller_owned(
            fixture,
            db_conn,
            expected_source_records=_VA_CALLER_ARM_ROW_COUNT,
            run_loader=lambda: load_va_contributions_with_filings(db_conn, fixture.input_path),
        )


def test_cli_load_path_hands_the_loader_an_idle_connection(db_conn: psycopg.Connection) -> None:
    """`cli._load_path` must hand the loader an IDLE connection.

    A data-source lookup left open would make the loader read INTRANS and silently drop its
    1,000-row commit boundary — the exact defect Stage 2 fixes inside the entry point.
    """
    from domains.campaign_finance.jurisdictions.states.VA.scraper import cli

    observed_transaction_status: list[object] = []

    def _recording_loader(conn: psycopg.Connection, input_path: Path, *, limit: int | None) -> LoadResult:
        observed_transaction_status.append(conn.info.transaction_status)
        return LoadResult(inserted=0, skipped=0, quarantined=0, superseded=0, errors=0, elapsed_seconds=0.0)

    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(cli, "load_va_contributions_with_filings", _recording_loader)
        connection = get_connection()
        try:
            cli._load_path(connection, Path("unused.csv"), data_type="contributions", limit=3)
        finally:
            connection.rollback()
            connection.close()

    assert observed_transaction_status == [psycopg.pq.TransactionStatus.IDLE]
