"""Unit tests for the civic OfficeRosterLink model."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from domains.civics.tests.model_payload_builders import build_office_roster_link_payload, build_uuid_string
from domains.civics.types import OfficeRosterLink


def test_office_roster_link_requires_office_id_and_data_source_id() -> None:
    with pytest.raises(ValidationError):
        OfficeRosterLink.model_validate({"data_source_id": build_uuid_string()})
    with pytest.raises(ValidationError):
        OfficeRosterLink.model_validate({"office_id": build_uuid_string()})


def test_office_roster_link_defaults_shared_identity_fields() -> None:
    link = OfficeRosterLink.model_validate(build_office_roster_link_payload())
    assert isinstance(link.id, UUID)
    assert isinstance(link.created_at, datetime)
    assert isinstance(link.updated_at, datetime)
    assert link.created_at.tzinfo == timezone.utc
    assert link.updated_at.tzinfo == timezone.utc


def test_office_roster_link_parses_uuid_foreign_keys() -> None:
    link = OfficeRosterLink.model_validate(build_office_roster_link_payload())
    assert isinstance(link.office_id, UUID)
    assert isinstance(link.data_source_id, UUID)


def test_office_roster_link_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        OfficeRosterLink.model_validate(build_office_roster_link_payload(unknown_field="value"))


def test_office_roster_link_round_trip_dump_and_validate() -> None:
    link = OfficeRosterLink.model_validate(build_office_roster_link_payload())
    dumped = link.model_dump(mode="json")
    restored = OfficeRosterLink.model_validate(dumped)
    assert restored == link
