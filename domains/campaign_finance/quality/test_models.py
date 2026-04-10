"""Unit tests for quality result models."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from domains.campaign_finance.quality.models import (
    CheckResult,
    JurisdictionSummary,
    QualityReport,
)


class TestCheckResult:
    def test_minimal_construction(self) -> None:
        result = CheckResult(name="test_check", status="pass")
        assert result.name == "test_check"
        assert result.status == "pass"
        assert result.message == ""
        assert result.metric_value is None
        assert result.details == {}

    def test_full_construction(self) -> None:
        result = CheckResult(
            name="null_rate",
            status="fail",
            message="source_url null rate 0.15 exceeds 0.05",
            metric_name="null_rate",
            metric_value=0.15,
            threshold=0.05,
            details={"column": "source_url", "sample_size": 100},
        )
        assert result.metric_value == 0.15
        assert result.threshold == 0.05
        assert result.details["column"] == "source_url"

    def test_is_passing_for_pass_and_warn(self) -> None:
        assert CheckResult(name="c", status="pass").is_passing()
        assert CheckResult(name="c", status="warn").is_passing()
        assert not CheckResult(name="c", status="fail").is_passing()
        assert not CheckResult(name="c", status="error").is_passing()

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CheckResult(name="c", status="unknown")  # type: ignore[arg-type]

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CheckResult(name="c", status="pass", bogus=True)  # type: ignore[call-arg]


class TestJurisdictionSummary:
    def test_empty_checks_gives_pass_status(self) -> None:
        summary = JurisdictionSummary(jurisdiction="federal/fec")
        assert summary.status == "pass"
        assert summary.pass_count == 0
        assert summary.fail_count == 0

    def test_status_escalation(self) -> None:
        summary = JurisdictionSummary(
            jurisdiction="state/CO",
            check_results=[
                CheckResult(name="a", status="pass"),
                CheckResult(name="b", status="warn"),
            ],
        )
        assert summary.status == "warn"

        summary_fail = JurisdictionSummary(
            jurisdiction="state/CO",
            check_results=[
                CheckResult(name="a", status="pass"),
                CheckResult(name="b", status="fail"),
            ],
        )
        assert summary_fail.status == "fail"

        summary_error = JurisdictionSummary(
            jurisdiction="state/GA",
            check_results=[
                CheckResult(name="a", status="fail"),
                CheckResult(name="b", status="error"),
            ],
        )
        assert summary_error.status == "error"

    def test_counts(self) -> None:
        summary = JurisdictionSummary(
            jurisdiction="state/NC",
            check_results=[
                CheckResult(name="a", status="pass"),
                CheckResult(name="b", status="pass"),
                CheckResult(name="c", status="fail"),
                CheckResult(name="d", status="warn"),
                CheckResult(name="e", status="error"),
            ],
        )
        assert summary.pass_count == 2
        assert summary.fail_count == 1
        assert summary.warn_count == 1
        assert summary.error_count == 1

    def test_baseline_urls_and_source_ids(self) -> None:
        summary = JurisdictionSummary(
            jurisdiction="federal/fec",
            data_source_ids=["abc-123"],
            baseline_urls=["https://fec.gov/data"],
            record_count=42,
        )
        assert summary.data_source_ids == ["abc-123"]
        assert summary.baseline_urls == ["https://fec.gov/data"]
        assert summary.record_count == 42


class TestQualityReport:
    def test_empty_report(self) -> None:
        report = QualityReport()
        assert report.status == "pass"
        assert report.total_checks == 0
        assert report.total_pass == 0
        assert report.total_fail == 0
        assert report.generated_at is not None

    def test_status_aggregation(self) -> None:
        report = QualityReport(
            summaries=[
                JurisdictionSummary(
                    jurisdiction="federal/fec",
                    check_results=[CheckResult(name="a", status="pass")],
                ),
                JurisdictionSummary(
                    jurisdiction="state/CO",
                    check_results=[CheckResult(name="b", status="fail")],
                ),
            ],
        )
        assert report.status == "fail"
        assert report.total_checks == 2
        assert report.total_pass == 1
        assert report.total_fail == 1

    def test_to_json_is_valid_json(self) -> None:
        report = QualityReport(
            summaries=[
                JurisdictionSummary(
                    jurisdiction="federal/fec",
                    check_results=[
                        CheckResult(name="record_count", status="pass", metric_value=100.0),
                    ],
                ),
            ],
        )
        raw = report.to_json()
        parsed = json.loads(raw)
        assert parsed["status"] == "pass"
        assert parsed["total_checks"] == 1
        assert parsed["total_pass"] == 1
        assert parsed["total_fail"] == 0
        assert len(parsed["summaries"]) == 1
        assert parsed["summaries"][0]["jurisdiction"] == "federal/fec"
        assert parsed["summaries"][0]["status"] == "pass"
        assert parsed["summaries"][0]["pass_count"] == 1

    def test_to_json_includes_computed_fields(self) -> None:
        report = QualityReport(
            summaries=[
                JurisdictionSummary(
                    jurisdiction="state/CO",
                    check_results=[
                        CheckResult(name="a", status="pass"),
                        CheckResult(name="b", status="warn"),
                        CheckResult(name="c", status="fail"),
                    ],
                ),
            ],
        )
        parsed = json.loads(report.to_json())
        summary = parsed["summaries"][0]
        assert summary["pass_count"] == 1
        assert summary["warn_count"] == 1
        assert summary["fail_count"] == 1
        assert summary["error_count"] == 0
        assert parsed["total_checks"] == 3

    def test_filters_serialized(self) -> None:
        report = QualityReport(
            jurisdiction_filter="state/CO",
            check_filter="record_count",
        )
        parsed = json.loads(report.to_json())
        assert parsed["jurisdiction_filter"] == "state/CO"
        assert parsed["check_filter"] == "record_count"

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            QualityReport(unexpected="field")  # type: ignore[call-arg]
