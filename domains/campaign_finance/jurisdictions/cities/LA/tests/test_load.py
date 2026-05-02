"""Unit tests for the LA filing-aware loader."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from domains.campaign_finance.jurisdictions.cities.LA.scraper.load import (
    LoadResult,
    _build_la_transaction,
    _upsert_la_filing_and_transaction,
    ensure_la_data_source,
    load_la_transactions_with_filings,
)

_FIXTURE_DIR = Path(__file__).parent / "test_fixtures"
_SAMPLE_TRANSACTIONS_PATH = _FIXTURE_DIR / "sample_transactions.csv"

_LA_DOMAIN = "campaign_finance"
_LA_JURISDICTION = "municipality/LA"
_DS_UUID = uuid4()


class TestEnsureLaDataSource:
    """Tests for ensure_la_data_source() creating/retrieving the LA data source."""

    def test_creates_data_source_with_correct_metadata(self, monkeypatch: pytest.MonkeyPatch) -> None:
        conn = MagicMock()
        mock_ensure = MagicMock(return_value=_DS_UUID)
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.ensure_data_source",
            mock_ensure,
        )

        result = ensure_la_data_source(conn)

        mock_ensure.assert_called_once()
        data_source_arg = mock_ensure.call_args[0][1]
        assert data_source_arg.domain == _LA_DOMAIN
        assert data_source_arg.jurisdiction == _LA_JURISDICTION
        assert "LA Ethics" in data_source_arg.name
        assert result == _DS_UUID

    def test_is_idempotent_returns_same_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        conn = MagicMock()
        mock_ensure = MagicMock(return_value=_DS_UUID)
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.ensure_data_source",
            mock_ensure,
        )

        first = ensure_la_data_source(conn)
        second = ensure_la_data_source(conn)

        assert first == second


# Removed test_skips_duplicate_source_record (false positive 2026-04-26):
# the previous version set up mocks but never called the loader,
# asserting `True` and silently passing without exercising the dedupe
# path. Real dedupe coverage lives implicitly in
# TestLoadLaTransactionsWithFilings tests.


class TestLoadLaTransactionsWithFilings:
    """Tests for the main loader entry point."""

    def _patch_db_layer(self, monkeypatch: pytest.MonkeyPatch, insert_count: int = 10) -> None:
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.ensure_data_source",
            MagicMock(return_value=_DS_UUID),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.try_insert_source_record",
            MagicMock(side_effect=[uuid4() for _ in range(insert_count)]),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.upsert_filing",
            MagicMock(side_effect=lambda conn, f: f.id),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.upsert_transaction",
            MagicMock(side_effect=lambda conn, t: t.id),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.ensure_state_committee",
            MagicMock(return_value=uuid4()),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.resolve_organization_by_canonical_name",
            MagicMock(return_value=uuid4()),
        )

    def test_returns_load_result_with_correct_counts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        conn = MagicMock()
        conn.info.transaction_status = 0  # IDLE

        self._patch_db_layer(monkeypatch, insert_count=10)

        result = load_la_transactions_with_filings(conn, _SAMPLE_TRANSACTIONS_PATH)

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

        result = load_la_transactions_with_filings(conn, _SAMPLE_TRANSACTIONS_PATH, limit=2)

        assert isinstance(result, LoadResult)
        assert result.inserted == 2

    def test_provenance_written_before_relational_rows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify two-pass: source records first, then filing+transaction upserts."""
        conn = MagicMock()
        conn.info.transaction_status = 0  # IDLE

        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.ensure_data_source",
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
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.try_insert_source_record",
            track_source_record,
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.upsert_filing",
            track_upsert_filing,
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.upsert_transaction",
            track_upsert_transaction,
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.ensure_state_committee",
            MagicMock(return_value=uuid4()),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.resolve_organization_by_canonical_name",
            MagicMock(return_value=uuid4()),
        )

        load_la_transactions_with_filings(conn, _SAMPLE_TRANSACTIONS_PATH, limit=1)

        source_end = max(i for i, c in enumerate(call_order) if c == "source_record")
        filing_start = min(
            (i for i, c in enumerate(call_order) if c in ("upsert_filing", "upsert_transaction")),
            default=len(call_order),
        )
        assert source_end < filing_start, f"Provenance not written before relational: {call_order}"

    def test_committee_uses_cmt_id_when_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify loader prefers cmt_id for committee identity."""
        conn = MagicMock()
        conn.info.transaction_status = 0

        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.ensure_data_source",
            MagicMock(return_value=_DS_UUID),
        )

        mock_try_insert = MagicMock(side_effect=[uuid4() for _ in range(10)])
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.try_insert_source_record",
            mock_try_insert,
        )

        committee_calls: list[tuple] = []
        mock_committee_id = uuid4()

        def track_ensure_committee(conn, *, state, native_committee_id, organization_id):
            committee_calls.append((state, native_committee_id))
            return mock_committee_id

        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.ensure_state_committee",
            track_ensure_committee,
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.upsert_filing",
            MagicMock(side_effect=lambda conn, f: f.id),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.upsert_transaction",
            MagicMock(side_effect=lambda conn, t: t.id),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.resolve_organization_by_canonical_name",
            MagicMock(return_value=uuid4()),
        )

        load_la_transactions_with_filings(conn, _SAMPLE_TRANSACTIONS_PATH, limit=1)

        # Fixture row 1 has cmt_id "1471359" — should use that as native_committee_id
        assert len(committee_calls) >= 1
        state, native_id = committee_calls[0]
        assert state == "CA"
        assert native_id == "1471359"


class TestBuildLaTransactionRecordHash:
    """Regression: LA data has no native transaction ID field.

    _build_la_transaction must assign record_hash as transaction_identifier.
    The original bug (Stage 4) was the assignment being missing entirely.
    """

    def test_transaction_identifier_equals_record_hash(self) -> None:
        filing_id = uuid4()
        committee_id = uuid4()
        source_record_id = uuid4()
        known_hash = "abc123def456_regression_proof"

        row: dict[str, object] = {
            "con_name": "Test Donor",
            "con_type": "Monetary Contributions",
            "con_amount": Decimal("500.00"),
            "con_date": date(2025, 6, 15),
            "con_city_nm": "Los Angeles",
            "con_state_nm": "CA",
            "con_zip_cd": "90001",
            "con_empr": "Test Corp",
        }

        txn = _build_la_transaction(
            row,
            filing_id=filing_id,
            committee_id=committee_id,
            source_record_id=source_record_id,
            record_hash=known_hash,
        )

        assert txn.transaction_identifier == known_hash

    def test_different_hashes_produce_different_identifiers(self) -> None:
        """Ensure transaction_identifier varies with record_hash, not hardcoded."""
        filing_id = uuid4()
        committee_id = uuid4()
        source_record_id = uuid4()
        row: dict[str, object] = {
            "con_name": "Test Donor",
            "con_amount": Decimal("100.00"),
        }

        txn_a = _build_la_transaction(
            row,
            filing_id=filing_id,
            committee_id=committee_id,
            source_record_id=source_record_id,
            record_hash="hash_a",
        )
        txn_b = _build_la_transaction(
            row,
            filing_id=filing_id,
            committee_id=committee_id,
            source_record_id=source_record_id,
            record_hash="hash_b",
        )

        assert txn_a.transaction_identifier == "hash_a"
        assert txn_b.transaction_identifier == "hash_b"
        assert txn_a.transaction_identifier != txn_b.transaction_identifier


class TestFilingLookupCacheSafety:
    """Regression: filing_lookup cache must only be populated after BOTH
    upsert_filing and upsert_transaction succeed.

    If upsert_transaction raises, the savepoint rolls back — a stale cache
    entry would cause FK violations on subsequent rows.
    """

    @staticmethod
    def _make_la_row(cmt_id: str = "TEST001") -> dict[str, object]:
        return {
            "cmt_id": cmt_id,
            "cmt_nm": "Test Committee",
            "form": "CA460",
            "per_beg_date": date(2025, 1, 1),
            "per_end_date": date(2025, 6, 30),
            "con_name": "Test Donor",
            "con_type": "Monetary Contributions",
            "con_amount": Decimal("100.00"),
            "con_date": date(2025, 3, 15),
        }

    def test_cache_empty_when_upsert_transaction_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = MagicMock()
        filing_lookup: dict = {}
        mock_filing_id = uuid4()

        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.resolve_organization_by_canonical_name",
            MagicMock(return_value=uuid4()),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.ensure_state_committee",
            MagicMock(return_value=uuid4()),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.upsert_filing",
            MagicMock(return_value=mock_filing_id),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.upsert_transaction",
            MagicMock(side_effect=RuntimeError("Simulated DB failure")),
        )

        row = self._make_la_row()
        with pytest.raises(RuntimeError, match="Simulated DB failure"):
            _upsert_la_filing_and_transaction(
                conn,
                row,
                uuid4(),
                "hash_fail",
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
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.resolve_organization_by_canonical_name",
            MagicMock(return_value=uuid4()),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.ensure_state_committee",
            MagicMock(return_value=uuid4()),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.upsert_filing",
            MagicMock(return_value=mock_filing_id),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.upsert_transaction",
            MagicMock(),
        )

        row = self._make_la_row()
        _upsert_la_filing_and_transaction(
            conn,
            row,
            uuid4(),
            "hash_ok",
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
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.resolve_organization_by_canonical_name",
            MagicMock(return_value=uuid4()),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.ensure_state_committee",
            MagicMock(return_value=uuid4()),
        )
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.upsert_filing",
            MagicMock(return_value=mock_filing_id),
        )

        # First call: upsert_transaction raises
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.upsert_transaction",
            MagicMock(side_effect=RuntimeError("Transient failure")),
        )

        row = self._make_la_row()
        with pytest.raises(RuntimeError):
            _upsert_la_filing_and_transaction(
                conn,
                row,
                uuid4(),
                "hash_retry",
                filing_lookup=filing_lookup,
            )
        assert len(filing_lookup) == 0

        # Second call: upsert_transaction succeeds
        monkeypatch.setattr(
            "domains.campaign_finance.jurisdictions.cities.LA.scraper.load.upsert_transaction",
            MagicMock(),
        )
        _upsert_la_filing_and_transaction(
            conn,
            row,
            uuid4(),
            "hash_retry",
            filing_lookup=filing_lookup,
        )
        assert len(filing_lookup) == 1
