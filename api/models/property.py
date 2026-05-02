"""
Stub summary for MAR18 property API models.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from api.models._validation import validate_inclusive_bounds
from api.models.provenance import SourceInfo

DatePrecision = Literal["day", "month", "quarter", "year", "approximate"]


class ParcelSummaryResponse(BaseModel):

    id: UUID
    reid: str
    pin: str
    site_address: str
    property_description: str | None = None
    city: str | None = None
    zoning_class: str | None = None
    land_class: str | None = None
    acreage: Decimal | None = None
    neighborhood: str | None = None
    fire_district: str | None = None
    is_pending: bool
    deed_date: date | None = None
    deed_book: str | None = None
    deed_page: str | None = None
    jurisdiction_id: UUID | None = None
    sources: list[SourceInfo]


class PropertyAssessmentResponse(BaseModel):
    id: UUID
    tax_year: int
    land_assessed_value: Decimal | None = None
    improvement_assessed_value: Decimal | None = None
    total_assessed_value: Decimal | None = None
    assessed_at: date | None = None
    heated_area: int | None = None
    exemption_description: str | None = None
    sources: list[SourceInfo]


class PropertyOwnershipResponse(BaseModel):

    id: UUID
    owner_name: str
    owner_mail_line1: str | None = None
    owner_mail_line2: str | None = None
    owner_mail_line3: str | None = None
    owner_mail_city: str | None = None
    owner_mail_state: str | None = None
    owner_mail_zip5: str | None = None
    ownership_recorded_at: date | None = None
    valid_period: str
    date_precision: DatePrecision
    owner_person_id: UUID | None = None
    owner_organization_id: UUID | None = None
    owner_address_id: UUID | None = None
    sources: list[SourceInfo]


class ParcelDetailResponse(ParcelSummaryResponse):
    assessments: list[PropertyAssessmentResponse] = Field(default_factory=list)
    ownership: list[PropertyOwnershipResponse] = Field(default_factory=list)


class ParcelListParams(BaseModel):

    city: str | None = None
    zoning_class: str | None = None
    min_acreage: Decimal | None = None
    max_acreage: Decimal | None = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_range_bounds(self) -> ParcelListParams:
        validate_inclusive_bounds(
            self.min_acreage,
            self.max_acreage,
            min_name="min_acreage",
            max_name="max_acreage",
        )
        return self
