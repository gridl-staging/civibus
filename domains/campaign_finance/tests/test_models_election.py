"""Unit tests for campaign-finance Election model."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from domains.campaign_finance.tests.model_payload_builders import (
    build_election_payload,
    build_uuid_string,
    build_valid_period_payload,
)
from domains.campaign_finance.types import Election, OfficeType, ValidDateRange


def test_election_defaults_shared_identity_fields():
    election = Election.model_validate(build_election_payload())
    assert isinstance(election.id, UUID)
    assert isinstance(election.created_at, datetime)
    assert isinstance(election.updated_at, datetime)
    assert election.created_at.tzinfo == timezone.utc
    assert election.updated_at.tzinfo == timezone.utc


def test_election_uses_valid_date_range_representation():
    election = Election.model_validate(build_election_payload())
    assert isinstance(election.valid_period, ValidDateRange)
    assert election.valid_period.start_date == date(2024, 1, 1)
    assert election.valid_period.end_date == date(2024, 12, 31)


def test_election_defaults_valid_period_to_stage2_unbounded_range():
    payload = build_election_payload()
    payload.pop("valid_period")

    election = Election.model_validate(payload)
    assert isinstance(election.valid_period, ValidDateRange)
    assert election.valid_period.start_date is None
    assert election.valid_period.end_date is None


def test_election_validates_required_and_allowed_fields():
    election = Election.model_validate(build_election_payload())
    assert election.office is OfficeType.HOUSE

    with pytest.raises(ValidationError):
        Election.model_validate(build_election_payload(office="G"))
    with pytest.raises(ValidationError):
        Election.model_validate(build_election_payload(jurisdiction_type="county"))
    with pytest.raises(ValidationError):
        Election.model_validate(build_election_payload(jurisdiction_code=None))
    with pytest.raises(ValidationError):
        Election.model_validate(build_election_payload(candidate_election_year=1899))
    with pytest.raises(ValidationError):
        Election.model_validate(build_election_payload(date_precision="week"))


def test_election_allows_optional_fec_year_and_district():
    election = Election.model_validate(
        build_election_payload(
            fec_election_year=None,
            district=None,
        )
    )
    assert election.fec_election_year is None
    assert election.district is None


def test_election_parses_source_record_uuid():
    election = Election.model_validate(build_election_payload(source_record_id=build_uuid_string()))
    assert isinstance(election.source_record_id, UUID)


def test_election_rejects_empty_valid_period_values():
    with pytest.raises(ValidationError):
        Election.model_validate(build_election_payload(valid_period=None))
    with pytest.raises(ValidationError):
        Election.model_validate(
            build_election_payload(
                valid_period=build_valid_period_payload(
                    start=date(2024, 1, 1),
                    end=date(2024, 1, 1),
                )
            )
        )


def test_election_round_trip_dump_and_validate():
    election = Election.model_validate(build_election_payload())
    dumped = election.model_dump(mode="json")
    restored = Election.model_validate(dumped)
    assert restored == election
