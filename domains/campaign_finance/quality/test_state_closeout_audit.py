"""Audit tests for state closeout: helpers, error paths, pull-status, and NC JSON/isolation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from domains.campaign_finance.quality.models import (
    CheckResult,
    JurisdictionSummary,
    QualityReport,
)
from domains.campaign_finance.quality.reconciliation import DataSourceSnapshot
from domains.campaign_finance.quality.state_closeout import (
    RunConfig,
    _compute_file_identity,
    _count_csv_rows,
    _run_co_load,
    _run_ga_load,
    run_state_closeout,
)
from domains.campaign_finance.quality.state_closeout_models import (
    NcCommitteeDocValidation,
)

_FIXED_NOW = datetime(2026, 3, 16, 12, 0, 0, tzinfo=timezone.utc)
_FIXED_DS_ID = uuid4()


def _stub_quality_report(jurisdiction: str) -> QualityReport:
    return QualityReport(
        generated_at=_FIXED_NOW,
        jurisdiction_filter=jurisdiction,
        summaries=[
            JurisdictionSummary(
                jurisdiction=jurisdiction,
                check_results=[
                    CheckResult(name="record_count_reconciliation", status="pass"),
                ],
            )
        ],
    )


# ---------------------------------------------------------------------------
# Helper function unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCountCsvRows:
    def test_header_only(self, tmp_path: Path) -> None:
        csv = tmp_path / "header_only.csv"
        csv.write_text("col_a,col_b,col_c\n", encoding="utf-8")
        assert _count_csv_rows(csv) == 0

    def test_header_plus_data(self, tmp_path: Path) -> None:
        csv = tmp_path / "data.csv"
        csv.write_text("a,b\n1,2\n3,4\n5,6\n", encoding="utf-8")
        assert _count_csv_rows(csv) == 3

    def test_empty_file(self, tmp_path: Path) -> None:
        csv = tmp_path / "empty.csv"
        csv.write_text("", encoding="utf-8")
        assert _count_csv_rows(csv) == 0


@pytest.mark.unit
class TestComputeFileIdentity:
    def test_sha256_and_byte_size(self, tmp_path: Path) -> None:
        f = tmp_path / "test.csv"
        content = b"col_a,col_b\n1,2\n3,4\n"
        f.write_bytes(content)
        sha256_hex, byte_size = _compute_file_identity(f)
        assert byte_size == len(content)
        assert sha256_hex == hashlib.sha256(content).hexdigest()

    def test_empty_file(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.csv"
        f.write_bytes(b"")
        sha256_hex, byte_size = _compute_file_identity(f)
        assert byte_size == 0
        assert sha256_hex == hashlib.sha256(b"").hexdigest()


# ---------------------------------------------------------------------------
# Error path tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestErrorPaths:
    def test_unsupported_jurisdiction_raises(self) -> None:
        config = RunConfig(
            jurisdiction="state/TX",
            data_type="contributions",
            source_file=Path("/data/tx.csv"),
        )
        with pytest.raises(ValueError, match="Unsupported jurisdiction: state/TX"):
            run_state_closeout(MagicMock(), config)

    def test_unsupported_co_data_type_raises(self) -> None:
        config = RunConfig(
            jurisdiction="state/CO",
            data_type="invalid_type",
            source_file=Path("/data/co.csv"),
        )
        with pytest.raises(ValueError, match="Unsupported CO data_type: invalid_type"):
            _run_co_load(MagicMock(), config, _FIXED_DS_ID)

    def test_unsupported_ga_data_type_raises(self) -> None:
        config = RunConfig(
            jurisdiction="state/GA",
            data_type="invalid_type",
            source_file=Path("/data/ga.csv"),
        )
        with pytest.raises(ValueError, match="Unsupported GA data_type: invalid_type"):
            _run_ga_load(MagicMock(), config)


# ---------------------------------------------------------------------------
# Pull-status derivation verification
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPullStatusDerivation:
    """Verify sync_data_source_metadata receives the correct pull_status value."""

    @patch("domains.campaign_finance.quality.state_closeout._discover_and_run")
    @patch("domains.campaign_finance.quality.state_closeout.fetch_data_source_snapshot")
    @patch("domains.campaign_finance.quality.state_closeout.sync_data_source_metadata")
    @patch("domains.campaign_finance.quality.state_closeout._run_co_load")
    @patch("domains.campaign_finance.quality.state_closeout._count_csv_rows")
    @patch("domains.campaign_finance.quality.state_closeout.ensure_co_data_source")
    def test_co_success_status_passed_to_sync(
        self,
        mock_ensure: MagicMock,
        mock_csv_rows: MagicMock,
        mock_load: MagicMock,
        mock_sync: MagicMock,
        mock_snapshot: MagicMock,
        mock_quality: MagicMock,
    ) -> None:
        mock_ensure.return_value = _FIXED_DS_ID
        mock_csv_rows.return_value = 100
        co_result = MagicMock(inserted=90, skipped=10, errors=0, elapsed_seconds=0.5)
        mock_load.return_value = MagicMock(result=co_result, parser_skipped=0)
        mock_snapshot.return_value = DataSourceSnapshot(
            record_count=90, last_pull_status="success", last_pull_at=_FIXED_NOW
        )
        mock_quality.return_value = _stub_quality_report("state/CO")

        config = RunConfig(jurisdiction="state/CO", data_type="contributions", source_file=Path("/data/c.csv"))
        run_state_closeout(MagicMock(), config)
        mock_sync.assert_called_once()
        _, kwargs = mock_sync.call_args
        assert kwargs["pull_status"] == "success"

    @patch("domains.campaign_finance.quality.state_closeout._discover_and_run")
    @patch("domains.campaign_finance.quality.state_closeout.fetch_data_source_snapshot")
    @patch("domains.campaign_finance.quality.state_closeout.sync_data_source_metadata")
    @patch("domains.campaign_finance.quality.state_closeout._run_co_load")
    @patch("domains.campaign_finance.quality.state_closeout._count_csv_rows")
    @patch("domains.campaign_finance.quality.state_closeout.ensure_co_data_source")
    def test_co_partial_status_when_errors_with_inserts(
        self,
        mock_ensure: MagicMock,
        mock_csv_rows: MagicMock,
        mock_load: MagicMock,
        mock_sync: MagicMock,
        mock_snapshot: MagicMock,
        mock_quality: MagicMock,
    ) -> None:
        mock_ensure.return_value = _FIXED_DS_ID
        mock_csv_rows.return_value = 100
        co_result = MagicMock(inserted=50, skipped=10, errors=5, elapsed_seconds=0.5)
        mock_load.return_value = MagicMock(result=co_result, parser_skipped=0)
        mock_snapshot.return_value = DataSourceSnapshot(
            record_count=50, last_pull_status="partial", last_pull_at=_FIXED_NOW
        )
        mock_quality.return_value = _stub_quality_report("state/CO")

        config = RunConfig(jurisdiction="state/CO", data_type="contributions", source_file=Path("/data/c.csv"))
        run_state_closeout(MagicMock(), config)
        _, kwargs = mock_sync.call_args
        # errors > 0 with inserts → "partial" per derive_pull_status_from_counts
        assert kwargs["pull_status"] == "partial"

    @patch("domains.campaign_finance.quality.state_closeout._discover_and_run")
    @patch("domains.campaign_finance.quality.state_closeout.fetch_data_source_snapshot")
    @patch("domains.campaign_finance.quality.state_closeout.sync_data_source_metadata")
    @patch("domains.campaign_finance.quality.state_closeout.load_nc_transactions")
    @patch("domains.campaign_finance.quality.state_closeout._compute_file_identity")
    @patch("domains.campaign_finance.quality.state_closeout.ensure_nc_data_source")
    def test_nc_all_skipped_rerun_is_success(
        self,
        mock_ensure: MagicMock,
        mock_file_id: MagicMock,
        mock_load: MagicMock,
        mock_sync: MagicMock,
        mock_snapshot: MagicMock,
        mock_quality: MagicMock,
    ) -> None:
        """All-skipped, zero-errors rerun should derive pull_status='success'."""
        mock_ensure.return_value = _FIXED_DS_ID
        mock_file_id.return_value = ("ncsha256hex", 12345)
        mock_load.return_value = MagicMock(
            inserted=0, skipped=100, quarantined=0, superseded=0, errors=0, elapsed_seconds=0.5
        )
        mock_snapshot.return_value = DataSourceSnapshot(
            record_count=0, last_pull_status="success", last_pull_at=_FIXED_NOW
        )
        mock_quality.return_value = _stub_quality_report("state/NC")

        config = RunConfig(
            jurisdiction="state/NC",
            data_type="transactions",
            source_file=Path("/data/nc.csv"),
            nc_acquisition_timestamp="2026-03-15T10:00:00Z",
        )
        run_state_closeout(MagicMock(), config)
        _, kwargs = mock_sync.call_args
        assert kwargs["pull_status"] == "success"


# ---------------------------------------------------------------------------
# NC closeout JSON round-trip and committee-doc DB isolation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNcCloseoutJsonAndIsolation:
    """Validate fixture-backed NC closeout JSON and committee-doc DB isolation."""

    @patch("domains.campaign_finance.quality.state_closeout._discover_and_run")
    @patch("domains.campaign_finance.quality.state_closeout.fetch_data_source_snapshot")
    @patch("domains.campaign_finance.quality.state_closeout.sync_data_source_metadata")
    @patch("domains.campaign_finance.quality.state_closeout.load_nc_transactions")
    @patch("domains.campaign_finance.quality.state_closeout._compute_file_identity")
    @patch("domains.campaign_finance.quality.state_closeout._validate_nc_committee_doc")
    @patch("domains.campaign_finance.quality.state_closeout.ensure_nc_data_source")
    def test_nc_evidence_json_round_trips(
        self,
        mock_ensure: MagicMock,
        mock_validate_doc: MagicMock,
        mock_file_id: MagicMock,
        mock_load: MagicMock,
        mock_sync: MagicMock,
        mock_snapshot: MagicMock,
        mock_quality: MagicMock,
    ) -> None:
        """NC closeout evidence serializes to JSON and contains expected fields."""
        mock_ensure.return_value = _FIXED_DS_ID
        mock_file_id.return_value = ("ncsha256hex", 12345)
        mock_load.return_value = MagicMock(
            inserted=80, skipped=10, quarantined=5, superseded=0, errors=0, elapsed_seconds=1.0
        )
        mock_validate_doc.return_value = NcCommitteeDocValidation(
            source_file="/data/nc_committees.csv",
            file_sha256="docshaHEX",
            total_rows=42,
            parse_skipped=3,
        )
        mock_sync.return_value = 80
        mock_snapshot.return_value = DataSourceSnapshot(
            record_count=80, last_pull_status="success", last_pull_at=_FIXED_NOW
        )
        mock_quality.return_value = _stub_quality_report("state/NC")

        config = RunConfig(
            jurisdiction="state/NC",
            data_type="transactions",
            source_file=Path("/data/nc.csv"),
            nc_acquisition_timestamp="2026-03-15T10:00:00Z",
            nc_committee_doc_path=Path("/data/nc_committees.csv"),
        )
        evidence = run_state_closeout(MagicMock(), config)
        raw = evidence.to_json()
        parsed = json.loads(raw)

        assert parsed["jurisdiction"] == "state/NC"
        assert parsed["data_type"] == "transactions"
        assert parsed["nc_evidence"]["transaction_file_sha256"] == "ncsha256hex"
        assert parsed["nc_evidence"]["load_result"]["inserted"] == 80
        assert parsed["nc_evidence"]["acquisition_timestamp"] == "2026-03-15T10:00:00Z"
        assert parsed["nc_evidence"]["committee_doc_validation"]["status"] == "validation_only"
        assert parsed["quality_report"]["status"] == "pass"
        assert parsed["co_evidence"] is None
        assert parsed["ga_evidence"] is None
        # Anomalies empty when all checks pass and committee doc provided
        assert parsed["anomalies"] == []

    @patch("domains.campaign_finance.quality.state_closeout._discover_and_run")
    @patch("domains.campaign_finance.quality.state_closeout.fetch_data_source_snapshot")
    @patch("domains.campaign_finance.quality.state_closeout.sync_data_source_metadata")
    @patch("domains.campaign_finance.quality.state_closeout.load_nc_transactions")
    @patch("domains.campaign_finance.quality.state_closeout._compute_file_identity")
    @patch("domains.campaign_finance.quality.state_closeout._validate_nc_committee_doc")
    @patch("domains.campaign_finance.quality.state_closeout.ensure_nc_data_source")
    def test_nc_committee_doc_never_calls_sync_or_ensure(
        self,
        mock_ensure: MagicMock,
        mock_validate_doc: MagicMock,
        mock_file_id: MagicMock,
        mock_load: MagicMock,
        mock_sync: MagicMock,
        mock_snapshot: MagicMock,
        mock_quality: MagicMock,
    ) -> None:
        """Committee-doc validation must not create or sync a data_source row."""
        mock_ensure.return_value = _FIXED_DS_ID
        mock_file_id.return_value = ("ncsha256hex", 12345)
        mock_load.return_value = MagicMock(
            inserted=80, skipped=10, quarantined=5, superseded=0, errors=0, elapsed_seconds=1.0
        )
        mock_validate_doc.return_value = NcCommitteeDocValidation(
            source_file="/data/nc_committees.csv",
            file_sha256="docshaHEX",
            total_rows=42,
            parse_skipped=3,
        )
        mock_sync.return_value = 80
        mock_snapshot.return_value = DataSourceSnapshot(
            record_count=80, last_pull_status="success", last_pull_at=_FIXED_NOW
        )
        mock_quality.return_value = _stub_quality_report("state/NC")

        config = RunConfig(
            jurisdiction="state/NC",
            data_type="transactions",
            source_file=Path("/data/nc.csv"),
            nc_acquisition_timestamp="2026-03-15T10:00:00Z",
            nc_committee_doc_path=Path("/data/nc_committees.csv"),
        )
        run_state_closeout(MagicMock(), config)

        # ensure_nc_data_source called exactly once (for transactions only)
        mock_ensure.assert_called_once()
        # sync_data_source_metadata called exactly once (for transactions only)
        mock_sync.assert_called_once()
        # _validate_nc_committee_doc called but it's read-only — no extra ensure/sync
        mock_validate_doc.assert_called_once_with(Path("/data/nc_committees.csv"))

    @patch("domains.campaign_finance.quality.state_closeout._discover_and_run")
    @patch("domains.campaign_finance.quality.state_closeout.fetch_data_source_snapshot")
    @patch("domains.campaign_finance.quality.state_closeout.sync_data_source_metadata")
    @patch("domains.campaign_finance.quality.state_closeout.load_nc_transactions")
    @patch("domains.campaign_finance.quality.state_closeout._compute_file_identity")
    @patch("domains.campaign_finance.quality.state_closeout.ensure_nc_data_source")
    def test_nc_quality_report_scoped_to_transaction_jurisdiction(
        self,
        mock_ensure: MagicMock,
        mock_file_id: MagicMock,
        mock_load: MagicMock,
        mock_sync: MagicMock,
        mock_snapshot: MagicMock,
        mock_quality: MagicMock,
    ) -> None:
        """quality_report must be scoped to state/NC, not a committee-doc jurisdiction."""
        mock_ensure.return_value = _FIXED_DS_ID
        mock_file_id.return_value = ("ncsha256hex", 12345)
        mock_load.return_value = MagicMock(
            inserted=80, skipped=10, quarantined=5, superseded=0, errors=0, elapsed_seconds=1.0
        )
        mock_snapshot.return_value = DataSourceSnapshot(
            record_count=80, last_pull_status="success", last_pull_at=_FIXED_NOW
        )
        mock_quality.return_value = _stub_quality_report("state/NC")

        config = RunConfig(
            jurisdiction="state/NC",
            data_type="transactions",
            source_file=Path("/data/nc.csv"),
            nc_acquisition_timestamp="2026-03-15T10:00:00Z",
        )
        run_state_closeout(MagicMock(), config)
        # _discover_and_run called with jurisdiction="state/NC"
        mock_quality.assert_called_once()
        args, _ = mock_quality.call_args
        assert args[1] == "state/NC"

    @patch("domains.campaign_finance.quality.state_closeout._discover_and_run")
    @patch("domains.campaign_finance.quality.state_closeout.fetch_data_source_snapshot")
    @patch("domains.campaign_finance.quality.state_closeout.sync_data_source_metadata")
    @patch("domains.campaign_finance.quality.state_closeout.load_nc_transactions")
    @patch("domains.campaign_finance.quality.state_closeout._compute_file_identity")
    @patch("domains.campaign_finance.quality.state_closeout.ensure_nc_data_source")
    def test_nc_gap_marker_in_json_anomalies(
        self,
        mock_ensure: MagicMock,
        mock_file_id: MagicMock,
        mock_load: MagicMock,
        mock_sync: MagicMock,
        mock_snapshot: MagicMock,
        mock_quality: MagicMock,
    ) -> None:
        """Gap marker must appear in serialized anomalies array."""
        mock_ensure.return_value = _FIXED_DS_ID
        mock_file_id.return_value = ("ncsha256hex", 12345)
        mock_load.return_value = MagicMock(
            inserted=80, skipped=10, quarantined=5, superseded=0, errors=0, elapsed_seconds=1.0
        )
        mock_sync.return_value = 80
        mock_snapshot.return_value = DataSourceSnapshot(
            record_count=80, last_pull_status="success", last_pull_at=_FIXED_NOW
        )
        mock_quality.return_value = _stub_quality_report("state/NC")

        config = RunConfig(
            jurisdiction="state/NC",
            data_type="transactions",
            source_file=Path("/data/nc.csv"),
            nc_acquisition_timestamp="2026-03-15T10:00:00Z",
            # no committee doc
        )
        evidence = run_state_closeout(MagicMock(), config)
        parsed = json.loads(evidence.to_json())
        anomalies = parsed["anomalies"]
        assert len(anomalies) == 1
        assert anomalies[0]["name"] == "nc_committee_doc_not_provided"
        assert anomalies[0]["details"]["category"] == "gap-marker"
