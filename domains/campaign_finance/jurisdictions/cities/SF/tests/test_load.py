"""Unit tests for the SF filing-aware loader."""

from __future__ import annotations

import csv
from contextlib import ExitStack
from pathlib import Path
from typing import NamedTuple
from unittest.mock import MagicMock
from uuid import uuid4

import psycopg
import pytest

from core.types.python.models import compute_record_hash
from domains.campaign_finance.ingest.filing_loader import generate_synthetic_committee_id
from domains.campaign_finance.jurisdictions._bulk_fixture_support import (
    BulkFixtureInterruption,
    bulk_fixture_entity_row_counts,
    bulk_fixture_row_counts,
    install_write_interrupt,
    seed_bulk_fixture,
    suppress_first_writes,
)
from domains.campaign_finance.jurisdictions.cities.SF.scraper import load as sf_load
from domains.campaign_finance.jurisdictions.cities.SF.scraper.load import (
    LoadResult,
    _to_json_safe,
    ensure_sf_data_source,
    load_sf_transactions_with_filings,
)
from domains.campaign_finance.jurisdictions.cities.SF.scraper.parse import parse_transactions

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_TRANSACTIONS_PATH = _FIXTURE_DIR / "sample_transactions.csv"

_SF_DOMAIN = "campaign_finance"
_SF_JURISDICTION = "municipality/SF"
_DS_UUID = uuid4()


class TestEnsureSfDataSource:
    """Tests for ensure_sf_data_source() creating/retrieving the SF data source."""

    def test_creates_data_source_with_correct_metadata(self, monkeypatch: pytest.MonkeyPatch) -> None:
        conn = MagicMock()
        mock_ensure = MagicMock(return_value=_DS_UUID)
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.SF.scraper.load.ensure_data_source",
            mock_ensure,
        )

        result = ensure_sf_data_source(conn)

        mock_ensure.assert_called_once()
        data_source_arg = mock_ensure.call_args[0][1]
        assert data_source_arg.domain == _SF_DOMAIN
        assert data_source_arg.jurisdiction == _SF_JURISDICTION
        assert "SF Ethics" in data_source_arg.name
        assert result == _DS_UUID

    def test_is_idempotent_returns_same_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        conn = MagicMock()
        mock_ensure = MagicMock(return_value=_DS_UUID)
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.SF.scraper.load.ensure_data_source",
            mock_ensure,
        )

        first = ensure_sf_data_source(conn)
        second = ensure_sf_data_source(conn)

        assert first == second


# Removed test_skips_duplicate_source_record (false positive 2026-04-26):
# the previous version set up mocks but never called the loader,
# asserting `True` and silently passing without exercising the dedupe
# path. The real dedupe coverage is implicit in
# TestLoadSfTransactionsWithFilings::test_returns_load_result_with_correct_counts
# which asserts result.skipped == 0 in the no-duplicate path. A
# dedicated "skipped > 0 when source_record already exists" test should
# be added later under TestLoadSfTransactionsWithFilings.


