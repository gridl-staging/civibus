"""Unit tests for the civic ReportingPeriod model."""

from __future__ import annotations

from datetime import date
from uuid import UUID

import pytest
from pydantic import ValidationError

from domains.civics.tests.model_payload_builders import build_reporting_period_payload, build_uuid_string
from domains.civics.types import ReportingPeriod


def test_reporting_period_requires_election_identity_and_dates() -> None:
    with pytest.raises(ValidationError):
        ReportingPeriod.model_validate(
            {
                "period_name": "pre_general_q3",
                "period_start": "2024-07-01",
                "period_end": "2024-09-30",
                "report_due_date": "2024-10-15",
            }
        )
    with pytest.raises(ValidationError):
        ReportingPeriod.model_validate(
            {
                "election_id": build_uuid_string(),
                "period_start": "2024-07-01",
                "period_end": "2024-09-30",
                "report_due_date": "2024-10-15",
            }
        )


def test_reporting_period_accepts_optional_fields() -> None:
    period = ReportingPeriod.model_validate(
        build_reporting_period_payload(
            disclosure_kind="periodic",
            source_record_id=build_uuid_string(),
        )
    )
    assert isinstance(period.election_id, UUID)
    assert period.period_start == date(2024, 7, 1)
    assert period.period_end == date(2024, 9, 30)
    assert period.report_due_date == date(2024, 10, 15)
    assert isinstance(period.source_record_id, UUID)


def test_reporting_period_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ReportingPeriod.model_validate(build_reporting_period_payload(unknown_field="value"))


def test_reporting_period_rejects_end_before_start() -> None:
    with pytest.raises(ValidationError, match="period_end must be on or after period_start"):
        ReportingPeriod.model_validate(
            build_reporting_period_payload(
                period_start="2024-09-30",
                period_end="2024-07-01",
            )
        )
