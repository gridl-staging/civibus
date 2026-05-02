"""Unit tests for the civic ElectoralDivision model."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from domains.civics.tests.model_payload_builders import (
    build_electoral_division_payload,
    build_uuid_string,
)
from domains.civics.types import ElectoralDivision


def test_electoral_division_requires_name_and_type() -> None:
    with pytest.raises(ValidationError):
        ElectoralDivision.model_validate({"division_type": "congressional_district"})
    with pytest.raises(ValidationError):
        ElectoralDivision.model_validate({"name": "NC-01"})


def test_electoral_division_rejects_empty_name() -> None:
    with pytest.raises(ValidationError):
        ElectoralDivision.model_validate(build_electoral_division_payload(name=""))


def test_electoral_division_defaults_shared_identity_fields() -> None:
    ed = ElectoralDivision.model_validate(build_electoral_division_payload())
    assert isinstance(ed.id, UUID)
    assert isinstance(ed.created_at, datetime)
    assert isinstance(ed.updated_at, datetime)
    assert ed.created_at.tzinfo == timezone.utc
    assert ed.updated_at.tzinfo == timezone.utc
    assert ed.is_container is False
    assert ed.geometry is None


def test_electoral_division_accepts_all_valid_types() -> None:
    valid_types = (
        "congressional_district",
        "state_legislative_upper",
        "state_legislative_lower",
        "county",
        "municipal",
        "judicial_district",
        "school_district",
        "special_district",
        "at_large",
        "statewide",
    )
    for division_type in valid_types:
        ed = ElectoralDivision.model_validate(build_electoral_division_payload(division_type=division_type))
        assert ed.division_type == division_type


def test_electoral_division_rejects_invalid_type() -> None:
    with pytest.raises(ValidationError):
        ElectoralDivision.model_validate(build_electoral_division_payload(division_type="galactic"))


def test_electoral_division_validates_state_code() -> None:
    ed = ElectoralDivision.model_validate(build_electoral_division_payload(state="NC"))
    assert ed.state == "NC"

    with pytest.raises(ValidationError):
        ElectoralDivision.model_validate(build_electoral_division_payload(state="north_carolina"))


def test_electoral_division_accepts_optional_fields() -> None:
    geometry = {
        "type": "Polygon",
        "coordinates": [
            [
                [-78.8, 35.7],
                [-78.7, 35.7],
                [-78.7, 35.8],
                [-78.8, 35.8],
                [-78.8, 35.7],
            ]
        ],
    }
    ed = ElectoralDivision.model_validate(
        build_electoral_division_payload(
            district_number="01",
            ocd_id="ocd-division/country:us/state:nc/cd:1",
            geometry=geometry,
            is_container=True,
            parent_id=build_uuid_string(),
            boundary_year=2020,
        )
    )
    assert ed.district_number == "01"
    assert ed.ocd_id == "ocd-division/country:us/state:nc/cd:1"
    assert ed.geometry == geometry
    assert ed.is_container is True
    assert isinstance(ed.parent_id, UUID)
    assert ed.boundary_year == 2020


def test_electoral_division_rejects_non_mapping_geometry() -> None:
    with pytest.raises(ValidationError):
        ElectoralDivision.model_validate(build_electoral_division_payload(geometry="POINT(-78.6 35.8)"))


def test_electoral_division_rejects_non_ocd_prefixed_ocd_id() -> None:
    with pytest.raises(ValidationError):
        ElectoralDivision.model_validate(build_electoral_division_payload(ocd_id="country:us/state:nc"))


def test_electoral_division_parses_source_record_id() -> None:
    ed = ElectoralDivision.model_validate(build_electoral_division_payload(source_record_id=build_uuid_string()))
    assert isinstance(ed.source_record_id, UUID)


def test_electoral_division_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ElectoralDivision.model_validate(build_electoral_division_payload(unknown_field="value"))


def test_electoral_division_round_trip_dump_and_validate() -> None:
    geometry = {
        "type": "Polygon",
        "coordinates": [
            [
                [-78.9, 35.9],
                [-78.8, 35.9],
                [-78.8, 36.0],
                [-78.9, 36.0],
                [-78.9, 35.9],
            ]
        ],
    }
    ed = ElectoralDivision.model_validate(build_electoral_division_payload(geometry=geometry))
    dumped = ed.model_dump(mode="json")
    restored = ElectoralDivision.model_validate(dumped)
    assert restored == ed
    assert restored.geometry == geometry
