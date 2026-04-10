"""Unit tests for state closeout orchestration runners."""

from __future__ import annotations

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
    _run_co_load,
    _validate_nc_committee_doc,
    run_state_closeout,
    write_evidence_artifact,
)
from domains.campaign_finance.quality.state_closeout_models import (
    NcCommitteeDocValidation,
    StateCloseoutEvidence,
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
# CO closeout orchestration
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCoCloseout:
    @patch("domains.campaign_finance.quality.state_closeout._discover_and_run")
    @patch("domains.campaign_finance.quality.state_closeout.fetch_data_source_snapshot")
    @patch("domains.campaign_finance.quality.state_closeout.sync_data_source_metadata")
    @patch("domains.campaign_finance.quality.state_closeout._run_co_load")
    @patch("domains.campaign_finance.quality.state_closeout._count_csv_rows")
    @patch("domains.campaign_finance.quality.state_closeout.ensure_co_data_source")
    def test_co_contributions_produces_evidence(
        self,
        mock_ensure: MagicMock,
        mock_csv_rows: MagicMock,
        mock_load: MagicMock,
        mock_sync: MagicMock,
        mock_snapshot: MagicMock,
        mock_quality: MagicMock,
    ) -> None:
        mock_ensure.return_value = _FIXED_DS_ID
        mock_csv_rows.return_value = 500
        co_result = MagicMock(
            inserted=490,
            skipped=5,
            quarantined=3,
            superseded=2,
            errors=0,
            elapsed_seconds=1.5,
        )
        mock_load.return_value = MagicMock(result=co_result, parser_skipped=0)
        mock_sync.return_value = 490
        mock_snapshot.return_value = DataSourceSnapshot(
            record_count=490,
            last_pull_status="success",
            last_pull_at=_FIXED_NOW,
        )
        mock_quality.return_value = _stub_quality_report("state/CO")

        config = RunConfig(
            jurisdiction="state/CO",
            data_type="contributions",
            source_file=Path("/data/contributions.csv"),
        )
        conn = MagicMock()
        evidence = run_state_closeout(conn, config)

        assert evidence.jurisdiction == "state/CO"
        assert evidence.data_type == "contributions"
        assert evidence.co_evidence is not None
        assert evidence.co_evidence.source_file == "/data/contributions.csv"
        assert evidence.co_evidence.raw_csv_row_count == 500
        assert evidence.co_evidence.load_result.inserted == 490
        assert evidence.co_evidence.load_result.quarantined == 3
        assert evidence.ga_evidence is None
        assert evidence.quality_report.status == "pass"

    @patch("domains.campaign_finance.quality.state_closeout.load_co_contributions")
    @patch("domains.campaign_finance.jurisdictions.states.CO.scraper.parse.parse_contributions")
    def test_run_co_load_iterates_parser_for_skipped_count(
        self,
        mock_parse: MagicMock,
        mock_load: MagicMock,
    ) -> None:
        """Regression: _run_co_load must iterate the parser to capture .skipped."""

        class _TrackingParser:
            def __init__(self) -> None:
                self.skipped = 0

            def __iter__(self):
                self.skipped = 7
                yield {"row": "data"}

        mock_parse.return_value = _TrackingParser()
        mock_load.return_value = MagicMock(
            inserted=1, skipped=0, quarantined=0, superseded=0, errors=0, elapsed_seconds=0.1
        )
        config = RunConfig(
            jurisdiction="state/CO",
            data_type="contributions",
            source_file=Path("/data/c.csv"),
        )
        output = _run_co_load(MagicMock(), config, _FIXED_DS_ID)
        assert output.parser_skipped == 7

    @patch("domains.campaign_finance.quality.state_closeout._discover_and_run")
    @patch("domains.campaign_finance.quality.state_closeout.fetch_data_source_snapshot")
    @patch("domains.campaign_finance.quality.state_closeout.sync_data_source_metadata")
    @patch("domains.campaign_finance.quality.state_closeout._run_co_load")
    @patch("domains.campaign_finance.quality.state_closeout._count_csv_rows")
    @patch("domains.campaign_finance.quality.state_closeout.ensure_co_data_source")
    def test_co_uses_persisted_metadata_as_source_of_truth(
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
        co_result = MagicMock(
            inserted=95,
            skipped=5,
            quarantined=0,
            superseded=0,
            errors=0,
            elapsed_seconds=0.5,
        )
        mock_load.return_value = MagicMock(result=co_result, parser_skipped=0)
        mock_sync.return_value = 95
        mock_snapshot.return_value = DataSourceSnapshot(
            record_count=95,
            last_pull_status="success",
            last_pull_at=_FIXED_NOW,
        )
        mock_quality.return_value = _stub_quality_report("state/CO")

        config = RunConfig(
            jurisdiction="state/CO",
            data_type="contributions",
            source_file=Path("/data/c.csv"),
        )
        evidence = run_state_closeout(MagicMock(), config)
        assert evidence.data_source_snapshot["record_count"] == 95
        assert evidence.data_source_snapshot["last_pull_status"] == "success"

    @patch("domains.campaign_finance.quality.state_closeout._discover_and_run")
    @patch("domains.campaign_finance.quality.state_closeout.fetch_data_source_snapshot")
    @patch("domains.campaign_finance.quality.state_closeout.sync_data_source_metadata")
    @patch("domains.campaign_finance.quality.state_closeout._run_co_load")
    @patch("domains.campaign_finance.quality.state_closeout._count_csv_rows")
    @patch("domains.campaign_finance.quality.state_closeout.ensure_co_data_source")
    def test_co_parser_skipped_captured(
        self,
        mock_ensure: MagicMock,
        mock_csv_rows: MagicMock,
        mock_load: MagicMock,
        mock_sync: MagicMock,
        mock_snapshot: MagicMock,
        mock_quality: MagicMock,
    ) -> None:
        mock_ensure.return_value = _FIXED_DS_ID
        mock_csv_rows.return_value = 200
        co_result = MagicMock(
            inserted=190,
            skipped=0,
            quarantined=0,
            superseded=0,
            errors=0,
            elapsed_seconds=0.5,
        )
        mock_load.return_value = MagicMock(result=co_result, parser_skipped=10)
        mock_sync.return_value = 190
        mock_snapshot.return_value = DataSourceSnapshot(
            record_count=190,
            last_pull_status="success",
            last_pull_at=_FIXED_NOW,
        )
        mock_quality.return_value = _stub_quality_report("state/CO")

        config = RunConfig(
            jurisdiction="state/CO",
            data_type="contributions",
            source_file=Path("/data/c.csv"),
        )
        evidence = run_state_closeout(MagicMock(), config)
        assert evidence.co_evidence is not None
        assert evidence.co_evidence.parser_skipped == 10


# ---------------------------------------------------------------------------
# GA closeout orchestration
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGaCloseout:
    @patch("domains.campaign_finance.quality.state_closeout._discover_and_run")
    @patch("domains.campaign_finance.quality.state_closeout.fetch_data_source_snapshot")
    @patch("domains.campaign_finance.quality.state_closeout.sync_data_source_metadata")
    @patch("domains.campaign_finance.quality.state_closeout._run_ga_load")
    @patch("domains.campaign_finance.quality.state_closeout._compute_file_identity")
    @patch("domains.campaign_finance.quality.state_closeout.ensure_ga_data_source")
    def test_ga_contributions_produces_evidence(
        self,
        mock_ensure: MagicMock,
        mock_file_id: MagicMock,
        mock_load: MagicMock,
        mock_sync: MagicMock,
        mock_snapshot: MagicMock,
        mock_quality: MagicMock,
    ) -> None:
        mock_ensure.return_value = _FIXED_DS_ID
        mock_file_id.return_value = ("abc123sha256", 54321)
        mock_load.return_value = MagicMock(
            inserted=100,
            skipped=5,
            errors=0,
            elapsed_seconds=0.8,
        )
        mock_sync.return_value = 100
        mock_snapshot.return_value = DataSourceSnapshot(
            record_count=100,
            last_pull_status="success",
            last_pull_at=_FIXED_NOW,
        )
        mock_quality.return_value = _stub_quality_report("state/GA")

        config = RunConfig(
            jurisdiction="state/GA",
            data_type="contributions",
            source_file=Path("/data/ga_contribs.csv"),
            ga_candidate="Jon Ossoff",
            ga_date_start="2023-01-01",
            ga_date_end="2024-12-31",
        )
        evidence = run_state_closeout(MagicMock(), config)
        assert evidence.jurisdiction == "state/GA"
        assert evidence.ga_evidence is not None
        assert evidence.ga_evidence.query_candidate == "Jon Ossoff"
        assert evidence.ga_evidence.file_sha256 == "abc123sha256"
        assert evidence.ga_evidence.file_byte_size == 54321
        assert evidence.ga_evidence.load_result.inserted == 100
        assert evidence.co_evidence is None

    @patch("domains.campaign_finance.quality.state_closeout._discover_and_run")
    @patch("domains.campaign_finance.quality.state_closeout.fetch_data_source_snapshot")
    @patch("domains.campaign_finance.quality.state_closeout.sync_data_source_metadata")
    @patch("domains.campaign_finance.quality.state_closeout._run_ga_load")
    @patch("domains.campaign_finance.quality.state_closeout._compute_file_identity")
    @patch("domains.campaign_finance.quality.state_closeout.ensure_ga_data_source")
    def test_ga_query_params_preserved_in_evidence(
        self,
        mock_ensure: MagicMock,
        mock_file_id: MagicMock,
        mock_load: MagicMock,
        mock_sync: MagicMock,
        mock_snapshot: MagicMock,
        mock_quality: MagicMock,
    ) -> None:
        mock_ensure.return_value = _FIXED_DS_ID
        mock_file_id.return_value = ("sha256hex", 999)
        mock_load.return_value = MagicMock(
            inserted=50,
            skipped=0,
            errors=0,
            elapsed_seconds=0.5,
        )
        mock_sync.return_value = 50
        mock_snapshot.return_value = DataSourceSnapshot(
            record_count=50,
            last_pull_status="success",
            last_pull_at=_FIXED_NOW,
        )
        mock_quality.return_value = _stub_quality_report("state/GA")

        config = RunConfig(
            jurisdiction="state/GA",
            data_type="expenditures",
            source_file=Path("/data/ga_exp.csv"),
            ga_candidate="Raphael Warnock",
            ga_date_start="2024-01-01",
            ga_date_end="2024-12-31",
        )
        evidence = run_state_closeout(MagicMock(), config)
        ga = evidence.ga_evidence
        assert ga is not None
        assert ga.query_candidate == "Raphael Warnock"
        assert ga.query_date_start == "2024-01-01"
        assert ga.query_date_end == "2024-12-31"
        assert ga.query_data_type == "expenditures"


# ---------------------------------------------------------------------------
# NC closeout orchestration
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNcCloseout:
    @patch("domains.campaign_finance.quality.state_closeout._discover_and_run")
    @patch("domains.campaign_finance.quality.state_closeout.fetch_data_source_snapshot")
    @patch("domains.campaign_finance.quality.state_closeout.sync_data_source_metadata")
    @patch("domains.campaign_finance.quality.state_closeout.load_nc_transactions")
    @patch("domains.campaign_finance.quality.state_closeout._compute_file_identity")
    @patch("domains.campaign_finance.quality.state_closeout.ensure_nc_data_source")
    def test_nc_transactions_produces_evidence(
        self,
        mock_ensure: MagicMock,
        mock_file_id: MagicMock,
        mock_load: MagicMock,
        mock_sync: MagicMock,
        mock_snapshot: MagicMock,
        mock_quality: MagicMock,
    ) -> None:
        mock_ensure.return_value = _FIXED_DS_ID
        mock_file_id.return_value = ("ncsha256hex", 12345)
        mock_load.return_value = MagicMock(
            inserted=80,
            skipped=10,
            quarantined=5,
            superseded=0,
            errors=2,
            elapsed_seconds=1.2,
        )
        mock_sync.return_value = 80
        mock_snapshot.return_value = DataSourceSnapshot(
            record_count=80,
            last_pull_status="success",
            last_pull_at=_FIXED_NOW,
        )
        mock_quality.return_value = _stub_quality_report("state/NC")

        config = RunConfig(
            jurisdiction="state/NC",
            data_type="transactions",
            source_file=Path("/data/nc_transactions.csv"),
            nc_acquisition_timestamp="2026-03-15T10:00:00Z",
        )
        evidence = run_state_closeout(MagicMock(), config)
        assert evidence.jurisdiction == "state/NC"
        assert evidence.nc_evidence is not None
        assert evidence.nc_evidence.transaction_file_sha256 == "ncsha256hex"
        assert evidence.nc_evidence.transaction_file_byte_size == 12345
        assert evidence.nc_evidence.load_result.inserted == 80
        assert evidence.nc_evidence.load_result.quarantined == 5
        assert evidence.nc_evidence.acquisition_timestamp == "2026-03-15T10:00:00Z"
        assert evidence.co_evidence is None
        assert evidence.ga_evidence is None
        assert evidence.quality_report.status == "pass"

    @patch("domains.campaign_finance.quality.state_closeout._discover_and_run")
    @patch("domains.campaign_finance.quality.state_closeout.fetch_data_source_snapshot")
    @patch("domains.campaign_finance.quality.state_closeout.sync_data_source_metadata")
    @patch("domains.campaign_finance.quality.state_closeout.load_nc_transactions")
    @patch("domains.campaign_finance.quality.state_closeout._compute_file_identity")
    @patch("domains.campaign_finance.quality.state_closeout.ensure_nc_data_source")
    def test_nc_gap_marker_when_no_committee_doc(
        self,
        mock_ensure: MagicMock,
        mock_file_id: MagicMock,
        mock_load: MagicMock,
        mock_sync: MagicMock,
        mock_snapshot: MagicMock,
        mock_quality: MagicMock,
    ) -> None:
        mock_ensure.return_value = _FIXED_DS_ID
        mock_file_id.return_value = ("ncsha256hex", 12345)
        mock_load.return_value = MagicMock(
            inserted=80,
            skipped=10,
            quarantined=5,
            superseded=0,
            errors=0,
            elapsed_seconds=1.0,
        )
        mock_sync.return_value = 80
        mock_snapshot.return_value = DataSourceSnapshot(
            record_count=80,
            last_pull_status="success",
            last_pull_at=_FIXED_NOW,
        )
        mock_quality.return_value = _stub_quality_report("state/NC")

        config = RunConfig(
            jurisdiction="state/NC",
            data_type="transactions",
            source_file=Path("/data/nc.csv"),
            nc_acquisition_timestamp="2026-03-15T10:00:00Z",
            # nc_committee_doc_path intentionally None
        )
        evidence = run_state_closeout(MagicMock(), config)
        assert len(evidence.known_limitations) == 1
        gap = evidence.known_limitations[0]
        assert gap["name"] == "nc_committee_doc_not_provided"
        assert gap["status"] == "warn"
        assert evidence.nc_evidence is not None
        assert evidence.nc_evidence.committee_doc_validation is None

    @patch("domains.campaign_finance.quality.state_closeout._discover_and_run")
    @patch("domains.campaign_finance.quality.state_closeout.fetch_data_source_snapshot")
    @patch("domains.campaign_finance.quality.state_closeout.sync_data_source_metadata")
    @patch("domains.campaign_finance.quality.state_closeout.load_nc_transactions")
    @patch("domains.campaign_finance.quality.state_closeout._compute_file_identity")
    @patch("domains.campaign_finance.quality.state_closeout._validate_nc_committee_doc")
    @patch("domains.campaign_finance.quality.state_closeout.ensure_nc_data_source")
    def test_nc_committee_doc_validation_captured(
        self,
        mock_ensure: MagicMock,
        mock_validate_doc: MagicMock,
        mock_file_id: MagicMock,
        mock_load: MagicMock,
        mock_sync: MagicMock,
        mock_snapshot: MagicMock,
        mock_quality: MagicMock,
    ) -> None:
        mock_ensure.return_value = _FIXED_DS_ID
        mock_file_id.return_value = ("ncsha256hex", 12345)
        mock_load.return_value = MagicMock(
            inserted=80,
            skipped=10,
            quarantined=5,
            superseded=0,
            errors=0,
            elapsed_seconds=1.0,
        )
        mock_validate_doc.return_value = NcCommitteeDocValidation(
            source_file="/data/nc_committees.csv",
            file_sha256="docshaHEX",
            total_rows=42,
            parse_skipped=3,
        )
        mock_sync.return_value = 80
        mock_snapshot.return_value = DataSourceSnapshot(
            record_count=80,
            last_pull_status="success",
            last_pull_at=_FIXED_NOW,
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
        assert evidence.nc_evidence is not None
        doc = evidence.nc_evidence.committee_doc_validation
        assert doc is not None
        assert doc.source_file == "/data/nc_committees.csv"
        assert doc.file_sha256 == "docshaHEX"
        assert doc.total_rows == 42
        assert doc.parse_skipped == 3
        assert doc.status == "validation_only"
        # No gap marker when committee doc is provided
        assert len(evidence.known_limitations) == 0

    @patch("domains.campaign_finance.quality.state_closeout._compute_file_identity")
    @patch("domains.campaign_finance.quality.state_closeout.nc_parse_committee_docs")
    def test_validate_nc_committee_doc_captures_stats(
        self,
        mock_parse: MagicMock,
        mock_file_id: MagicMock,
    ) -> None:
        """_validate_nc_committee_doc iterates parser for row count and skipped."""

        class _TrackingParser:
            def __init__(self) -> None:
                self.skipped = 0

            def __iter__(self):
                self.skipped = 3
                yield {"row1": "data"}
                yield {"row2": "data"}

        mock_parse.return_value = _TrackingParser()
        mock_file_id.return_value = ("docshaHEX", 999)

        result = _validate_nc_committee_doc(Path("/data/committees.csv"))
        assert result.total_rows == 2
        assert result.parse_skipped == 3
        assert result.file_sha256 == "docshaHEX"
        assert result.source_file == "/data/committees.csv"
        assert result.status == "validation_only"


# ---------------------------------------------------------------------------
# write_evidence_artifact
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_write_evidence_artifact_creates_parent_and_terminates_with_newline(tmp_path: Path) -> None:
    evidence = MagicMock(spec=StateCloseoutEvidence)
    evidence.to_json.return_value = '{"test": true}'

    artifact_path = tmp_path / "sub" / "dir" / "closeout_evidence.json"
    write_evidence_artifact(evidence, artifact_path)

    assert artifact_path.exists()
    content = artifact_path.read_text(encoding="utf-8")
    assert content == '{"test": true}\n'
    assert content.endswith("\n")
