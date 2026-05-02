"""Unit tests for IRS 527 Filing8872 model (Form 8872 / record type 2)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from domains.campaign_finance.tests.model_payload_builders import (
    build_filing_8872_payload,
    build_uuid_string,
)
from domains.campaign_finance.types import Filing8872


class TestFiling8872RequiredFields:
    def test_requires_form_type(self):
        payload = build_filing_8872_payload()
        del payload["form_type"]
        with pytest.raises(ValidationError):
            Filing8872.model_validate(payload)

    def test_requires_form_id_number(self):
        payload = build_filing_8872_payload()
        del payload["form_id_number"]
        with pytest.raises(ValidationError):
            Filing8872.model_validate(payload)

    def test_requires_ein(self):
        payload = build_filing_8872_payload()
        del payload["ein"]
        with pytest.raises(ValidationError):
            Filing8872.model_validate(payload)

    def test_period_begin_date_defaults_none_when_omitted(self):
        payload = build_filing_8872_payload()
        del payload["period_begin_date"]
        filing = Filing8872.model_validate(payload)
        assert filing.period_begin_date is None

    def test_period_end_date_defaults_none_when_omitted(self):
        payload = build_filing_8872_payload()
        del payload["period_end_date"]
        filing = Filing8872.model_validate(payload)
        assert filing.period_end_date is None


class TestFiling8872Defaults:
    def test_defaults_shared_identity_fields(self):
        filing = Filing8872.model_validate(build_filing_8872_payload())
        assert isinstance(filing.id, UUID)
        assert isinstance(filing.created_at, datetime)
        assert isinstance(filing.updated_at, datetime)
        assert filing.created_at.tzinfo == timezone.utc
        assert filing.updated_at.tzinfo == timezone.utc


class TestFiling8872ReportIndicators:
    def test_accepts_report_type_indicators(self):
        filing = Filing8872.model_validate(
            build_filing_8872_payload(
                initial_report_indicator=True,
                amended_report_indicator=False,
                final_report_indicator=False,
            )
        )
        assert filing.initial_report_indicator is True
        assert filing.amended_report_indicator is False
        assert filing.final_report_indicator is False

    def test_report_indicators_default_none(self):
        filing = Filing8872.model_validate(build_filing_8872_payload())
        assert filing.initial_report_indicator is None
        assert filing.amended_report_indicator is None
        assert filing.final_report_indicator is None


class TestFiling8872OptionalFields:
    def test_optional_schedule_indicators(self):
        filing = Filing8872.model_validate(
            build_filing_8872_payload(
                quarterly_indicator=True,
                monthly_report_month="03",
                pre_election_type="primary",
                pre_or_post_election_date=date(2025, 5, 6),
                pre_or_post_election_state="NC",
            )
        )
        assert filing.quarterly_indicator is True
        assert filing.monthly_report_month == "03"
        assert filing.pre_election_type == "primary"

    def test_optional_schedule_totals(self):
        filing = Filing8872.model_validate(
            build_filing_8872_payload(
                sched_a_indicator=True,
                total_sched_a=Decimal("50000.00"),
                sched_b_indicator=True,
                total_sched_b=Decimal("45000.00"),
            )
        )
        assert filing.total_sched_a == Decimal("50000.00")
        assert filing.total_sched_b == Decimal("45000.00")

    def test_optional_insert_datetime(self):
        filing = Filing8872.model_validate(build_filing_8872_payload(insert_datetime="2025-06-30T23:59:59"))
        assert filing.insert_datetime == "2025-06-30T23:59:59"

    def test_optional_org_and_address_fields(self):
        filing = Filing8872.model_validate(
            build_filing_8872_payload(
                organization_name="Americans for Things",
                mailing_address_1="123 Main St",
                mailing_address_city="Washington",
                mailing_address_state="DC",
                mailing_address_zip="20001",
                email_address="info@example.org",
                change_of_address_indicator=True,
                org_formation_date=date(2020, 1, 1),
            )
        )
        assert filing.organization_name == "Americans for Things"
        assert filing.change_of_address_indicator is True

    def test_nullable_fields_default_none(self):
        filing = Filing8872.model_validate(build_filing_8872_payload())
        assert filing.organization_name is None
        assert filing.quarterly_indicator is None
        assert filing.total_sched_a is None
        assert filing.total_sched_b is None
        assert filing.insert_datetime is None


class TestFiling8872CoverageDateValidation:
    def test_rejects_begin_after_end(self):
        with pytest.raises(ValidationError, match="period_begin_date must be <= period_end_date"):
            Filing8872.model_validate(
                build_filing_8872_payload(
                    period_begin_date=date(2025, 7, 1),
                    period_end_date=date(2025, 1, 1),
                )
            )

    def test_accepts_same_begin_and_end(self):
        filing = Filing8872.model_validate(
            build_filing_8872_payload(
                period_begin_date=date(2025, 6, 15),
                period_end_date=date(2025, 6, 15),
            )
        )
        assert filing.period_begin_date == filing.period_end_date


class TestFiling8872ForeignKeys:
    def test_parses_source_record_id(self):
        filing = Filing8872.model_validate(build_filing_8872_payload(source_record_id=build_uuid_string()))
        assert isinstance(filing.source_record_id, UUID)


class TestFiling8872ExtraForbid:
    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            Filing8872.model_validate(build_filing_8872_payload(unexpected_field="bad"))


class TestFiling8872RoundTrip:
    def test_dump_validate_round_trip(self):
        filing = Filing8872.model_validate(build_filing_8872_payload())
        dumped = filing.model_dump(mode="json")
        restored = Filing8872.model_validate(dumped)
        assert restored == filing

    def test_schema_includes_required_fields(self):
        schema = Filing8872.model_json_schema()
        assert "form_type" in schema["properties"]
        assert "form_id_number" in schema["properties"]
        assert "ein" in schema["properties"]
        assert "form_type" in schema["required"]
        assert "period_begin_date" not in schema["required"]
