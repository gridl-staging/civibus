"""Unit tests for state closeout evidence models."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from domains.campaign_finance.quality.models import CheckResult, JurisdictionSummary, QualityReport
from domains.campaign_finance.quality.state_closeout_models import (
    CoCloseoutSection,
    GaCloseoutSection,
    LoadResultSnapshot,
    StateCloseoutEvidence,
)


def _make_quality_report(*, jurisdiction: str, status: str = "pass") -> QualityReport:
    """Build a minimal QualityReport for test fixtures."""
    return QualityReport(
        generated_at=datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc),
        jurisdiction_filter=jurisdiction,
        summaries=[
            JurisdictionSummary(
                jurisdiction=jurisdiction,
                check_results=[CheckResult(name="record_count_reconciliation", status=status)],
            )
        ],
    )


def _make_load_result_snapshot(**overrides: object) -> LoadResultSnapshot:
    defaults = {
        "inserted": 100,
        "skipped": 5,
        "errors": 0,
        "elapsed_seconds": 1.5,
    }
    defaults.update(overrides)
    return LoadResultSnapshot(**defaults)


# ---------------------------------------------------------------------------
# LoadResultSnapshot
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLoadResultSnapshot:
    def test_basic_fields(self) -> None:
        snap = LoadResultSnapshot(inserted=10, skipped=2, errors=1, elapsed_seconds=0.5)
        assert snap.inserted == 10
        assert snap.skipped == 2
        assert snap.errors == 1
        assert snap.elapsed_seconds == 0.5

    def test_optional_quarantined_superseded_default_none(self) -> None:
        snap = LoadResultSnapshot(inserted=10, skipped=0, errors=0, elapsed_seconds=0.1)
        assert snap.quarantined is None
        assert snap.superseded is None

    def test_co_fields_with_quarantined_superseded(self) -> None:
        snap = LoadResultSnapshot(
            inserted=100,
            skipped=5,
            quarantined=3,
            superseded=2,
            errors=0,
            elapsed_seconds=1.0,
        )
        assert snap.quarantined == 3
        assert snap.superseded == 2

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(Exception, match="extra"):
            LoadResultSnapshot(inserted=1, skipped=0, errors=0, elapsed_seconds=0.1, bonus=True)


# ---------------------------------------------------------------------------
# CoCloseoutSection
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCoCloseoutSection:
    def test_all_fields(self) -> None:
        section = CoCloseoutSection(
            source_file="/data/contributions.csv",
            raw_csv_row_count=1000,
            parser_skipped=3,
            load_result=_make_load_result_snapshot(quarantined=2, superseded=1),
            tracer_summary_notes="Totals match within 0.5%",
        )
        assert section.source_file == "/data/contributions.csv"
        assert section.raw_csv_row_count == 1000
        assert section.parser_skipped == 3
        assert section.load_result.quarantined == 2
        assert section.tracer_summary_notes == "Totals match within 0.5%"

    def test_tracer_summary_notes_defaults_none(self) -> None:
        section = CoCloseoutSection(
            source_file="/data/exp.csv",
            raw_csv_row_count=500,
            parser_skipped=0,
            load_result=_make_load_result_snapshot(),
        )
        assert section.tracer_summary_notes is None


# ---------------------------------------------------------------------------
# GaCloseoutSection
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGaCloseoutSection:
    def test_all_fields(self) -> None:
        section = GaCloseoutSection(
            source_file="/data/ga_contribs.csv",
            file_sha256="abc123",
            file_byte_size=54321,
            query_candidate="Jon Ossoff",
            query_date_start="2023-01-01",
            query_date_end="2024-12-31",
            query_data_type="contributions",
            load_result=_make_load_result_snapshot(),
            portal_summary_notes="Summary page shows 120 total",
        )
        assert section.query_candidate == "Jon Ossoff"
        assert section.file_sha256 == "abc123"
        assert section.portal_summary_notes == "Summary page shows 120 total"

    def test_portal_summary_notes_defaults_none(self) -> None:
        section = GaCloseoutSection(
            source_file="/data/ga_exp.csv",
            file_sha256="def456",
            file_byte_size=12345,
            query_candidate="Test Candidate",
            query_date_start="2024-01-01",
            query_date_end="2024-12-31",
            query_data_type="expenditures",
            load_result=_make_load_result_snapshot(),
        )
        assert section.portal_summary_notes is None


# ---------------------------------------------------------------------------
# StateCloseoutEvidence
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStateCloseoutEvidence:
    def test_to_json_is_deterministic(self) -> None:
        evidence = StateCloseoutEvidence(
            generated_at=datetime(2026, 3, 16, 13, 0, tzinfo=timezone.utc),
            jurisdiction="state/CO",
            data_type="contributions",
            data_source_id=str(uuid4()),
            data_source_snapshot={"record_count": 100, "last_pull_status": "success", "last_pull_at": None},
            quality_report=_make_quality_report(jurisdiction="state/CO"),
            co_evidence=CoCloseoutSection(
                source_file="/data/contribs.csv",
                raw_csv_row_count=100,
                parser_skipped=0,
                load_result=_make_load_result_snapshot(),
            ),
        )
        first = evidence.to_json()
        second = evidence.to_json()
        assert first == second

        payload = json.loads(first)
        assert payload["jurisdiction"] == "state/CO"
        assert payload["data_type"] == "contributions"
        assert payload["quality_report"]["status"] == "pass"
        assert "anomalies" in payload

    def test_embeds_quality_report_directly(self) -> None:
        qr = _make_quality_report(jurisdiction="state/GA", status="fail")
        evidence = StateCloseoutEvidence(
            jurisdiction="state/GA",
            data_type="contributions",
            data_source_id=str(uuid4()),
            data_source_snapshot={"record_count": 50, "last_pull_status": "success", "last_pull_at": None},
            quality_report=qr,
            ga_evidence=GaCloseoutSection(
                source_file="/data/ga.csv",
                file_sha256="abc",
                file_byte_size=1000,
                query_candidate="Test",
                query_date_start="2024-01-01",
                query_date_end="2024-12-31",
                query_data_type="contributions",
                load_result=_make_load_result_snapshot(),
            ),
        )
        payload = json.loads(evidence.to_json())
        check = payload["quality_report"]["summaries"][0]["check_results"][0]
        assert check["name"] == "record_count_reconciliation"
        assert check["status"] == "fail"

    def test_surfaced_anomalies_extracts_nonpass_and_known_limitations(self) -> None:
        qr = QualityReport(
            generated_at=datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc),
            summaries=[
                JurisdictionSummary(
                    jurisdiction="state/CO",
                    check_results=[
                        CheckResult(name="record_count_reconciliation", status="pass"),
                        CheckResult(name="completeness_source_url", status="warn", message="high null rate"),
                    ],
                )
            ],
        )
        limitation = {"name": "known_limitation_test", "status": "warn", "message": "test"}
        evidence = StateCloseoutEvidence(
            jurisdiction="state/CO",
            data_type="contributions",
            data_source_id=str(uuid4()),
            data_source_snapshot={"record_count": 10, "last_pull_status": "success", "last_pull_at": None},
            quality_report=qr,
            known_limitations=[limitation],
            co_evidence=CoCloseoutSection(
                source_file="/data/x.csv",
                raw_csv_row_count=10,
                parser_skipped=0,
                load_result=_make_load_result_snapshot(),
            ),
        )
        anomalies = evidence.surfaced_anomalies()
        assert len(anomalies) == 2
        assert anomalies[0]["name"] == "completeness_source_url"
        assert anomalies[0]["status"] == "warn"
        assert anomalies[1]["name"] == "known_limitation_test"

    def test_surfaced_anomalies_empty_when_all_pass(self) -> None:
        evidence = StateCloseoutEvidence(
            jurisdiction="state/CO",
            data_type="contributions",
            data_source_id=str(uuid4()),
            data_source_snapshot={"record_count": 10, "last_pull_status": "success", "last_pull_at": None},
            quality_report=_make_quality_report(jurisdiction="state/CO"),
            co_evidence=CoCloseoutSection(
                source_file="/data/x.csv",
                raw_csv_row_count=10,
                parser_skipped=0,
                load_result=_make_load_result_snapshot(),
            ),
        )
        assert evidence.surfaced_anomalies() == []

    def test_round_trips_null_optional_fields(self) -> None:
        evidence = StateCloseoutEvidence(
            jurisdiction="state/CO",
            data_type="contributions",
            data_source_id=str(uuid4()),
            data_source_snapshot={"record_count": 10, "last_pull_status": "success", "last_pull_at": None},
            quality_report=_make_quality_report(jurisdiction="state/CO"),
            co_evidence=CoCloseoutSection(
                source_file="/data/x.csv",
                raw_csv_row_count=10,
                parser_skipped=0,
                load_result=_make_load_result_snapshot(),
            ),
        )
        payload = json.loads(evidence.to_json())
        assert payload["ga_evidence"] is None
        assert payload["nc_evidence"] is None
        assert payload["co_evidence"]["tracer_summary_notes"] is None

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(Exception, match="extra"):
            StateCloseoutEvidence(
                jurisdiction="state/CO",
                data_type="contributions",
                data_source_id=str(uuid4()),
                data_source_snapshot={},
                quality_report=_make_quality_report(jurisdiction="state/CO"),
                bonus_field="nope",
            )
