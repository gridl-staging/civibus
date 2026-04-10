"""Unit tests for campaign-finance Candidate model."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from domains.campaign_finance.tests.model_payload_builders import (
    build_candidate_payload,
    build_uuid_string,
)
from domains.campaign_finance.types import Candidate, OfficeType


def test_candidate_requires_fec_candidate_id_name_and_office():
    with pytest.raises(ValidationError):
        Candidate.model_validate({"name": "Missing ID", "office": "H"})
    with pytest.raises(ValidationError):
        Candidate.model_validate({"fec_candidate_id": "H1NC00001", "office": "H"})
    with pytest.raises(ValidationError):
        Candidate.model_validate({"fec_candidate_id": "H1NC00001", "name": "ALEX TAYLOR"})


def test_candidate_defaults_shared_identity_fields():
    candidate = Candidate.model_validate(build_candidate_payload())
    assert isinstance(candidate.id, UUID)
    assert isinstance(candidate.created_at, datetime)
    assert isinstance(candidate.updated_at, datetime)
    assert candidate.created_at.tzinfo == timezone.utc
    assert candidate.updated_at.tzinfo == timezone.utc


def test_candidate_enforces_fec_candidate_id_pattern():
    with pytest.raises(ValidationError):
        Candidate.model_validate(build_candidate_payload(fec_candidate_id="C1NC00001"))
    with pytest.raises(ValidationError):
        Candidate.model_validate(build_candidate_payload(fec_candidate_id="H12345"))


def test_candidate_validates_office_state_district_and_incumbent_challenge():
    candidate = Candidate.model_validate(build_candidate_payload())
    assert candidate.office is OfficeType.HOUSE

    with pytest.raises(ValidationError):
        Candidate.model_validate(build_candidate_payload(office="G"))
    with pytest.raises(ValidationError):
        Candidate.model_validate(build_candidate_payload(state="NCA"))
    with pytest.raises(ValidationError):
        Candidate.model_validate(build_candidate_payload(district="001"))
    with pytest.raises(ValidationError):
        Candidate.model_validate(build_candidate_payload(incumbent_challenge="N"))


def test_candidate_parses_uuid_foreign_keys():
    candidate = Candidate.model_validate(
        build_candidate_payload(
            person_id=build_uuid_string(),
            principal_committee_id=build_uuid_string(),
            source_record_id=build_uuid_string(),
        )
    )
    assert isinstance(candidate.person_id, UUID)
    assert isinstance(candidate.principal_committee_id, UUID)
    assert isinstance(candidate.source_record_id, UUID)


def test_candidate_requires_fec_id_office_prefix_match():
    with pytest.raises(ValidationError):
        Candidate.model_validate(build_candidate_payload(fec_candidate_id="S1NC00001", office="H"))


def test_candidate_round_trip_dump_and_validate():
    candidate = Candidate.model_validate(build_candidate_payload())
    dumped = candidate.model_dump(mode="json")
    restored = Candidate.model_validate(dumped)
    assert restored == candidate
