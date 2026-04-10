from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field

from api.models.provenance import SourceInfo


class PersonResponse(BaseModel):
    id: UUID
    canonical_name: str
    name_variants: list[str] = Field(default_factory=list)
    first_name: str | None = None
    middle_name: str | None = None
    last_name: str | None = None
    suffix: str | None = None
    date_of_birth: date | None = None
    year_of_birth: int | None = None
    identifiers: dict[str, str] = Field(default_factory=dict)
    primary_address_id: UUID | None = None
    er_cluster_id: UUID | None = None
    er_confidence: float | None = None
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
