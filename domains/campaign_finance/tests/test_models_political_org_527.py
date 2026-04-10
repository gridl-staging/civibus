"""Unit tests for IRS 527 PoliticalOrganization527 model (Form 8871 / record type 1)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from domains.campaign_finance.tests.model_payload_builders import (
    build_political_org_527_payload,
    build_uuid_string,
)
from domains.campaign_finance.types import PoliticalOrganization527


class TestPoliticalOrg527RequiredFields:
    def test_requires_form_type(self):
        payload = build_political_org_527_payload()
        del payload["form_type"]
        with pytest.raises(ValidationError):
            PoliticalOrganization527.model_validate(payload)

    def test_requires_form_id_number(self):
        payload = build_political_org_527_payload()
        del payload["form_id_number"]
        with pytest.raises(ValidationError):
            PoliticalOrganization527.model_validate(payload)

    def test_requires_ein(self):
        payload = build_political_org_527_payload()
        del payload["ein"]
        with pytest.raises(ValidationError):
            PoliticalOrganization527.model_validate(payload)

    def test_requires_name(self):
        payload = build_political_org_527_payload()
        del payload["name"]
        with pytest.raises(ValidationError):
            PoliticalOrganization527.model_validate(payload)


class TestPoliticalOrg527EinValidation:
    def test_accepts_ein_with_dash(self):
        org = PoliticalOrganization527.model_validate(build_political_org_527_payload(ein="12-3456789"))
        assert org.ein == "12-3456789"

    def test_accepts_ein_without_dash(self):
        org = PoliticalOrganization527.model_validate(build_political_org_527_payload(ein="123456789"))
        assert org.ein == "123456789"

    def test_rejects_short_ein(self):
        with pytest.raises(ValidationError):
            PoliticalOrganization527.model_validate(build_political_org_527_payload(ein="12-345"))

    def test_rejects_alpha_ein(self):
        with pytest.raises(ValidationError):
            PoliticalOrganization527.model_validate(build_political_org_527_payload(ein="AB-CDEFGHI"))


class TestPoliticalOrg527Defaults:
    def test_defaults_shared_identity_fields(self):
        org = PoliticalOrganization527.model_validate(build_political_org_527_payload())
        assert isinstance(org.id, UUID)
        assert isinstance(org.created_at, datetime)
        assert isinstance(org.updated_at, datetime)
        assert org.created_at.tzinfo == timezone.utc
        assert org.updated_at.tzinfo == timezone.utc


class TestPoliticalOrg527OptionalFields:
    def test_optional_address_fields(self):
        org = PoliticalOrganization527.model_validate(
            build_political_org_527_payload(
                mailing_address_2="Suite 100",
                mailing_address_zip_ext="1234",
                email_address="info@example.org",
                business_address_1="456 K St",
                business_address_city="Washington",
                business_address_state="DC",
                business_address_zip="20005",
            )
        )
        assert org.mailing_address_2 == "Suite 100"
        assert org.business_address_1 == "456 K St"

    def test_optional_custodian_and_contact(self):
        org = PoliticalOrganization527.model_validate(
            build_political_org_527_payload(
                custodian_name="John Keeper",
                custodian_address_1="789 Archive Rd",
                custodian_address_city="Arlington",
                custodian_address_state="VA",
                custodian_address_zip="22201",
                contact_person_name="Sarah Contact",
                contact_address_1="101 Outreach Ave",
                contact_address_city="Bethesda",
                contact_address_state="MD",
                contact_address_zip="20814",
            )
        )
        assert org.custodian_name == "John Keeper"
        assert org.contact_person_name == "Sarah Contact"

    def test_optional_purpose_and_dates(self):
        org = PoliticalOrganization527.model_validate(
            build_political_org_527_payload(
                purpose="Promote civic engagement",
                established_date=date(2020, 1, 15),
                material_change_date=date(2025, 6, 1),
            )
        )
        assert org.purpose == "Promote civic engagement"
        assert org.established_date == date(2020, 1, 15)

    def test_optional_report_indicators(self):
        org = PoliticalOrganization527.model_validate(
            build_political_org_527_payload(
                initial_report_indicator=True,
                amended_report_indicator=False,
                final_report_indicator=False,
            )
        )
        assert org.initial_report_indicator is True
        assert org.amended_report_indicator is False
        assert org.final_report_indicator is False

    def test_optional_exempt_indicators(self):
        org = PoliticalOrganization527.model_validate(
            build_political_org_527_payload(
                exempt_8872_indicator=True,
                exempt_state="DC",
                exempt_990_indicator=False,
            )
        )
        assert org.exempt_8872_indicator is True
        assert org.exempt_state == "DC"

    def test_optional_irs_metadata_fields(self):
        org = PoliticalOrganization527.model_validate(
            build_political_org_527_payload(
                insert_datetime="2025-06-01T12:34:56",
                related_entity_bypass="N",
                eain_bypass="N",
            )
        )
        assert org.insert_datetime == "2025-06-01T12:34:56"
        assert org.related_entity_bypass == "N"
        assert org.eain_bypass == "N"

    def test_nullable_fields_default_none(self):
        org = PoliticalOrganization527.model_validate(build_political_org_527_payload())
        assert org.mailing_address_2 is None
        assert org.custodian_name is None
        assert org.contact_person_name is None
        assert org.purpose is None
        assert org.established_date is None
        assert org.initial_report_indicator is None
        assert org.insert_datetime is None
        assert org.related_entity_bypass is None
        assert org.eain_bypass is None


class TestPoliticalOrg527ForeignKeys:
    def test_parses_source_record_id(self):
        org = PoliticalOrganization527.model_validate(
            build_political_org_527_payload(source_record_id=build_uuid_string())
        )
        assert isinstance(org.source_record_id, UUID)

    def test_source_record_id_defaults_none(self):
        org = PoliticalOrganization527.model_validate(build_political_org_527_payload())
        assert org.source_record_id is None


class TestPoliticalOrg527ExtraForbid:
    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            PoliticalOrganization527.model_validate(build_political_org_527_payload(unexpected_field="bad"))


class TestPoliticalOrg527RoundTrip:
    def test_dump_validate_round_trip(self):
        org = PoliticalOrganization527.model_validate(build_political_org_527_payload())
        dumped = org.model_dump(mode="json")
        restored = PoliticalOrganization527.model_validate(dumped)
        assert restored == org

    def test_schema_includes_required_fields(self):
        schema = PoliticalOrganization527.model_json_schema()
        assert "form_type" in schema["properties"]
        assert "form_id_number" in schema["properties"]
        assert "ein" in schema["properties"]
        assert "form_type" in schema["required"]
        assert "name" in schema["required"]
