"""Unit tests for IRS 527 Expenditure527 model (Schedule B / record type B)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from domains.campaign_finance.tests.model_payload_builders import (
    build_expenditure_527_payload,
    build_uuid_string,
)
from domains.campaign_finance.types import Expenditure527


class TestExpenditure527RequiredFields:
    def test_requires_form_id_number(self):
        payload = build_expenditure_527_payload()
        del payload["form_id_number"]
        with pytest.raises(ValidationError):
            Expenditure527.model_validate(payload)

    def test_requires_sched_b_id(self):
        payload = build_expenditure_527_payload()
        del payload["sched_b_id"]
        with pytest.raises(ValidationError):
            Expenditure527.model_validate(payload)

    def test_requires_amount(self):
        payload = build_expenditure_527_payload()
        del payload["amount"]
        with pytest.raises(ValidationError):
            Expenditure527.model_validate(payload)

    def test_expenditure_date_defaults_none_when_omitted(self):
        payload = build_expenditure_527_payload()
        del payload["expenditure_date"]
        e = Expenditure527.model_validate(payload)
        assert e.expenditure_date is None

    def test_purpose_defaults_none_when_omitted(self):
        payload = build_expenditure_527_payload()
        del payload["purpose"]
        e = Expenditure527.model_validate(payload)
        assert e.purpose is None

    def test_requires_recipient_name(self):
        payload = build_expenditure_527_payload()
        del payload["recipient_name"]
        with pytest.raises(ValidationError):
            Expenditure527.model_validate(payload)

    def test_requires_ein(self):
        payload = build_expenditure_527_payload()
        del payload["ein"]
        with pytest.raises(ValidationError):
            Expenditure527.model_validate(payload)


class TestExpenditure527Defaults:
    def test_defaults_shared_identity_fields(self):
        e = Expenditure527.model_validate(build_expenditure_527_payload())
        assert isinstance(e.id, UUID)
        assert isinstance(e.created_at, datetime)
        assert isinstance(e.updated_at, datetime)
        assert e.created_at.tzinfo == timezone.utc
        assert e.updated_at.tzinfo == timezone.utc


class TestExpenditure527AmountField:
    def test_parses_decimal_amount(self):
        e = Expenditure527.model_validate(build_expenditure_527_payload(amount=Decimal("75000.50")))
        assert e.amount == Decimal("75000.50")


class TestExpenditure527RecipientFields:
    def test_optional_recipient_address(self):
        e = Expenditure527.model_validate(
            build_expenditure_527_payload(
                recipient_address_1="200 Media Blvd",
                recipient_address_2="Floor 3",
                recipient_address_city="New York",
                recipient_address_state="NY",
                recipient_address_zip="10001",
                recipient_address_zip_ext="0001",
            )
        )
        assert e.recipient_address_1 == "200 Media Blvd"
        assert e.recipient_address_city == "New York"

    def test_optional_recipient_employer_and_occupation(self):
        e = Expenditure527.model_validate(
            build_expenditure_527_payload(
                recipient_employer="Media Group LLC",
                recipient_occupation="Consulting",
            )
        )
        assert e.recipient_employer == "Media Group LLC"
        assert e.recipient_occupation == "Consulting"

    def test_nullable_recipient_fields_default_none(self):
        e = Expenditure527.model_validate(build_expenditure_527_payload())
        assert e.recipient_address_1 is None
        assert e.recipient_employer is None
        assert e.recipient_occupation is None


class TestExpenditure527OptionalFields:
    def test_optional_org_name(self):
        e = Expenditure527.model_validate(build_expenditure_527_payload(org_name="Americans for Things"))
        assert e.org_name == "Americans for Things"


class TestExpenditure527ForeignKeys:
    def test_parses_source_record_id(self):
        e = Expenditure527.model_validate(build_expenditure_527_payload(source_record_id=build_uuid_string()))
        assert isinstance(e.source_record_id, UUID)


class TestExpenditure527ExtraForbid:
    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            Expenditure527.model_validate(build_expenditure_527_payload(unexpected_field="bad"))


class TestExpenditure527RoundTrip:
    def test_dump_validate_round_trip(self):
        e = Expenditure527.model_validate(build_expenditure_527_payload())
        dumped = e.model_dump(mode="json")
        restored = Expenditure527.model_validate(dumped)
        assert restored == e

    def test_schema_includes_required_fields(self):
        schema = Expenditure527.model_json_schema()
        assert "sched_b_id" in schema["properties"]
        assert "sched_b_id" in schema["required"]
        assert "purpose" not in schema["required"]
