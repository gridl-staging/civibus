"""Unit tests for federal FEC closeout evidence models."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from domains.campaign_finance.quality.fec_closeout_models import (
    FecCloseoutEvidence,
    FecIngestMetadata,
    FecIngestStepSummary,
)
from domains.campaign_finance.quality.models import CheckResult, JurisdictionSummary, QualityReport


@pytest.mark.unit
def test_fec_closeout_evidence_to_json_is_deterministic() -> None:
    quality_report = QualityReport(
        generated_at=datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc),
        jurisdiction_filter="federal/fec",
        summaries=[
            JurisdictionSummary(
                jurisdiction="federal/fec",
                check_results=[
                    CheckResult(name="record_count_reconciliation", status="pass", details={"delta": 0}),
                    CheckResult(name="duplicate_records", status="warn", details={"duplicates": 2}),
                ],
            )
        ],
    )
    evidence = FecCloseoutEvidence(
        generated_at=datetime(2026, 3, 16, 13, 0, tzinfo=timezone.utc),
        cycle=2024,
        jurisdiction="federal/fec",
        data_source_id=str(uuid4()),
        transaction_limit=1000,
        baseline_urls={
            "cm": "https://www.fec.gov/files/bulk-downloads/2024/cm24.zip",
            "cn": "https://www.fec.gov/files/bulk-downloads/2024/cn24.zip",
            "ccl": "https://www.fec.gov/files/bulk-downloads/2024/ccl24.zip",
            "itcont": "https://www.fec.gov/files/bulk-downloads/2024/indiv24.zip",
            "itpas2": "https://www.fec.gov/files/bulk-downloads/2024/pas224.zip",
        },
        scoped_table_counts={
            "cf.committee": 5,
            "cf.candidate": 4,
            "cf.candidate_committee_link": 3,
            "core.source_record_active": 10,
        },
        ingest_steps=[
            FecIngestStepSummary(
                file_type="cm",
                source_path="/tmp/cm.txt",
                baseline_url="https://www.fec.gov/files/bulk-downloads/2024/cm24.zip",
                inserted=5,
                skipped=0,
                errors=0,
                elapsed_seconds=0.1,
            ),
            FecIngestStepSummary(
                file_type="itcont",
                source_path="/tmp/itcont.txt",
                baseline_url="https://www.fec.gov/files/bulk-downloads/2024/indiv24.zip",
                inserted=1,
                skipped=4,
                errors=1,
                elapsed_seconds=0.2,
            ),
        ],
        ingest_metadata=FecIngestMetadata(
            record_count=10,
            last_pull_status="partial",
            last_pull_at=datetime(2026, 3, 16, 13, 1, tzinfo=timezone.utc),
        ),
        quality_report=quality_report,
    )

    first_json = evidence.to_json()
    second_json = evidence.to_json()
    assert first_json == second_json

    payload = json.loads(first_json)
    assert payload["cycle"] == 2024
    assert payload["transaction_limit"] == 1000
    assert payload["scoped_table_counts"]["core.source_record_active"] == 10
    assert payload["quality_report"]["status"] == "warn"
    assert payload["anomalies"] == [
        {
            "jurisdiction": "federal/fec",
            "name": "duplicate_records",
            "status": "warn",
            "message": "",
            "details": {"duplicates": 2},
        }
    ]


@pytest.mark.unit
def test_fec_closeout_evidence_uses_quality_report_without_cloning_contract_fields() -> None:
    quality_report = QualityReport(
        generated_at=datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc),
        summaries=[
            JurisdictionSummary(
                jurisdiction="federal/fec",
                check_results=[
                    CheckResult(
                        name="null_rate_source_url",
                        status="fail",
                        message="source_url null rate exceeds threshold",
                        metric_name="null_rate",
                        metric_value=0.17,
                        threshold=0.05,
                        details={"column": "source_url"},
                    ),
                ],
            )
        ],
    )
    evidence = FecCloseoutEvidence(
        cycle=2024,
        jurisdiction="federal/fec",
        data_source_id=str(uuid4()),
        baseline_urls={},
        scoped_table_counts={},
        ingest_steps=[],
        ingest_metadata=FecIngestMetadata(record_count=0, last_pull_status="success", last_pull_at=None),
        quality_report=quality_report,
    )

    payload = json.loads(evidence.to_json())
    check_result = payload["quality_report"]["summaries"][0]["check_results"][0]
    assert check_result["name"] == "null_rate_source_url"
    assert check_result["metric_name"] == "null_rate"
    assert check_result["metric_value"] == 0.17
    assert check_result["threshold"] == 0.05
    assert check_result["details"] == {"column": "source_url"}


@pytest.mark.unit
def test_fec_ingest_step_summary_rejects_extra_fields() -> None:
    with pytest.raises(Exception, match="extra"):
        FecIngestStepSummary(
            file_type="cm",
            source_path="/tmp/cm.txt",
            baseline_url="https://example.com/cm24.zip",
            inserted=5,
            skipped=0,
            errors=0,
            elapsed_seconds=0.1,
            unexpected_field="boom",
        )


@pytest.mark.unit
def test_fec_ingest_metadata_allows_null_last_pull_at() -> None:
    meta = FecIngestMetadata(record_count=42, last_pull_status="success", last_pull_at=None)
    assert meta.last_pull_at is None
    assert meta.record_count == 42


@pytest.mark.unit
def test_surfaced_anomalies_returns_empty_when_all_checks_pass() -> None:
    quality_report = QualityReport(
        generated_at=datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc),
        summaries=[
            JurisdictionSummary(
                jurisdiction="federal/fec",
                check_results=[
                    CheckResult(name="record_count_reconciliation", status="pass"),
                    CheckResult(name="duplicate_records", status="pass"),
                ],
            )
        ],
    )
    evidence = FecCloseoutEvidence(
        cycle=2024,
        jurisdiction="federal/fec",
        data_source_id=str(uuid4()),
        baseline_urls={},
        scoped_table_counts={},
        ingest_steps=[],
        ingest_metadata=FecIngestMetadata(record_count=10, last_pull_status="success", last_pull_at=None),
        quality_report=quality_report,
    )
    assert evidence.surfaced_anomalies() == []


@pytest.mark.unit
def test_to_json_round_trips_null_optional_fields() -> None:
    quality_report = QualityReport(
        generated_at=datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc),
        summaries=[
            JurisdictionSummary(
                jurisdiction="federal/fec",
                check_results=[CheckResult(name="x", status="pass")],
            )
        ],
    )
    evidence = FecCloseoutEvidence(
        cycle=2024,
        jurisdiction="federal/fec",
        data_source_id=str(uuid4()),
        transaction_limit=None,
        baseline_urls={},
        scoped_table_counts={},
        ingest_steps=[],
        ingest_metadata=FecIngestMetadata(record_count=0, last_pull_status="success", last_pull_at=None),
        quality_report=quality_report,
    )
    payload = json.loads(evidence.to_json())
    assert payload["transaction_limit"] is None
    assert payload["ingest_metadata"]["last_pull_at"] is None
