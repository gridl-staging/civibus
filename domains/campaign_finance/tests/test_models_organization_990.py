"""Unit tests for IRS 990 Organization990 placeholder model."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from domains.campaign_finance.tests.model_payload_builders import (
    build_organization_990_payload,
    build_uuid_string,
)
from domains.campaign_finance.types import Organization990


class TestOrganization990RequiredFields:
    def test_requires_ein(self):
        payload = build_organization_990_payload()
        del payload["ein"]
        with pytest.raises(ValidationError):
            Organization990.model_validate(payload)

    def test_requires_name(self):
        payload = build_organization_990_payload()
        del payload["name"]
        with pytest.raises(ValidationError):
            Organization990.model_validate(payload)


class TestOrganization990Defaults:
    def test_defaults_shared_identity_fields(self):
        org = Organization990.model_validate(build_organization_990_payload())
        assert isinstance(org.id, UUID)
        assert isinstance(org.created_at, datetime)
        assert isinstance(org.updated_at, datetime)
        assert org.created_at.tzinfo == timezone.utc
        assert org.updated_at.tzinfo == timezone.utc

    def test_optional_fields_default_none(self):
        org = Organization990.model_validate(build_organization_990_payload())
        assert org.ntee_code is None
        assert org.total_revenue is None
        assert org.political_expenditures is None
        assert org.source_record_id is None


class TestOrganization990OptionalFields:
    def test_accepts_optional_placeholder_fields(self):
        org = Organization990.model_validate(
            build_organization_990_payload(
                ntee_code="W05",
                total_revenue=Decimal("1500000.00"),
                political_expenditures=Decimal("275000.50"),
            )
        )
        assert org.ntee_code == "W05"
        assert org.total_revenue == Decimal("1500000.00")
        assert org.political_expenditures == Decimal("275000.50")


class TestOrganization990ForeignKeys:
    def test_parses_source_record_id(self):
        org = Organization990.model_validate(build_organization_990_payload(source_record_id=build_uuid_string()))
        assert isinstance(org.source_record_id, UUID)


class TestOrganization990ExtraForbid:
    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            Organization990.model_validate(build_organization_990_payload(unexpected_field="bad"))


class TestOrganization990RoundTrip:
    def test_dump_validate_round_trip(self):
        org = Organization990.model_validate(build_organization_990_payload())
        dumped = org.model_dump(mode="json")
        restored = Organization990.model_validate(dumped)
        assert restored == org

    def test_schema_includes_required_fields(self):
        schema = Organization990.model_json_schema()
        assert "ein" in schema["properties"]
        assert "name" in schema["properties"]
        assert "ntee_code" in schema["properties"]
        assert "total_revenue" in schema["properties"]
        assert "political_expenditures" in schema["properties"]
        assert "ein" in schema["required"]
        assert "name" in schema["required"]
