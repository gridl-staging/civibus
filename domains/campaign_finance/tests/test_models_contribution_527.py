"""Unit tests for IRS 527 Contribution527 model (Schedule A / record type A)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from domains.campaign_finance.tests.model_payload_builders import (
    build_contribution_527_payload,
    build_uuid_string,
)
from domains.campaign_finance.types import Contribution527


class TestContribution527RequiredFields:
    def test_requires_form_id_number(self):
        payload = build_contribution_527_payload()
        del payload["form_id_number"]
        with pytest.raises(ValidationError):
            Contribution527.model_validate(payload)

    def test_requires_sched_a_id(self):
        payload = build_contribution_527_payload()
        del payload["sched_a_id"]
        with pytest.raises(ValidationError):
            Contribution527.model_validate(payload)

    def test_requires_amount(self):
        payload = build_contribution_527_payload()
        del payload["amount"]
        with pytest.raises(ValidationError):
            Contribution527.model_validate(payload)

    def test_contribution_date_defaults_none_when_omitted(self):
        payload = build_contribution_527_payload()
        del payload["contribution_date"]
        c = Contribution527.model_validate(payload)
        assert c.contribution_date is None

    def test_requires_contributor_name(self):
        payload = build_contribution_527_payload()
        del payload["contributor_name"]
        with pytest.raises(ValidationError):
            Contribution527.model_validate(payload)

    def test_requires_aggregate_ytd(self):
        payload = build_contribution_527_payload()
        del payload["aggregate_ytd"]
        with pytest.raises(ValidationError):
            Contribution527.model_validate(payload)

    def test_requires_ein(self):
        payload = build_contribution_527_payload()
        del payload["ein"]
        with pytest.raises(ValidationError):
            Contribution527.model_validate(payload)


class TestContribution527Defaults:
    def test_defaults_shared_identity_fields(self):
        c = Contribution527.model_validate(build_contribution_527_payload())
        assert isinstance(c.id, UUID)
        assert isinstance(c.created_at, datetime)
        assert isinstance(c.updated_at, datetime)
        assert c.created_at.tzinfo == timezone.utc
        assert c.updated_at.tzinfo == timezone.utc


class TestContribution527AmountFields:
    def test_parses_decimal_amount(self):
        c = Contribution527.model_validate(build_contribution_527_payload(amount=Decimal("1234.56")))
        assert c.amount == Decimal("1234.56")

    def test_parses_aggregate_ytd(self):
        c = Contribution527.model_validate(build_contribution_527_payload(aggregate_ytd=Decimal("99999.99")))
        assert c.aggregate_ytd == Decimal("99999.99")


class TestContribution527ContributorFields:
    def test_optional_contributor_address(self):
        c = Contribution527.model_validate(
            build_contribution_527_payload(
                contributor_address_1="100 Donor Ln",
                contributor_address_2="Apt 4",
                contributor_address_city="Portland",
                contributor_address_state="OR",
                contributor_address_zip="97201",
                contributor_address_zip_ext="5678",
            )
        )
        assert c.contributor_address_1 == "100 Donor Ln"
        assert c.contributor_address_city == "Portland"

    def test_optional_employer_and_occupation(self):
        c = Contribution527.model_validate(
            build_contribution_527_payload(
                contributor_employer="Acme Corp",
                contributor_occupation="Engineer",
            )
        )
        assert c.contributor_employer == "Acme Corp"
        assert c.contributor_occupation == "Engineer"

    def test_nullable_contributor_fields_default_none(self):
        c = Contribution527.model_validate(build_contribution_527_payload())
        assert c.contributor_address_1 is None
        assert c.contributor_employer is None
        assert c.contributor_occupation is None


class TestContribution527OptionalFields:
    def test_optional_org_name(self):
        c = Contribution527.model_validate(build_contribution_527_payload(org_name="Americans for Things"))
        assert c.org_name == "Americans for Things"


class TestContribution527ForeignKeys:
    def test_parses_source_record_id(self):
        c = Contribution527.model_validate(build_contribution_527_payload(source_record_id=build_uuid_string()))
        assert isinstance(c.source_record_id, UUID)


class TestContribution527ExtraForbid:
    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            Contribution527.model_validate(build_contribution_527_payload(unexpected_field="bad"))


class TestContribution527RoundTrip:
    def test_dump_validate_round_trip(self):
        c = Contribution527.model_validate(build_contribution_527_payload())
        dumped = c.model_dump(mode="json")
        restored = Contribution527.model_validate(dumped)
        assert restored == c

    def test_schema_includes_required_fields(self):
        schema = Contribution527.model_json_schema()
        assert "sched_a_id" in schema["properties"]
        assert "amount" in schema["required"]
