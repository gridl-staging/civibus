"""Unit tests for Schedule E closeout module."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from domains.campaign_finance.quality.models import CheckResult, QualityReport
from domains.campaign_finance.quality.schedule_e_closeout import (
    _NULL_RATE_FIELDS,
    _SOURCE_KEY_PREFIX,
    _run_schedule_e_checks,
    run_schedule_e_closeout,
)
from domains.campaign_finance.quality.schedule_e_closeout_models import (
    ScheduleECloseoutEvidence,
)


def _mock_conn() -> MagicMock:
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = (0, 100)
    mock_cursor.fetchall.return_value = []
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn


class TestRunScheduleEChecks:
    """Verify _run_schedule_e_checks produces the expected set of checks."""

    @patch("domains.campaign_finance.quality.schedule_e_closeout.check_raw_field_null_rate")
    @patch("domains.campaign_finance.quality.schedule_e_closeout.check_duplicate_records")
    @patch("domains.campaign_finance.quality.schedule_e_closeout.check_source_count")
    def test_produces_five_check_results(
        self,
        mock_count: MagicMock,
        mock_dup: MagicMock,
        mock_null: MagicMock,
    ) -> None:
        # Each mock returns a valid CheckResult
        mock_count.return_value = CheckResult(name="schedule_e_source_count", status="pass")
        mock_dup.return_value = CheckResult(name="schedule_e_duplicate_records", status="pass")
        mock_null.return_value = CheckResult(name="schedule_e_null_rate_sup_opp", status="pass")

        results = _run_schedule_e_checks(_mock_conn(), uuid4())

        # 1 count + 1 dup + 3 null rate fields = 5
        assert len(results) == 5
        mock_count.assert_called_once()
        mock_dup.assert_called_once()
        assert mock_null.call_count == 3

    @patch("domains.campaign_finance.quality.schedule_e_closeout.check_raw_field_null_rate")
    @patch("domains.campaign_finance.quality.schedule_e_closeout.check_duplicate_records")
    @patch("domains.campaign_finance.quality.schedule_e_closeout.check_source_count")
    def test_all_checks_use_schedule_e_prefix(
        self,
        mock_count: MagicMock,
        mock_dup: MagicMock,
        mock_null: MagicMock,
    ) -> None:
        mock_count.return_value = CheckResult(name="schedule_e_source_count", status="pass")
        mock_dup.return_value = CheckResult(name="schedule_e_duplicate_records", status="pass")
        mock_null.return_value = CheckResult(name="placeholder", status="pass")

        _run_schedule_e_checks(_mock_conn(), uuid4())

        # Source count passes prefix
        assert mock_count.call_args.kwargs["source_key_prefix"] == _SOURCE_KEY_PREFIX
        # Duplicate check passes prefix
        assert mock_dup.call_args.kwargs["source_key_prefix"] == _SOURCE_KEY_PREFIX
        # All null rate calls pass prefix
        for call in mock_null.call_args_list:
            assert call.kwargs["source_key_prefix"] == _SOURCE_KEY_PREFIX

    @patch("domains.campaign_finance.quality.schedule_e_closeout.check_raw_field_null_rate")
    @patch("domains.campaign_finance.quality.schedule_e_closeout.check_duplicate_records")
    @patch("domains.campaign_finance.quality.schedule_e_closeout.check_source_count")
    def test_null_rate_checks_use_csv_native_field_names(
        self,
        mock_count: MagicMock,
        mock_dup: MagicMock,
        mock_null: MagicMock,
    ) -> None:
        mock_count.return_value = CheckResult(name="schedule_e_source_count", status="pass")
        mock_dup.return_value = CheckResult(name="schedule_e_duplicate_records", status="pass")
        mock_null.return_value = CheckResult(name="placeholder", status="pass")

        _run_schedule_e_checks(_mock_conn(), uuid4())

        # Verify CSV-native field names, NOT domain column names
        field_names = [call.args[3] for call in mock_null.call_args_list]
        assert field_names == list(_NULL_RATE_FIELDS)
        assert "sup_opp" in field_names
        assert "exp_amo" in field_names
        assert "cand_id" in field_names

    @patch("domains.campaign_finance.quality.schedule_e_closeout.check_raw_field_null_rate")
    @patch("domains.campaign_finance.quality.schedule_e_closeout.check_duplicate_records")
    @patch("domains.campaign_finance.quality.schedule_e_closeout.check_source_count")
    def test_check_names_use_schedule_e_prefix(
        self,
        mock_count: MagicMock,
        mock_dup: MagicMock,
        mock_null: MagicMock,
    ) -> None:
        mock_count.return_value = CheckResult(name="schedule_e_source_count", status="pass")
        mock_dup.return_value = CheckResult(name="schedule_e_duplicate_records", status="pass")
        mock_null.return_value = CheckResult(name="placeholder", status="pass")

        _run_schedule_e_checks(_mock_conn(), uuid4())

        assert mock_count.call_args.kwargs["check_name"] == "schedule_e_source_count"
        assert mock_dup.call_args.kwargs["check_name"] == "schedule_e_duplicate_records"
        expected_null_names = [f"schedule_e_null_rate_{f}" for f in _NULL_RATE_FIELDS]
        actual_null_names = [call.kwargs["check_name"] for call in mock_null.call_args_list]
        assert actual_null_names == expected_null_names


class TestRunScheduleECloseout:
    """Verify run_schedule_e_closeout builds correct evidence structure."""

    @patch("domains.campaign_finance.quality.schedule_e_closeout.count_source_records", return_value=25)
    @patch("domains.campaign_finance.quality.schedule_e_closeout._run_schedule_e_checks")
    def test_evidence_contains_quality_report(
        self,
        mock_checks: MagicMock,
        mock_count: MagicMock,
    ) -> None:
        mock_checks.return_value = [
            CheckResult(name="schedule_e_source_count", status="pass", metric_value=25.0),
            CheckResult(name="schedule_e_duplicate_records", status="pass"),
            CheckResult(name="schedule_e_null_rate_sup_opp", status="pass"),
            CheckResult(name="schedule_e_null_rate_exp_amo", status="pass"),
            CheckResult(name="schedule_e_null_rate_cand_id", status="pass"),
        ]

        ds_id = uuid4()
        evidence = run_schedule_e_closeout(_mock_conn(), ds_id, cycle=2024)

        assert isinstance(evidence, ScheduleECloseoutEvidence)
        assert evidence.cycle == 2024
        assert evidence.data_source_id == str(ds_id)
        assert evidence.source_record_count == 25
        assert evidence.quality_report.status == "pass"
        assert len(evidence.quality_report.summaries) == 1
        assert evidence.quality_report.summaries[0].jurisdiction == "federal/fec"

    @patch("domains.campaign_finance.quality.schedule_e_closeout.count_source_records", return_value=10)
    @patch("domains.campaign_finance.quality.schedule_e_closeout._run_schedule_e_checks")
    def test_evidence_report_status_reflects_check_failures(
        self,
        mock_checks: MagicMock,
        mock_count: MagicMock,
    ) -> None:
        mock_checks.return_value = [
            CheckResult(name="schedule_e_source_count", status="pass"),
            CheckResult(name="schedule_e_duplicate_records", status="fail"),
        ]

        evidence = run_schedule_e_closeout(_mock_conn(), uuid4(), cycle=2024)

        assert evidence.quality_report.status == "fail"

    @patch("domains.campaign_finance.quality.schedule_e_closeout.count_source_records", return_value=5)
    @patch("domains.campaign_finance.quality.schedule_e_closeout._run_schedule_e_checks")
    def test_evidence_to_json_round_trips(
        self,
        mock_checks: MagicMock,
        mock_count: MagicMock,
    ) -> None:
        mock_checks.return_value = [
            CheckResult(name="schedule_e_source_count", status="pass"),
        ]

        evidence = run_schedule_e_closeout(_mock_conn(), uuid4(), cycle=2024)
        json_str = evidence.to_json()
        parsed = json.loads(json_str)

        assert parsed["cycle"] == 2024
        assert parsed["source_record_count"] == 5
        assert "quality_report" in parsed


class TestScheduleECloseoutEvidence:
    """Model-level tests for ScheduleECloseoutEvidence."""

    def test_surfaced_anomalies_returns_empty_when_all_pass(self) -> None:
        report = QualityReport(
            generated_at=datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc),
            summaries=[],
        )
        evidence = ScheduleECloseoutEvidence(
            generated_at=datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc),
            cycle=2024,
            data_source_id=str(uuid4()),
            source_record_count=10,
            quality_report=report,
        )
        assert evidence.surfaced_anomalies() == []

    def test_surfaced_anomalies_includes_non_pass_checks(self) -> None:
        from domains.campaign_finance.quality.models import JurisdictionSummary

        report = QualityReport(
            generated_at=datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc),
            summaries=[
                JurisdictionSummary(
                    jurisdiction="federal/fec",
                    check_results=[
                        CheckResult(name="schedule_e_source_count", status="pass"),
                        CheckResult(name="schedule_e_null_rate_cand_id", status="fail", message="high null rate"),
                    ],
                )
            ],
        )
        evidence = ScheduleECloseoutEvidence(
            cycle=2024,
            data_source_id=str(uuid4()),
            source_record_count=10,
            quality_report=report,
        )
        anomalies = evidence.surfaced_anomalies()
        assert len(anomalies) == 1
        assert anomalies[0]["name"] == "schedule_e_null_rate_cand_id"
        assert anomalies[0]["status"] == "fail"

    def test_rejects_extra_fields(self) -> None:
        # Tightened from `pytest.raises(Exception)` so the test pins the
        # actual contract (Pydantic strict-mode rejects extra fields)
        # rather than passing on any unrelated exception.
        with pytest.raises(ValidationError):
            ScheduleECloseoutEvidence(
                cycle=2024,
                data_source_id=str(uuid4()),
                source_record_count=10,
                quality_report=QualityReport(),
                extra_field="should_fail",
            )
