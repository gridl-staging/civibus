"""Unit tests for the civic FilingDeadline model."""

from __future__ import annotations

from datetime import date
from uuid import UUID

import pytest
from pydantic import ValidationError

from domains.civics.tests.model_payload_builders import build_filing_deadline_payload, build_uuid_string
from domains.civics.types import FilingDeadline


def test_filing_deadline_requires_identity_and_deadline_fields() -> None:
    with pytest.raises(ValidationError):
        FilingDeadline.model_validate(
            {
                "office_id": build_uuid_string(),
                "jurisdiction_scope": "state",
                "deadline_date": "2024-03-01",
                "deadline_kind": "candidate_filing",
            }
        )
    with pytest.raises(ValidationError):
        FilingDeadline.model_validate(
            {
                "election_id": build_uuid_string(),
                "office_id": build_uuid_string(),
                "jurisdiction_scope": "state",
                "deadline_kind": "candidate_filing",
            }
        )


def test_filing_deadline_accepts_optional_fields() -> None:
    filing_deadline = FilingDeadline.model_validate(
        build_filing_deadline_payload(
            state="NC",
            county="Durham",
            municipality="Durham",
            electoral_division_id=build_uuid_string(),
            source_record_id=build_uuid_string(),
        )
    )
    assert isinstance(filing_deadline.election_id, UUID)
    assert isinstance(filing_deadline.office_id, UUID)
    assert filing_deadline.deadline_date == date(2024, 3, 1)
    assert isinstance(filing_deadline.electoral_division_id, UUID)
    assert isinstance(filing_deadline.source_record_id, UUID)


def test_filing_deadline_rejects_invalid_scope() -> None:
    with pytest.raises(ValidationError):
        FilingDeadline.model_validate(build_filing_deadline_payload(jurisdiction_scope="planetary"))


def test_filing_deadline_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        FilingDeadline.model_validate(build_filing_deadline_payload(unknown_field="value"))


def test_filing_deadline_accepts_candidate_filing_open_kind() -> None:
    filing_deadline = FilingDeadline.model_validate(
        build_filing_deadline_payload(
            deadline_kind="candidate_filing_open",
        )
    )
    assert filing_deadline.deadline_kind == "candidate_filing_open"
