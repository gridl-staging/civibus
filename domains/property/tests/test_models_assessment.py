"""Unit tests for the property Assessment model."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from domains.property.tests.model_payload_builders import build_assessment_payload, build_uuid_string
from domains.property.types import Assessment


def test_assessment_requires_parcel_and_tax_year() -> None:
    with pytest.raises(ValidationError):
        Assessment.model_validate({"tax_year": 2024})
    with pytest.raises(ValidationError):
        Assessment.model_validate({"parcel_id": build_uuid_string()})


def test_assessment_defaults_shared_identity_fields() -> None:
    assessment = Assessment.model_validate(build_assessment_payload())

    assert isinstance(assessment.id, UUID)
    assert isinstance(assessment.created_at, datetime)
    assert isinstance(assessment.updated_at, datetime)
    assert assessment.created_at.tzinfo == timezone.utc
    assert assessment.updated_at.tzinfo == timezone.utc


def test_assessment_allows_nullable_assessed_values() -> None:
    assessment = Assessment.model_validate(
        build_assessment_payload(
            land_assessed_value=None,
            improvement_assessed_value=None,
            total_assessed_value=None,
            assessed_at=None,
        )
    )

    assert assessment.land_assessed_value is None
    assert assessment.improvement_assessed_value is None
    assert assessment.total_assessed_value is None
    assert assessment.assessed_at is None


def test_assessment_parses_uuid_fields_and_decimal_values() -> None:
    assessment = Assessment.model_validate(
        build_assessment_payload(
            source_record_id=build_uuid_string(),
            total_assessed_value=Decimal("99999.99"),
            assessed_at=date(2024, 6, 30),
        )
    )

    assert isinstance(assessment.parcel_id, UUID)
    assert isinstance(assessment.source_record_id, UUID)
    assert assessment.total_assessed_value == Decimal("99999.99")


def test_assessment_validates_tax_year_bounds() -> None:
    with pytest.raises(ValidationError):
        Assessment.model_validate(build_assessment_payload(tax_year=1899))


def test_assessment_round_trip_dump_and_validate() -> None:
    assessment = Assessment.model_validate(build_assessment_payload())
    dumped = assessment.model_dump(mode="json")
    restored = Assessment.model_validate(dumped)

    assert restored == assessment
