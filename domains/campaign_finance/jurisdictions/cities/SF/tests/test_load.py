"""Unit tests for the SF filing-aware loader."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from domains.campaign_finance.jurisdictions.cities.SF.scraper.load import (
    LoadResult,
    ensure_sf_data_source,
    load_sf_transactions_with_filings,
)

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
