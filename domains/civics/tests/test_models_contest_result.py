"""Unit tests for the civic ContestResult model."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from domains.civics.tests.model_payload_builders import build_contest_result_payload, build_uuid_string
from domains.civics.types import ContestResult


def test_contest_result_requires_contest_name_and_election_date() -> None:
    with pytest.raises(ValidationError):
        ContestResult.model_validate({"candidate_name_on_ballot": "ALEX EXAMPLE", "election_date": "2024-11-05"})
    with pytest.raises(ValidationError):
        ContestResult.model_validate({"contest_id": build_uuid_string(), "election_date": "2024-11-05"})
    with pytest.raises(ValidationError):
        ContestResult.model_validate({"contest_id": build_uuid_string(), "candidate_name_on_ballot": "ALEX EXAMPLE"})


def test_contest_result_defaults_and_uuid_date_parsing() -> None:
    result = ContestResult.model_validate(build_contest_result_payload())
    assert isinstance(result.id, UUID)
    assert isinstance(result.created_at, datetime)
    assert isinstance(result.updated_at, datetime)
    assert result.created_at.tzinfo == timezone.utc
    assert result.updated_at.tzinfo == timezone.utc
    assert isinstance(result.contest_id, UUID)
    assert result.election_date == date(2024, 11, 5)
    assert result.is_winner is False


def test_contest_result_accepts_optional_fields() -> None:
    result = ContestResult.model_validate(
        build_contest_result_payload(
            is_winner=True,
            source_record_id=build_uuid_string(),
        )
    )
    assert result.is_winner is True
    assert isinstance(result.source_record_id, UUID)


def test_contest_result_optional_fields_default_when_omitted() -> None:
    result = ContestResult.model_validate(build_contest_result_payload())
    assert result.is_winner is False
    assert result.source_record_id is None


def test_contest_result_model_json_schema_includes_result_fields() -> None:
    schema = ContestResult.model_json_schema()

    assert {
        "contest_id",
        "candidate_name_on_ballot",
        "election_date",
        "is_winner",
        "source_record_id",
    }.issubset(set(schema["properties"]))
    assert set(schema["required"]) == {"contest_id", "candidate_name_on_ballot", "election_date"}


def test_contest_result_rejects_blank_candidate_name() -> None:
    with pytest.raises(ValidationError):
        ContestResult.model_validate(build_contest_result_payload(candidate_name_on_ballot=""))
    with pytest.raises(ValidationError):
        ContestResult.model_validate(build_contest_result_payload(candidate_name_on_ballot="   "))


def test_contest_result_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ContestResult.model_validate(build_contest_result_payload(unexpected_field="value"))