class TestLoadSfTransactionsWithFilings:
    """Tests for the main loader entry point."""

    def test_returns_load_result_with_correct_counts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        conn = MagicMock()
        conn.info.transaction_status = 0  # IDLE

        mock_ensure_ds = MagicMock(return_value=_DS_UUID)
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.SF.scraper.load.ensure_data_source",
            mock_ensure_ds,
        )

        # Mock try_insert_source_record to return a UUID for each row
        mock_try_insert = MagicMock(side_effect=[uuid4() for _ in range(10)])
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.SF.scraper.load.try_insert_source_record",
            mock_try_insert,
        )

        # Mock the relational layer (filing/transaction upserts)
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.SF.scraper.load.upsert_filing",
            MagicMock(side_effect=lambda conn, f: f.id),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.SF.scraper.load.upsert_transaction",
            MagicMock(side_effect=lambda conn, t: t.id),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.SF.scraper.load.ensure_state_committee",
            MagicMock(return_value=uuid4()),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.SF.scraper.load.resolve_organization_by_canonical_name",
            MagicMock(return_value=uuid4()),
        )

        result = load_sf_transactions_with_filings(conn, _SAMPLE_TRANSACTIONS_PATH)

        assert isinstance(result, LoadResult)
        # Fixture has 10 data rows (all 2025–2026, above default year_from cutoff)
        assert result.inserted == 10
        assert result.skipped == 0
        assert result.errors == 0
        assert result.elapsed_seconds >= 0.0

    def test_respects_limit_parameter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        conn = MagicMock()
        conn.info.transaction_status = 0  # IDLE

        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.SF.scraper.load.ensure_data_source",
            MagicMock(return_value=_DS_UUID),
        )

        mock_try_insert = MagicMock(side_effect=[uuid4() for _ in range(10)])
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.SF.scraper.load.try_insert_source_record",
            mock_try_insert,
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.SF.scraper.load.upsert_filing",
            MagicMock(side_effect=lambda conn, f: f.id),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.SF.scraper.load.upsert_transaction",
            MagicMock(side_effect=lambda conn, t: t.id),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.SF.scraper.load.ensure_state_committee",
            MagicMock(return_value=uuid4()),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.SF.scraper.load.resolve_organization_by_canonical_name",
            MagicMock(return_value=uuid4()),
        )

        result = load_sf_transactions_with_filings(conn, _SAMPLE_TRANSACTIONS_PATH, limit=2)

        assert isinstance(result, LoadResult)
        assert result.inserted == 2

    def test_provenance_written_before_relational_rows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify two-pass: source records first, then filing+transaction upserts."""
        conn = MagicMock()
        conn.info.transaction_status = 0  # IDLE

        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.SF.scraper.load.ensure_data_source",
            MagicMock(return_value=_DS_UUID),
        )

        call_order: list[str] = []

        def track_source_record(conn, sr):
            call_order.append("source_record")
            return uuid4()

        def track_upsert_filing(conn, f):
            call_order.append("upsert_filing")
            return f.id

        def track_upsert_transaction(conn, t):
            call_order.append("upsert_transaction")
            return t.id

        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.SF.scraper.load.try_insert_source_record",
            track_source_record,
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.SF.scraper.load.upsert_filing",
            track_upsert_filing,
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.SF.scraper.load.upsert_transaction",
            track_upsert_transaction,
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.SF.scraper.load.ensure_state_committee",
            MagicMock(return_value=uuid4()),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.SF.scraper.load.resolve_organization_by_canonical_name",
            MagicMock(return_value=uuid4()),
        )

        load_sf_transactions_with_filings(conn, _SAMPLE_TRANSACTIONS_PATH, limit=1)

        # All source_record calls must come before any filing/transaction calls
        source_end = max(i for i, c in enumerate(call_order) if c == "source_record")
        filing_start = min(
            (i for i, c in enumerate(call_order) if c in ("upsert_filing", "upsert_transaction")),
            default=len(call_order),
        )
        assert source_end < filing_start, f"Provenance not written before relational: {call_order}"

    def test_committee_uses_fppc_id_when_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify loader prefers fppc_id for committee identity."""
        conn = MagicMock()
        conn.info.transaction_status = 0

        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.SF.scraper.load.ensure_data_source",
            MagicMock(return_value=_DS_UUID),
        )

        mock_try_insert = MagicMock(side_effect=[uuid4() for _ in range(10)])
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.SF.scraper.load.try_insert_source_record",
            mock_try_insert,
        )

        committee_calls: list[tuple] = []
        mock_committee_id = uuid4()

        def track_ensure_committee(conn, *, state, native_committee_id, organization_id):
            committee_calls.append((state, native_committee_id))
            return mock_committee_id

        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.SF.scraper.load.ensure_state_committee",
            track_ensure_committee,
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.SF.scraper.load.upsert_filing",
            MagicMock(side_effect=lambda conn, f: f.id),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.SF.scraper.load.upsert_transaction",
            MagicMock(side_effect=lambda conn, t: t.id),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.SF.scraper.load.resolve_organization_by_canonical_name",
            MagicMock(return_value=uuid4()),
        )

        load_sf_transactions_with_filings(conn, _SAMPLE_TRANSACTIONS_PATH, limit=1)

        # Fixture row 1 has fppc_id "1488379" — should use that as native_committee_id
        assert len(committee_calls) >= 1
        state, native_id = committee_calls[0]
        assert state == "CA"
        assert native_id == "1488379"


