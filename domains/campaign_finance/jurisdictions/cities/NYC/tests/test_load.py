"""Unit tests for the NYC filing-aware loader."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from domains.campaign_finance.jurisdictions.cities.NYC.scraper.load import (
    LoadResult,
    _upsert_nyc_filing_and_transaction,
    ensure_nyc_data_source,
    load_nyc_transactions_with_filings,
)

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_TRANSACTIONS_PATH = _FIXTURE_DIR / "sample_transactions.csv"

_NYC_DOMAIN = "campaign_finance"
_NYC_JURISDICTION = "municipality/NYC"
_DS_UUID = uuid4()


class TestEnsureNycDataSource:
    """Tests for ensure_nyc_data_source() creating/retrieving the NYC data source."""

    def test_creates_data_source_with_correct_metadata(self, monkeypatch: pytest.MonkeyPatch) -> None:
        conn = MagicMock()
        mock_ensure = MagicMock(return_value=_DS_UUID)
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.ensure_data_source",
            mock_ensure,
        )

        result = ensure_nyc_data_source(conn)

        mock_ensure.assert_called_once()
        data_source_arg = mock_ensure.call_args[0][1]
        assert data_source_arg.domain == _NYC_DOMAIN
        assert data_source_arg.jurisdiction == _NYC_JURISDICTION
        assert "NYC CFB" in data_source_arg.name
        assert result == _DS_UUID

    def test_is_idempotent_returns_same_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        conn = MagicMock()
        mock_ensure = MagicMock(return_value=_DS_UUID)
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.ensure_data_source",
            mock_ensure,
        )

        first = ensure_nyc_data_source(conn)
        second = ensure_nyc_data_source(conn)

        assert first == second


class TestLoadNycTransactionsWithFilings:
    """Tests for the main loader entry point."""

    def _patch_db_layer(self, monkeypatch: pytest.MonkeyPatch, insert_count: int = 10) -> None:
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.ensure_data_source",
            MagicMock(return_value=_DS_UUID),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.try_insert_source_record",
            MagicMock(side_effect=[uuid4() for _ in range(insert_count)]),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.upsert_filing",
            MagicMock(side_effect=lambda conn, f: f.id),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.upsert_transaction",
            MagicMock(side_effect=lambda conn, t: t.id),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.ensure_state_committee",
            MagicMock(return_value=uuid4()),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.resolve_organization_by_canonical_name",
            MagicMock(return_value=uuid4()),
        )

    def test_returns_load_result_with_correct_counts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        conn = MagicMock()
        conn.info.transaction_status = 0  # IDLE

        self._patch_db_layer(monkeypatch, insert_count=10)

        result = load_nyc_transactions_with_filings(conn, _SAMPLE_TRANSACTIONS_PATH)

        assert isinstance(result, LoadResult)
        # Fixture has 10 data rows; row 8 (2021) is filtered by default year_from cutoff
        assert result.inserted == 9
        assert result.skipped == 0
        assert result.errors == 0
        assert result.elapsed_seconds >= 0.0

    def test_respects_limit_parameter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        conn = MagicMock()
        conn.info.transaction_status = 0  # IDLE

        self._patch_db_layer(monkeypatch, insert_count=10)

        result = load_nyc_transactions_with_filings(conn, _SAMPLE_TRANSACTIONS_PATH, limit=2)

        assert isinstance(result, LoadResult)
        assert result.inserted == 2

    def test_provenance_written_before_relational_rows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify two-pass: source records first, then filing+transaction upserts."""
        conn = MagicMock()
        conn.info.transaction_status = 0  # IDLE

        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.ensure_data_source",
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
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.try_insert_source_record",
            track_source_record,
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.upsert_filing",
            track_upsert_filing,
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.upsert_transaction",
            track_upsert_transaction,
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.ensure_state_committee",
            MagicMock(return_value=uuid4()),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.resolve_organization_by_canonical_name",
            MagicMock(return_value=uuid4()),
        )

        load_nyc_transactions_with_filings(conn, _SAMPLE_TRANSACTIONS_PATH, limit=1)

        source_end = max(i for i, c in enumerate(call_order) if c == "source_record")
        filing_start = min(
            (i for i, c in enumerate(call_order) if c in ("upsert_filing", "upsert_transaction")),
            default=len(call_order),
        )
        assert source_end < filing_start, f"Provenance not written before relational: {call_order}"

    def test_committee_uses_recipid_with_state_ny(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify loader uses RECIPID for committee identity with state='NY'."""
        conn = MagicMock()
        conn.info.transaction_status = 0

        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.ensure_data_source",
            MagicMock(return_value=_DS_UUID),
        )

        mock_try_insert = MagicMock(side_effect=[uuid4() for _ in range(10)])
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.try_insert_source_record",
            mock_try_insert,
        )

        committee_calls: list[tuple] = []
        mock_committee_id = uuid4()

        def track_ensure_committee(conn, *, state, native_committee_id, organization_id):
            committee_calls.append((state, native_committee_id))
            return mock_committee_id

        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.ensure_state_committee",
            track_ensure_committee,
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.upsert_filing",
            MagicMock(side_effect=lambda conn, f: f.id),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.upsert_transaction",
            MagicMock(side_effect=lambda conn, t: t.id),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.resolve_organization_by_canonical_name",
            MagicMock(return_value=uuid4()),
        )

        load_nyc_transactions_with_filings(conn, _SAMPLE_TRANSACTIONS_PATH, limit=1)

        # Fixture row 1 has RECIPID "1682" — should use that as native_committee_id with state="NY"
        assert len(committee_calls) >= 1
        state, native_id = committee_calls[0]
        assert state == "NY"
        assert native_id == "1682"


class TestFilingLookupCacheSafety:
    """Regression: filing_lookup cache must only be populated after BOTH
    upsert_filing and upsert_transaction succeed.

    If upsert_transaction raises, the savepoint rolls back — a stale cache
    entry would cause FK violations on subsequent rows.
    """

    @staticmethod
    def _make_nyc_row(recipid: str = "TEST001") -> dict[str, object]:
        return {
            "RECIPID": recipid,
            "RECIPNAME": "Test Candidate",
            "FILING": "7",
            "ELECTION": "2025",
            "SCHEDULE": "ABC",
            "REFNO": "R0099999",
            "NAME": "Test Donor",
            "C_CODE": "IND",
            "AMNT": Decimal("500.00"),
            "DATE": date(2025, 3, 15),
        }

    def test_cache_empty_when_upsert_transaction_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = MagicMock()
        filing_lookup: dict = {}
        mock_filing_id = uuid4()

        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.resolve_organization_by_canonical_name",
            MagicMock(return_value=uuid4()),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.ensure_state_committee",
            MagicMock(return_value=uuid4()),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.upsert_filing",
            MagicMock(return_value=mock_filing_id),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.upsert_transaction",
            MagicMock(side_effect=RuntimeError("Simulated DB failure")),
        )

        row = self._make_nyc_row()
        with pytest.raises(RuntimeError, match="Simulated DB failure"):
            _upsert_nyc_filing_and_transaction(
                conn,
                row,
                uuid4(),
                filing_lookup=filing_lookup,
            )

        assert len(filing_lookup) == 0, "filing_lookup must stay empty when upsert_transaction fails"

    def test_cache_populated_after_successful_upserts(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = MagicMock()
        filing_lookup: dict = {}
        mock_filing_id = uuid4()

        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.resolve_organization_by_canonical_name",
            MagicMock(return_value=uuid4()),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.ensure_state_committee",
            MagicMock(return_value=uuid4()),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.upsert_filing",
            MagicMock(return_value=mock_filing_id),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.upsert_transaction",
            MagicMock(),
        )

        row = self._make_nyc_row()
        _upsert_nyc_filing_and_transaction(
            conn,
            row,
            uuid4(),
            filing_lookup=filing_lookup,
        )

        assert len(filing_lookup) == 1, "filing_lookup must be populated after both upserts succeed"

    def test_cache_retry_after_failure_populates_on_success(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """First call fails (upsert_transaction raises), second call succeeds.
        Verify cache is empty after failure and populated after success."""
        conn = MagicMock()
        filing_lookup: dict = {}
        mock_filing_id = uuid4()

        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.resolve_organization_by_canonical_name",
            MagicMock(return_value=uuid4()),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.ensure_state_committee",
            MagicMock(return_value=uuid4()),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.upsert_filing",
            MagicMock(return_value=mock_filing_id),
        )

        # First call: upsert_transaction raises
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.upsert_transaction",
            MagicMock(side_effect=RuntimeError("Transient failure")),
        )

        row = self._make_nyc_row()
        with pytest.raises(RuntimeError):
            _upsert_nyc_filing_and_transaction(
                conn,
                row,
                uuid4(),
                filing_lookup=filing_lookup,
            )
        assert len(filing_lookup) == 0

        # Second call: upsert_transaction succeeds
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.NYC.scraper.load.upsert_transaction",
            MagicMock(),
        )
        _upsert_nyc_filing_and_transaction(
            conn,
            row,
            uuid4(),
            filing_lookup=filing_lookup,
        )
        assert len(filing_lookup) == 1
