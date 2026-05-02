"""Unit tests for the civic Candidacy model."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from domains.civics.tests.model_payload_builders import (
    build_candidacy_mvp_fields_payload,
    build_candidacy_payload,
    build_uuid_string,
)
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
    assert candidacy.name_on_ballot is None
    assert candidacy.is_unexpired_term is False
    assert candidacy.raw_fields == {}
    assert candidacy.committee_id is None


def test_candidacy_parses_uuid_foreign_keys() -> None:
    candidacy = Candidacy.model_validate(build_candidacy_payload())
    assert isinstance(candidacy.person_id, UUID)
    assert isinstance(candidacy.contest_id, UUID)


def test_candidacy_accepts_optional_fields() -> None:
    optional_fields = build_candidacy_mvp_fields_payload()
    candidacy = Candidacy.model_validate(
        build_candidacy_payload(
            party="DEM",
            filing_date="2024-02-15",
            status="filed",
            incumbent_challenge="C",
            candidate_number="12345",
            name_on_ballot=optional_fields["name_on_ballot"],
            is_unexpired_term=optional_fields["is_unexpired_term"],
            raw_fields=optional_fields["raw_fields"],
            committee_id=optional_fields["committee_id"],
            source_record_id=build_uuid_string(),
        )
    )
    assert candidacy.party == "DEM"
    assert candidacy.filing_date == date(2024, 2, 15)
    assert candidacy.status == "filed"
    assert candidacy.incumbent_challenge == "C"
    assert candidacy.candidate_number == "12345"
    assert candidacy.name_on_ballot == optional_fields["name_on_ballot"]
    assert candidacy.is_unexpired_term is True
    assert candidacy.raw_fields == optional_fields["raw_fields"]
    assert isinstance(candidacy.committee_id, UUID)
    assert isinstance(candidacy.source_record_id, UUID)


def test_candidacy_rejects_blank_name_on_ballot() -> None:
    with pytest.raises(ValidationError):
        Candidacy.model_validate(build_candidacy_payload(name_on_ballot=""))
    with pytest.raises(ValidationError):
        Candidacy.model_validate(build_candidacy_payload(name_on_ballot="   "))


def test_candidacy_model_json_schema_includes_mvp_fields() -> None:
    schema = Candidacy.model_json_schema()

    assert {
        "name_on_ballot",
        "is_unexpired_term",
        "raw_fields",
        "committee_id",
    }.issubset(set(schema["properties"]))
    assert set(schema["required"]) == {"person_id", "contest_id"}


def test_candidacy_committee_id_requires_uuid_format() -> None:
    candidacy = Candidacy.model_validate(build_candidacy_payload(committee_id=build_uuid_string()))
    assert isinstance(candidacy.committee_id, UUID)

    with pytest.raises(ValidationError):
        Candidacy.model_validate(build_candidacy_payload(committee_id="not-a-uuid"))


def test_candidacy_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Candidacy.model_validate(build_candidacy_payload(unknown_field="value"))


def test_candidacy_round_trip_dump_and_validate() -> None:
    candidacy = Candidacy.model_validate(build_candidacy_payload())
    dumped = candidacy.model_dump(mode="json")
    restored = Candidacy.model_validate(dumped)
    assert restored == candidacy
