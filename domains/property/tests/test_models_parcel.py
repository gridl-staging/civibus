"""Unit tests for the property Parcel model."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from domains.property.tests.model_payload_builders import build_parcel_payload, build_uuid_string
from domains.property.types import Parcel


def test_parcel_requires_reid_pin_and_site_address() -> None:
    with pytest.raises(ValidationError):
        Parcel.model_validate({"pin": "0821-01-20-1234", "site_address": "123 Main St"})
    with pytest.raises(ValidationError):
        Parcel.model_validate({"reid": "123456789", "site_address": "123 Main St"})
    with pytest.raises(ValidationError):
        Parcel.model_validate({"reid": "123456789", "pin": "0821-01-20-1234"})


def test_parcel_defaults_shared_identity_fields() -> None:
    parcel = Parcel.model_validate(build_parcel_payload())

    assert isinstance(parcel.id, UUID)
    assert isinstance(parcel.created_at, datetime)
    assert isinstance(parcel.updated_at, datetime)
    assert parcel.created_at.tzinfo == timezone.utc
    assert parcel.updated_at.tzinfo == timezone.utc


def test_parcel_parses_optional_uuid_foreign_keys() -> None:
    parcel = Parcel.model_validate(
        build_parcel_payload(
            jurisdiction_id=build_uuid_string(),
            source_record_id=build_uuid_string(),
        )
    )

    assert isinstance(parcel.jurisdiction_id, UUID)
    assert isinstance(parcel.source_record_id, UUID)


def test_parcel_round_trip_dump_and_validate() -> None:
    parcel = Parcel.model_validate(build_parcel_payload())
    dumped = parcel.model_dump(mode="json")
    restored = Parcel.model_validate(dumped)

    assert restored == parcel
