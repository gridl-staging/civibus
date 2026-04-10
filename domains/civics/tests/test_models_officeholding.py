"""Unit tests for the civic Officeholding model."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from core.types.python.models import ValidDateRange
from domains.civics.tests.model_payload_builders import (
    build_officeholding_payload,
    build_uuid_string,
    build_valid_period_payload,
)
from domains.civics.types import Officeholding


def test_officeholding_requires_person_id_and_office_id() -> None:
    with pytest.raises(ValidationError):
        Officeholding.model_validate({"office_id": build_uuid_string()})
    with pytest.raises(ValidationError):
        Officeholding.model_validate({"person_id": build_uuid_string()})


def test_officeholding_defaults_shared_identity_fields() -> None:
    oh = Officeholding.model_validate(build_officeholding_payload())
    assert isinstance(oh.id, UUID)
    assert isinstance(oh.created_at, datetime)
    assert isinstance(oh.updated_at, datetime)
    assert oh.created_at.tzinfo == timezone.utc
    assert oh.updated_at.tzinfo == timezone.utc
    assert isinstance(oh.valid_period, ValidDateRange)
    assert oh.valid_period.start_date is None
    assert oh.valid_period.end_date is None
    assert oh.holder_status == "elected"
    assert oh.date_precision == "day"


def test_officeholding_parses_uuid_foreign_keys() -> None:
    oh = Officeholding.model_validate(build_officeholding_payload())
    assert isinstance(oh.person_id, UUID)
    assert isinstance(oh.office_id, UUID)


def test_officeholding_accepts_optional_fields() -> None:
    oh = Officeholding.model_validate(
        build_officeholding_payload(
            electoral_division_id=build_uuid_string(),
            holder_status="appointed",
            valid_period=build_valid_period_payload(
                start=date(2023, 1, 1),
                end=date(2027, 1, 1),
            ),
            date_precision="month",
            source_record_id=build_uuid_string(),
        )
    )
    assert isinstance(oh.electoral_division_id, UUID)
    assert oh.holder_status == "appointed"
    assert oh.valid_period.start_date == date(2023, 1, 1)
    assert oh.valid_period.end_date == date(2027, 1, 1)
    assert oh.date_precision == "month"
    assert isinstance(oh.source_record_id, UUID)


@pytest.mark.parametrize("holder_status", ["elected", "appointed", "acting", "former"])
def test_officeholding_accepts_supported_holder_status_values(holder_status: str) -> None:
    oh = Officeholding.model_validate(build_officeholding_payload(holder_status=holder_status))
    assert oh.holder_status == holder_status


def test_officeholding_rejects_vacancy_as_person_backed_status() -> None:
    with pytest.raises(ValidationError):
        Officeholding.model_validate(build_officeholding_payload(holder_status="vacant"))


def test_officeholding_rejects_invalid_temporal_range() -> None:
    with pytest.raises(ValidationError, match="valid_period must be non-empty"):
        Officeholding.model_validate(
            build_officeholding_payload(
                valid_period=build_valid_period_payload(
                    start=date(2027, 1, 1),
                    end=date(2023, 1, 1),
                ),
            )
        )


def test_officeholding_rejects_equal_start_and_end() -> None:
    with pytest.raises(ValidationError, match="valid_period must be non-empty"):
        Officeholding.model_validate(
            build_officeholding_payload(
                valid_period=build_valid_period_payload(
                    start=date(2024, 1, 1),
                    end=date(2024, 1, 1),
                ),
            )
        )


def test_officeholding_allows_open_ended_ranges() -> None:
    oh_start_only = Officeholding.model_validate(build_officeholding_payload(valid_period={"start_date": "2023-01-01"}))
    assert oh_start_only.valid_period.start_date == date(2023, 1, 1)
    assert oh_start_only.valid_period.end_date is None

    oh_end_only = Officeholding.model_validate(build_officeholding_payload(valid_period={"end_date": "2027-01-01"}))
    assert oh_end_only.valid_period.start_date is None
    assert oh_end_only.valid_period.end_date == date(2027, 1, 1)


def test_officeholding_rejects_invalid_date_precision() -> None:
    with pytest.raises(ValidationError):
        Officeholding.model_validate(build_officeholding_payload(date_precision="week"))


def test_officeholding_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Officeholding.model_validate(build_officeholding_payload(unknown_field="value"))


def test_officeholding_round_trip_dump_and_validate() -> None:
    oh = Officeholding.model_validate(build_officeholding_payload())
    dumped = oh.model_dump(mode="json")
    restored = Officeholding.model_validate(dumped)
    assert restored == oh
    assert isinstance(restored.valid_period, ValidDateRange)
