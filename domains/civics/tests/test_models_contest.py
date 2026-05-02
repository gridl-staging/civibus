"""Unit tests for the civic Contest model."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from domains.civics.tests.model_payload_builders import build_contest_payload, build_uuid_string
from domains.civics.types import Contest


def test_contest_requires_name_election_type_and_office_id() -> None:
    with pytest.raises(ValidationError):
        Contest.model_validate({"election_type": "general", "office_id": build_uuid_string()})
    with pytest.raises(ValidationError):
        Contest.model_validate({"name": "NC-01 2024 General", "office_id": build_uuid_string()})
    with pytest.raises(ValidationError):
        Contest.model_validate({"name": "NC-01 2024 General", "election_type": "general"})


def test_contest_rejects_empty_name() -> None:
    with pytest.raises(ValidationError):
        Contest.model_validate(build_contest_payload(name=""))


def test_contest_defaults_shared_identity_fields() -> None:
    contest = Contest.model_validate(build_contest_payload())
    assert isinstance(contest.id, UUID)
    assert isinstance(contest.created_at, datetime)
    assert isinstance(contest.updated_at, datetime)
    assert contest.created_at.tzinfo == timezone.utc
    assert contest.updated_at.tzinfo == timezone.utc


def test_contest_defaults_seats_and_partisan() -> None:
    contest = Contest.model_validate(build_contest_payload())
    assert contest.number_of_seats == 1
    assert contest.is_partisan is True
    assert contest.candidate_list_incomplete is False


def test_contest_accepts_all_valid_election_types() -> None:
    for election_type in ("general", "primary", "runoff", "special", "recall"):
        contest = Contest.model_validate(build_contest_payload(election_type=election_type))
        assert contest.election_type == election_type


def test_contest_rejects_invalid_election_type() -> None:
    with pytest.raises(ValidationError):
        Contest.model_validate(build_contest_payload(election_type="exhibition"))


def test_contest_accepts_optional_fields() -> None:
    contest = Contest.model_validate(
        build_contest_payload(
            election_date="2024-11-05",
            election_id=build_uuid_string(),
            electoral_division_id=build_uuid_string(),
            filing_deadline="2024-03-01",
            candidate_list_incomplete=True,
            source_record_id=build_uuid_string(),
        )
    )
    assert contest.election_date == date(2024, 11, 5)
    assert isinstance(contest.election_id, UUID)
    assert isinstance(contest.electoral_division_id, UUID)
    assert contest.filing_deadline == date(2024, 3, 1)
    assert contest.candidate_list_incomplete is True
    assert isinstance(contest.source_record_id, UUID)


def test_contest_parses_office_id_as_uuid() -> None:
    contest = Contest.model_validate(build_contest_payload())
    assert isinstance(contest.office_id, UUID)


def test_contest_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Contest.model_validate(build_contest_payload(unknown_field="value"))


def test_contest_round_trip_dump_and_validate() -> None:
    contest = Contest.model_validate(build_contest_payload())
    dumped = contest.model_dump(mode="json")
    restored = Contest.model_validate(dumped)
    assert restored == contest
