"""Unit tests for campaign-finance Committee model."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from domains.campaign_finance.tests.model_payload_builders import (
    build_committee_payload,
    build_uuid_string,
)
from domains.campaign_finance.types import Committee, CommitteeType


def test_committee_requires_fec_committee_id_and_name():
    with pytest.raises(ValidationError):
        Committee.model_validate({"name": "Missing FEC ID"})
    with pytest.raises(ValidationError):
        Committee.model_validate({"fec_committee_id": "C12345678"})


def test_committee_defaults_shared_identity_fields():
    committee = Committee.model_validate(build_committee_payload())
    assert isinstance(committee.id, UUID)
    assert isinstance(committee.created_at, datetime)
    assert isinstance(committee.updated_at, datetime)
    assert committee.created_at.tzinfo == timezone.utc
    assert committee.updated_at.tzinfo == timezone.utc


def test_committee_parses_uuid_foreign_keys():
    committee = Committee.model_validate(
        build_committee_payload(
            organization_id=build_uuid_string(),
            source_record_id=build_uuid_string(),
        )
    )
    assert isinstance(committee.organization_id, UUID)
    assert isinstance(committee.source_record_id, UUID)


def test_committee_enforces_fec_id_pattern():
    with pytest.raises(ValidationError):
        Committee.model_validate(build_committee_payload(fec_committee_id="H12345678"))
    with pytest.raises(ValidationError):
        Committee.model_validate(build_committee_payload(fec_committee_id="C1234"))


def test_committee_enforces_two_character_state():
    with pytest.raises(ValidationError):
        Committee.model_validate(build_committee_payload(state="NCA"))


def test_committee_uses_committee_type_enum():
    committee = Committee.model_validate(build_committee_payload(committee_type="P"))
    assert committee.committee_type is CommitteeType.PRESIDENTIAL_CAMPAIGN
    with pytest.raises(ValidationError):
        Committee.model_validate(build_committee_payload(committee_type="K"))


def test_committee_allows_nullable_stage2_columns():
    committee = Committee.model_validate(
        build_committee_payload(
            committee_designation=None,
            party=None,
            city=None,
            zip_code=None,
            treasurer_name=None,
        )
    )
    assert committee.committee_designation is None
    assert committee.party is None
    assert committee.city is None
    assert committee.zip_code is None
    assert committee.treasurer_name is None


def test_committee_round_trip_dump_validate_and_schema():
    committee = Committee.model_validate(build_committee_payload())
    dumped = committee.model_dump(mode="json")
    restored = Committee.model_validate(dumped)
    schema = Committee.model_json_schema()

    assert restored == committee
    assert "fec_committee_id" in schema["properties"]
    assert "name" in schema["required"]
