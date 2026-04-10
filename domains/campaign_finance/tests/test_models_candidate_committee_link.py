"""Unit tests for campaign-finance CandidateCommitteeLink model."""

from __future__ import annotations

from datetime import date
import pytest
from pydantic import ValidationError

from domains.campaign_finance.tests.model_payload_builders import (
    build_candidate_committee_link_payload,
    build_uuid_string,
    build_valid_period_payload,
)
from domains.campaign_finance.types import CandidateCommitteeLink, ValidDateRange


def test_candidate_committee_link_requires_candidate_committee_and_valid_period():
    with pytest.raises(ValidationError):
        CandidateCommitteeLink.model_validate(build_candidate_committee_link_payload().copy() | {"candidate_id": None})
    with pytest.raises(ValidationError):
        CandidateCommitteeLink.model_validate(build_candidate_committee_link_payload().copy() | {"committee_id": None})
    with pytest.raises(ValidationError):
        CandidateCommitteeLink.model_validate(build_candidate_committee_link_payload().copy() | {"valid_period": None})


def test_candidate_committee_link_allows_optional_fields_and_validates_fks():
    link = CandidateCommitteeLink.model_validate(
        build_candidate_committee_link_payload(
            election_id=build_uuid_string(),
            designation="P",
            candidate_election_year=2024,
            fec_election_year=2024,
            source_record_id=build_uuid_string(),
        )
    )

    assert link.election_id is not None
    assert link.designation == "P"
    assert link.candidate_election_year == 2024
    assert link.fec_election_year == 2024
    assert link.source_record_id is not None


def test_candidate_committee_link_validates_non_empty_valid_period():
    with pytest.raises(ValidationError):
        CandidateCommitteeLink.model_validate(
            build_candidate_committee_link_payload(
                valid_period=build_valid_period_payload(
                    start=date(2024, 1, 1),
                    end=date(2024, 1, 1),
                )
            )
        )


def test_candidate_committee_link_defaults_date_precision_to_year():
    assert CandidateCommitteeLink.model_validate(build_candidate_committee_link_payload()).date_precision == "year"


def test_candidate_committee_link_round_trip_dump_and_validate():
    link = CandidateCommitteeLink.model_validate(
        build_candidate_committee_link_payload(
            valid_period=build_valid_period_payload(
                start=date(2024, 1, 1),
                end=date(2024, 12, 31),
            )
        )
    )
    dumped = link.model_dump(mode="json")
    restored = CandidateCommitteeLink.model_validate(dumped)
    assert restored == link
    assert isinstance(restored.valid_period, ValidDateRange)
