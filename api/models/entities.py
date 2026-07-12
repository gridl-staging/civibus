"""
Stub summary for jun04_3pm_3_member_photo_bio_enrichment/civibus_dev/api/models/entities.py.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from api.models.provenance import SourceInfo


class PersonPortraitResponse(BaseModel):
    status: str
    rights_status: str
    source_image_url: str | None = None
    mime_type: str | None = None
    width_px: int | None = None
    height_px: int | None = None


class PersonResponse(BaseModel):

    id: UUID
    canonical_name: str
    name_variants: list[str] = Field(default_factory=list)
    first_name: str | None = None
    middle_name: str | None = None
    last_name: str | None = None
    suffix: str | None = None
    occupation: str | None = None
    education: str | None = None
    bio_text: str | None = None
    bio_source_url: str | None = None
    bio_license: str | None = None
    bio_pulled_at: datetime | None = None
    date_of_birth: date | None = None
    year_of_birth: int | None = None
    identifiers: dict[str, str | list[str]] = Field(default_factory=dict)
    primary_address_id: UUID | None = None
    er_cluster_id: UUID | None = None
    er_confidence: float | None = None
    portrait: PersonPortraitResponse | None = None
    sources: list[SourceInfo]


class PersonSlugResult(BaseModel):
    id: UUID
    canonical_name: str
    first_name: str | None = None
    last_name: str | None = None
    suffix: str | None = None


class OrgResponse(BaseModel):
    id: UUID
    canonical_name: str
    name_variants: list[str] = Field(default_factory=list)
    org_type: str | None = None
    identifiers: dict[str, str] = Field(default_factory=dict)
    registered_state: str | None = None
    formation_date: date | None = None
    dissolution_date: date | None = None
    primary_address_id: UUID | None = None
    er_cluster_id: UUID | None = None
    er_confidence: float | None = None
    sources: list[SourceInfo]
