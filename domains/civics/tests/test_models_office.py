"""Unit tests for the civic Office model."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from domains.civics.tests.model_payload_builders import (
    build_office_browse_status_payload,
    build_office_payload,
    build_uuid_string,
)
from domains.civics.types import Office, OfficeBrowseStatus


def test_office_requires_name_and_office_level() -> None:
    with pytest.raises(ValidationError):
        Office.model_validate({"office_level": "federal"})
    with pytest.raises(ValidationError):
        Office.model_validate({"name": "Governor"})


def test_office_rejects_empty_name() -> None:
    with pytest.raises(ValidationError):
        Office.model_validate(build_office_payload(name=""))


def test_office_defaults_shared_identity_fields() -> None:
    office = Office.model_validate(build_office_payload())
    assert isinstance(office.id, UUID)
    assert isinstance(office.created_at, datetime)
    assert isinstance(office.updated_at, datetime)
    assert office.created_at.tzinfo == timezone.utc
    assert office.updated_at.tzinfo == timezone.utc


def test_office_defaults_elected_and_seats() -> None:
    office = Office.model_validate(build_office_payload())
    assert office.is_elected is True
    assert office.number_of_seats == 1


def test_office_accepts_all_valid_levels() -> None:
    for level in ("federal", "state", "county", "municipal", "judicial", "school_board", "special_district"):
        office = Office.model_validate(build_office_payload(office_level=level))
        assert office.office_level == level


def test_office_rejects_invalid_level() -> None:
    with pytest.raises(ValidationError):
        Office.model_validate(build_office_payload(office_level="galactic"))


def test_office_validates_state_code() -> None:
    office = Office.model_validate(build_office_payload(state="NC"))
    assert office.state == "NC"

    with pytest.raises(ValidationError):
        Office.model_validate(build_office_payload(state="north_carolina"))


def test_office_parses_optional_uuid_foreign_keys() -> None:
    office = Office.model_validate(
        build_office_payload(
            jurisdiction_id=build_uuid_string(),
            source_record_id=build_uuid_string(),
        )
    )
    assert isinstance(office.jurisdiction_id, UUID)
    assert isinstance(office.source_record_id, UUID)


def test_office_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Office.model_validate(build_office_payload(unknown_field="value"))


def test_office_round_trip_dump_and_validate() -> None:
    office = Office.model_validate(build_office_payload())
    dumped = office.model_dump(mode="json")
    restored = Office.model_validate(dumped)
    assert restored == office


def test_office_browse_status_defaults_to_no_data_gaps() -> None:
    office_status = OfficeBrowseStatus.model_validate(build_office_browse_status_payload())
    assert office_status.has_officeholder is True
    assert office_status.has_active_contest is True
    assert office_status.incomplete_data_states == ()


def test_office_browse_status_derives_missing_data_states_from_query_flags() -> None:
    office_status = OfficeBrowseStatus.model_validate(
        build_office_browse_status_payload(
            has_officeholder=False,
            has_active_contest=False,
        )
    )
    assert office_status.incomplete_data_states == ("no_officeholder", "no_active_contest")
