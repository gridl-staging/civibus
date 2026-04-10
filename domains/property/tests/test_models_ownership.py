"""Unit tests for the property Ownership model."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from domains.property.tests.model_payload_builders import build_ownership_payload, build_uuid_string
from domains.property.types import Ownership


def test_ownership_requires_parcel_owner_and_mailing_address_basics() -> None:
    with pytest.raises(ValidationError):
        Ownership.model_validate({"owner_name": "Jordan Fields"})
    with pytest.raises(ValidationError):
        Ownership.model_validate({"parcel_id": build_uuid_string()})


def test_ownership_defaults_shared_identity_fields() -> None:
    ownership = Ownership.model_validate(build_ownership_payload())

    assert isinstance(ownership.id, UUID)
    assert isinstance(ownership.created_at, datetime)
    assert isinstance(ownership.updated_at, datetime)
    assert ownership.created_at.tzinfo == timezone.utc
    assert ownership.updated_at.tzinfo == timezone.utc


def test_ownership_validates_owner_mail_state_and_zip() -> None:
    with pytest.raises(ValidationError):
        Ownership.model_validate(build_ownership_payload(owner_mail_state="North Carolina"))
    with pytest.raises(ValidationError):
        Ownership.model_validate(build_ownership_payload(owner_mail_zip5="2770"))


def test_ownership_allows_nullable_owner_mail_fields() -> None:
    ownership = Ownership.model_validate(
        build_ownership_payload(
            owner_mail_line1=None,
            owner_mail_line2=None,
            owner_mail_city=None,
            owner_mail_state=None,
            owner_mail_zip5=None,
        )
    )

    assert ownership.owner_mail_line1 is None
    assert ownership.owner_mail_line2 is None
    assert ownership.owner_mail_city is None
    assert ownership.owner_mail_state is None
    assert ownership.owner_mail_zip5 is None


def test_ownership_parses_source_record_id_uuid() -> None:
    ownership = Ownership.model_validate(build_ownership_payload(source_record_id=build_uuid_string()))

    assert isinstance(ownership.parcel_id, UUID)
    assert isinstance(ownership.source_record_id, UUID)


def test_ownership_round_trip_dump_and_validate() -> None:
    ownership = Ownership.model_validate(build_ownership_payload())
    dumped = ownership.model_dump(mode="json")
    restored = Ownership.model_validate(dumped)

    assert restored == ownership