# --- Stage 4: each pass commits its completed batches mid-loop ----------------
#
# DB-backed acceptance specimens, deliberately unmocked: the point is what a *second*
# connection can see, which mocked writes cannot demonstrate. They sit beside the mocked
# unit tests above rather than replacing them.
#
# `_EXPECTED_DURABLE_BATCH_ROWS` is a frozen literal, deliberately NOT read from
# `sf_load._COMMIT_BATCH_ROWS`. The falsifiability probe for these specimens monkeypatches
# that module constant above the fixture size; an expectation derived from the live
# constant would move with the probe and they could never go red.

_EXPECTED_DURABLE_BATCH_ROWS = 1_000
_SF_BULK_ROW_COUNT = _EXPECTED_DURABLE_BATCH_ROWS + 1
# Rows whose provenance insert is suppressed, so pass 2 finds no source record for them,
# skips them, and must still count them towards its boundary.
_SF_SKIPPED_PROVENANCE_ROWS = 3
# Every row shares one committee, and the loader writes no contributor person or address
# rows, so a completed load's whole entity footprint is that one committee.
_SF_LOADED_COMMITTEE_ROWS = 1


class SFBulkFixture(NamedTuple):
    """One synthetic SF transactions CSV and the identities it writes."""

    transactions_path: Path
    run_suffix: str
    fppc_id: str
    source_record_keys: list[str]

    @property
    def committee_fec_id(self) -> str:
        return generate_synthetic_committee_id("CA", self.fppc_id)


