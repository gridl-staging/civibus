
from __future__ import annotations

from datetime import date
from typing import Any, Literal
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


class OfficeholdingPersonPeriodSummary(BaseModel):
    """Shared officeholding person/period fields for office detail embedded rows."""

    officeholding_id: UUID
    person_id: UUID
    person_name: str
    holder_status: OfficeholdingStatusLiteral
    electoral_division_id: UUID | None = None
    electoral_division_type: str | None = None
    electoral_division_state: str | None = None
    valid_period_lower: date | None = None
    valid_period_upper: date | None = None
    date_precision: DatePrecisionLiteral


class OfficeCurrentHolderCard(OfficeholdingPersonPeriodSummary):
    """Summary card payload for the currently active officeholder."""


class OfficeholdingTimelineSummary(OfficeholdingPersonPeriodSummary):
    """Timeline row for officeholding history shown on office detail pages."""
    is_active: bool
    # Backend-owned ended-state flag derived from the same CURRENT_DATE
    # active-period semantics as is_active: a row is term_ended only when its
    # upper bound is non-null and has already passed today on the server.
    # Frontend presenters must rely on this instead of inferring ended-state
    # from holder_status or recomputing today on the client.
    term_ended: bool


class CandidacySummary(BaseModel):
    """Summary of a candidacy, embedded in ContestResponse."""

    candidacy_id: UUID
    person_id: UUID
    person_name: str
    party: str | None = None
    status: str | None = None
    incumbent_challenge: str | None = None


class OfficeRecentContestSummary(BaseModel):
    """Recent contest summary row for office context."""

    contest_id: UUID
    contest_name: str
    election_date: date | None = None
    election_type: ElectionTypeLiteral
    filing_deadline: date | None = None
    electoral_division_id: UUID | None = None
    electoral_division_type: str | None = None
    electoral_division_state: str | None = None
    is_partisan: bool
    candidate_list_incomplete: bool


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
    electoral_division_id: UUID | None = None
    is_elected: bool
    number_of_seats: int
    current_officeholders: list[OfficeholderSummary] = Field(default_factory=list)
    current_holder_card: OfficeCurrentHolderCard | None = None
    officeholding_timeline: list[OfficeholdingTimelineSummary] = Field(default_factory=list)
    recent_contests: list[OfficeRecentContestSummary] = Field(default_factory=list)
    selected_electoral_division_id: UUID | None = None
    selected_electoral_division_type: str | None = None
    selected_electoral_division_state: str | None = None
    incomplete_data_states: list[OfficeIncompleteDataStateLiteral] = Field(default_factory=list)
    sources: list[SourceInfo] = Field(default_factory=list)


class ContestResponse(BaseModel):
    id: UUID
    name: str
    election_date: date | None = None
    election_type: ElectionTypeLiteral
    office_id: UUID
    electoral_division_id: UUID | None = None
    electoral_division_type: str | None = None
    electoral_division_state: str | None = None
    number_of_seats: int
    filing_deadline: date | None = None
    is_partisan: bool
    candidate_list_incomplete: bool
    result_winner_candidacy_id: UUID | None = None
    result_winner_person_id: UUID | None = None
    result_winner_person_name: str | None = None
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


class CivicGeometryFeatureProperties(BaseModel):
    id: UUID
    name: str
    division_type: str
    state: str
    district_number: str | None = None
    boundary_year: int | None = None


class CivicGeometryFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: dict[str, Any]
    properties: CivicGeometryFeatureProperties


class CivicGeometryFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[CivicGeometryFeature] = Field(default_factory=list)


class ElectionContestSummary(BaseModel):
    contest_id: UUID
    office_id: UUID
    name: str
    election_type: ElectionTypeLiteral
    office_name: str
    office_level: OfficeLevelLiteral
    state: str | None = None
    jurisdiction_id: UUID | None = None
    electoral_division_id: UUID | None = None
    candidate_count: int
    result_status: str | None = None
    winning_person_name: str | None = None


class ElectionDateAggregateResponse(BaseModel):
    date: date
    total_contests: int
    total_candidacies: int
    contests: list[ElectionContestSummary] = Field(default_factory=list)


class UpcomingElectionTimelineEntry(BaseModel):
    date: date
    contests: list[ElectionContestSummary] = Field(default_factory=list)
