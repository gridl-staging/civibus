"""Unit tests for the civic Election model."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from domains.civics.tests.model_payload_builders import build_election_payload, build_uuid_string
from domains.civics.types import Election


def test_election_requires_scope_date_and_type() -> None:
    with pytest.raises(ValidationError):
        Election.model_validate({"election_date": "2024-11-05", "election_type": "general"})
    with pytest.raises(ValidationError):
        Election.model_validate({"jurisdiction_scope": "state", "election_type": "general"})
    with pytest.raises(ValidationError):
        Election.model_validate({"jurisdiction_scope": "state", "election_date": "2024-11-05"})


def test_election_defaults_shared_identity_fields() -> None:
    election = Election.model_validate(build_election_payload())
    assert isinstance(election.id, UUID)
    assert isinstance(election.created_at, datetime)
    assert isinstance(election.updated_at, datetime)
    assert election.created_at.tzinfo == timezone.utc
    assert election.updated_at.tzinfo == timezone.utc


def test_election_accepts_optional_fields() -> None:
    election = Election.model_validate(
        build_election_payload(
            office_id=build_uuid_string(),
            electoral_division_id=build_uuid_string(),
            source_record_id=build_uuid_string(),
        )
    )
    assert election.election_date == date(2024, 11, 5)
    assert isinstance(election.office_id, UUID)
    assert isinstance(election.electoral_division_id, UUID)
    assert isinstance(election.source_record_id, UUID)


def test_election_allows_special_primary_semantics() -> None:
    election = Election.model_validate(build_election_payload(election_type="primary", is_special=True))
    assert election.election_type == "primary"
    assert election.is_special is True


def test_election_rejects_invalid_scope() -> None:
    with pytest.raises(ValidationError):
        Election.model_validate(build_election_payload(jurisdiction_scope="planetary"))


def test_election_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Election.model_validate(build_election_payload(unknown_field="value"))
