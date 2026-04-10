"""Unit tests for the civic Candidacy model."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from domains.civics.tests.model_payload_builders import build_candidacy_payload, build_uuid_string
from domains.civics.types import Candidacy


def test_candidacy_requires_person_id_and_contest_id() -> None:
    with pytest.raises(ValidationError):
        Candidacy.model_validate({"contest_id": build_uuid_string()})
    with pytest.raises(ValidationError):
        Candidacy.model_validate({"person_id": build_uuid_string()})


def test_candidacy_defaults_shared_identity_fields() -> None:
    candidacy = Candidacy.model_validate(build_candidacy_payload())
    assert isinstance(candidacy.id, UUID)
    assert isinstance(candidacy.created_at, datetime)
    assert isinstance(candidacy.updated_at, datetime)
    assert candidacy.created_at.tzinfo == timezone.utc
    assert candidacy.updated_at.tzinfo == timezone.utc


def test_candidacy_parses_uuid_foreign_keys() -> None:
    candidacy = Candidacy.model_validate(build_candidacy_payload())
    assert isinstance(candidacy.person_id, UUID)
    assert isinstance(candidacy.contest_id, UUID)


def test_candidacy_accepts_optional_fields() -> None:
    candidacy = Candidacy.model_validate(
        build_candidacy_payload(
            party="DEM",
            filing_date="2024-02-15",
            status="filed",
            incumbent_challenge="C",
            candidate_number="12345",
            source_record_id=build_uuid_string(),
        )
    )
    assert candidacy.party == "DEM"
    assert candidacy.filing_date == date(2024, 2, 15)
    assert candidacy.status == "filed"
    assert candidacy.incumbent_challenge == "C"
    assert candidacy.candidate_number == "12345"
    assert isinstance(candidacy.source_record_id, UUID)


def test_candidacy_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Candidacy.model_validate(build_candidacy_payload(unknown_field="value"))


def test_candidacy_round_trip_dump_and_validate() -> None:
    candidacy = Candidacy.model_validate(build_candidacy_payload())
    dumped = candidacy.model_dump(mode="json")
    restored = Candidacy.model_validate(dumped)
    assert restored == candidacy
