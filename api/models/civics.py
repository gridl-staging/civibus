"""Pydantic response models for civic domain endpoints (offices, contests, candidacies, officeholdings)."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field

from api.models.provenance import SourceInfo
from domains.civics.types.models import (
    DatePrecisionLiteral,
    ElectionTypeLiteral,
    OfficeLevelLiteral,
    OfficeIncompleteDataStateLiteral,
    OfficeholdingStatusLiteral,
)


# ---------------------------------------------------------------------------
# Embedded summaries (used inside detail responses)
# ---------------------------------------------------------------------------


class OfficeholderSummary(BaseModel):
    """Summary of a current officeholder, embedded in OfficeResponse."""

    officeholding_id: UUID
    person_id: UUID
    person_name: str
    holder_status: OfficeholdingStatusLiteral


class CandidacySummary(BaseModel):
    """Summary of a candidacy, embedded in ContestResponse."""

    candidacy_id: UUID
    person_id: UUID
    person_name: str
    party: str | None = None
    status: str | None = None
    incumbent_challenge: str | None = None


# ---------------------------------------------------------------------------
# Detail responses
# ---------------------------------------------------------------------------


class OfficeResponse(BaseModel):
    id: UUID
    name: str
    office_level: OfficeLevelLiteral
    title: str | None = None
    jurisdiction_id: UUID | None = None
    state: str | None = None
    is_elected: bool
    number_of_seats: int
    current_officeholders: list[OfficeholderSummary] = Field(default_factory=list)
    incomplete_data_states: list[OfficeIncompleteDataStateLiteral] = Field(default_factory=list)
    sources: list[SourceInfo] = Field(default_factory=list)


class ContestResponse(BaseModel):
    id: UUID
    name: str
    election_date: date | None = None
    election_type: ElectionTypeLiteral
    office_id: UUID
    electoral_division_id: UUID | None = None
    number_of_seats: int
    filing_deadline: date | None = None
    is_partisan: bool
    candidate_list_incomplete: bool
    candidacies: list[CandidacySummary] = Field(default_factory=list)
    sources: list[SourceInfo] = Field(default_factory=list)


class CandidacyResponse(BaseModel):
    id: UUID
    person_id: UUID
    person_name: str
    contest_id: UUID
    party: str | None = None
    filing_date: date | None = None
    status: str | None = None
    incumbent_challenge: str | None = None
    candidate_number: str | None = None
    sources: list[SourceInfo] = Field(default_factory=list)


class OfficeholdingResponse(BaseModel):
    id: UUID
    person_id: UUID
    person_name: str
    office_id: UUID
    electoral_division_id: UUID | None = None
    holder_status: OfficeholdingStatusLiteral
    valid_period_lower: date | None = None
    valid_period_upper: date | None = None
    date_precision: DatePrecisionLiteral
    sources: list[SourceInfo] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Browse / list responses
# ---------------------------------------------------------------------------


class OfficeListItem(BaseModel):
    id: UUID
    name: str
    office_level: OfficeLevelLiteral
    title: str | None = None
    state: str | None = None
    is_elected: bool
    number_of_seats: int


class ContactSummary(BaseModel):
    id: UUID
    type: str
    value_normalized: str | None = None
    role: str | None = None
    owner_type: str
    owner_id: UUID
