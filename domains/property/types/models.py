"""
Stub summary for MAR18_cross_domain_er_and_property_graph/civibus_dev/domains/property/types/models.py.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.types.python.models import (
    utc_now,
    validate_optional_fixed_digit_string,
    validate_optional_state_code,
)


class PropertyBaseModel(BaseModel):
    """Shared constructor policy for property records."""

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at", "updated_at", mode="after")
    @classmethod
    def _normalize_timestamp_to_utc(cls, timestamp: datetime) -> datetime:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must include timezone information")
        return timestamp.astimezone(timezone.utc)


class Parcel(PropertyBaseModel):
    reid: str = Field(min_length=1)
    pin: str = Field(min_length=1)
    site_address: str = Field(min_length=1)
    jurisdiction_id: UUID | None = None
    zoning_class: str | None = None
    source_record_id: UUID | None = None


class Assessment(PropertyBaseModel):
    parcel_id: UUID
    tax_year: int = Field(ge=1900)
    land_assessed_value: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    improvement_assessed_value: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    total_assessed_value: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    assessed_at: date | None = None
    source_record_id: UUID | None = None


class Ownership(PropertyBaseModel):

    parcel_id: UUID
    owner_name: str = Field(min_length=1)
    owner_mail_line1: str | None = None
    owner_mail_line2: str | None = None
    owner_mail_city: str | None = None
    owner_mail_state: str | None = None
    owner_mail_zip5: str | None = None
    ownership_recorded_at: date | None = None
    source_record_id: UUID | None = None

    @field_validator("owner_mail_state")
    @classmethod
    def _validate_owner_mail_state(cls, value: str | None) -> str | None:
        return validate_optional_state_code(value, field_name="owner_mail_state")

    @field_validator("owner_mail_zip5")
    @classmethod
    def _validate_owner_mail_zip5(cls, value: str | None) -> str | None:
        return validate_optional_fixed_digit_string(value, expected_length=5, field_name="owner_mail_zip5")