def _write_sf_transaction_fixture(tmp_path: Path, *, row_count: int) -> SFBulkFixture:
    """Write a transactions CSV whose every identity is unique to this run.

    All rows share one per-run ``fppc_id`` and ``filing_id_number`` so the load resolves a
    single committee and filing, while each row carries a distinct ``transaction_id`` and
    contributor surname — and therefore a distinct whole-row hash and source-record key.
    That is what lets a bulk fixture cross ``sf_load._COMMIT_BATCH_ROWS`` and still be
    cleaned up by its own scoped keys, and what keeps two fixtures running concurrently
    under xdist from resolving to, and then deleting, each other's rows.
    """
    if row_count < 1:
        raise ValueError(f"row_count must be >= 1, got {row_count}")

    run_suffix = uuid4().hex[:12]
    fppc_id = f"9{int(run_suffix[:8], 16) % 10_000_000:07d}"
    transactions_path = tmp_path / f"sf_bounded_{run_suffix}_transactions.csv"

    with _SAMPLE_TRANSACTIONS_PATH.open(encoding="utf-8", newline="") as sample_file:
        reader = csv.DictReader(sample_file)
        fieldnames = list(reader.fieldnames or [])
        base_row = next(reader)

    rows: list[dict[str, str]] = []
    for index in range(row_count):
        row = dict(base_row)
        row["fppc_id"] = fppc_id
        row["filing_id_number"] = f"9{run_suffix[:8]}"
        row["filer_name"] = f"SF Bounded Commit Test Committee {run_suffix}"
        row["transaction_id"] = f"BATCH{run_suffix}{index}"
        row["transaction_last_name"] = f"Batch Donor {run_suffix} {index}"
        rows.append(row)

    with transactions_path.open("w", encoding="utf-8", newline="") as fixture_file:
        writer = csv.DictWriter(fixture_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    source_record_keys = [compute_record_hash(_to_json_safe(row)) for row in parse_transactions(transactions_path)]
    return SFBulkFixture(
        transactions_path=transactions_path,
        run_suffix=run_suffix,
        fppc_id=fppc_id,
        source_record_keys=source_record_keys,
    )


def _seed_sf_bulk_fixture(
    resources: ExitStack,
    db_conn: psycopg.Connection,
    tmp_path: Path,
) -> SFBulkFixture:
    """Write the bulk fixture and hand it to the shared seeding contract."""
    fixture = _write_sf_transaction_fixture(tmp_path, row_count=_SF_BULK_ROW_COUNT)
    seed_bulk_fixture(resources, db_conn, fixture, expected_unique_source_record_keys=_SF_BULK_ROW_COUNT)
    return fixture


@pytest.mark.parametrize(
    ("interrupted_pass", "write_attribute"),
    [
        ("provenance", "try_insert_source_record"),
        ("relational", "upsert_transaction"),
    ],
)
def test_load_sf_transactions_with_filings_commits_each_pass_batch_mid_loop(
    db_conn: psycopg.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interrupted_pass: str,
    write_attribute: str,
) -> None:
    """Interrupting either pass after 1,000 rows leaves exactly those 1,000 durable.

    Before Stage 4 each pass committed once, at the end of its section, so either
    interruption discarded everything that pass had written and an independent connection
    saw zero.
    """
    with ExitStack() as resources:
        fixture = _seed_sf_bulk_fixture(resources, db_conn, tmp_path)
        write_counts = install_write_interrupt(
            monkeypatch,
            sf_load,
            write_attribute,
            raise_after_writes=_EXPECTED_DURABLE_BATCH_ROWS,
        )

        with pytest.raises(BulkFixtureInterruption):
            load_sf_transactions_with_filings(db_conn, fixture.transactions_path)
        db_conn.rollback()

        assert write_counts["writes"] == _SF_BULK_ROW_COUNT
        source_record_count, transaction_count = bulk_fixture_row_counts(fixture)
        if interrupted_pass == "provenance":
            # Pass 1 died on row 1,001, so its first full batch is durable and pass 2
            # never ran at all — hence no committee either.
            assert source_record_count == _EXPECTED_DURABLE_BATCH_ROWS
            assert transaction_count == 0
            expected_committee_rows = 0
        else:
            # Pass 1 completed and flushed every row; pass 2 died on row 1,001.
            assert source_record_count == _SF_BULK_ROW_COUNT
            assert transaction_count == _EXPECTED_DURABLE_BATCH_ROWS
            expected_committee_rows = _SF_LOADED_COMMITTEE_ROWS

        # The SF loader resolves a committee organization in pass 2 and writes no
        # contributor person or address rows at all. The stack's cleanup deletes the
        # committee and its organization and then re-reads this same count, so a cleanup
        # that stops covering them fails this specimen.
        assert bulk_fixture_entity_row_counts(fixture) == {
            "person": 0,
            "organization": expected_committee_rows,
            "address": 0,
            "committee": expected_committee_rows,
        }


def test_load_sf_relational_batch_boundary_advances_on_missing_provenance(
    db_conn: psycopg.Connection,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pass-2 rows with no provenance still advance pass 2's commit boundary.

    Three rows are denied a source record in pass 1, so pass 2 skips them without writing
    anything. The boundary counts iterated rows rather than linked ones, so it still fires
    on iteration 1,000 — with only 997 transactions written by then. Counting linked rows
    instead would push the first commit three rows later, past the interrupt, and leave
    nothing durable.
    """
    with ExitStack() as resources:
        fixture = _seed_sf_bulk_fixture(resources, db_conn, tmp_path)

        suppress_first_writes(
            monkeypatch,
            sf_load,
            "try_insert_source_record",
            suppress_first=_SF_SKIPPED_PROVENANCE_ROWS,
        )
        expected_durable_transactions = _EXPECTED_DURABLE_BATCH_ROWS - _SF_SKIPPED_PROVENANCE_ROWS
        write_counts = install_write_interrupt(
            monkeypatch,
            sf_load,
            "upsert_transaction",
            raise_after_writes=expected_durable_transactions,
        )

        with pytest.raises(BulkFixtureInterruption):
            load_sf_transactions_with_filings(db_conn, fixture.transactions_path)
        db_conn.rollback()

        assert write_counts["writes"] == expected_durable_transactions + 1
        source_record_count, transaction_count = bulk_fixture_row_counts(fixture)
        assert source_record_count == _SF_BULK_ROW_COUNT - _SF_SKIPPED_PROVENANCE_ROWS
        assert transaction_count == expected_durable_transactions
