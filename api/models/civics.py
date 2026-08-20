"""
Stub summary for jun04_3pm_4_congress_directory_ui/civibus_dev/api/models/civics.py.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from api.models.campaign_finance import (
    CandidateFundraisingCoverage,
    CandidateMoneyCoverage,
    CandidateOutOfCycleOfficialTotal,
)
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


class ContestCandidateMoneyRow(BaseModel):
    """One candidate's money scoreboard line within a contest.

    Money fields are optional on purpose. A candidacy with no matching
    ``cf.candidate`` row has UNKNOWN money, not zero money, and the product's
    own screen specs forbid rendering unknown coverage as ``$0.00``. Typing
    these as ``Decimal`` would force a zero at serialization and reintroduce
    exactly that defect at the source.
    """

    candidacy_id: UUID
    person_id: UUID
    person_name: str
    party: str | None = None
    status: str | None = None
    incumbent_challenge: str | None = None
    fec_candidate_id: str | None = None
    candidate_id: UUID | None = None
    candidate_name: str | None = None
    candidate_slug: str | None = None
    # Routing facts, not display facts: the client uses the same rule as the
    # candidate detail page to decide between a slug URL and a UUID URL.
    candidate_slug_is_unique: bool = False
    candidate_identity_is_safe: bool = False
    # False when no cf.candidate row matched; the client must render the
    # unknown-coverage copy rather than any figure.
    has_fec_money: bool
    total_raised: Decimal | None = None
    total_spent: Decimal | None = None
    net: Decimal | None = None
    cash_on_hand: Decimal | None = None
    summary_source: str | None = None
    fundraising_coverage: CandidateFundraisingCoverage | None = None
    out_of_cycle_official_total: CandidateOutOfCycleOfficialTotal | None = None
    # Optional for the same reason as the fundraising fields above. "No Schedule
    # E was loaded for this cycle" and "no outside money was spent on this
    # candidate" are different claims; typing these as ``Decimal`` forced a zero
    # at serialization and published the second whenever the first was true.
    # ``ie_coverage`` is present only when the state is not ``populated``,
    # mirroring ``fundraising_coverage`` above.
    ie_support_total: Decimal | None = None
    ie_oppose_total: Decimal | None = None
    ie_support_count: int | None = None
    ie_oppose_count: int | None = None
    ie_coverage: CandidateMoneyCoverage | None = None


class ContestCandidateMoneyResponse(BaseModel):
    """Race-level money scoreboard for one contest, in a single response.

    Replaces a per-candidacy HTTP fan-out (4N+1 backend calls from the web
    layer) with one call backed by three batched queries, so cost is flat in
    the number of candidates.
    """

    contest_id: UUID
    selected_cycle: int
    candidate_count: int
    # Race-level rollups over the rows below, for the answer-first summary line
    # race_detail.md specifies. Candidates with unknown money contribute nothing
    # rather than a zero, so these are sums of what is actually known.
    #
    # ``None`` when NO candidate in the race has loaded fundraising: summing an
    # empty set of known values yields no total, and a headline reading
    # "Civibus has loaded $0.00 raised" would state a measurement nobody took.
    # A race where every loaded candidate genuinely raised nothing still totals
    # ``Decimal("0.00")`` — that zero is measured and must keep its figure.
    total_raised: Decimal | None = None
    # ``None`` when no candidate in the race has loaded outside spending: there
    # is nothing to total, and a race headline reading "$0.00 supporting" would
    # be the loudest false statement on the page.
    total_ie_support: Decimal | None = None
    total_ie_oppose: Decimal | None = None
    # True when at least one candidacy has no loaded money; the summary line
    # must qualify itself rather than present a partial total as complete.
    has_unknown_candidate_money: bool
    # The same qualifier for the outside-spending half. Separate from the
    # fundraising flag because the two datasets load independently: Schedule A
    # can be current while Schedule E for the same cycle was never fetched.
    has_unknown_candidate_ie: bool = False
    rows: list[ContestCandidateMoneyRow] = Field(default_factory=list)


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


class CongressMemberSummary(BaseModel):
    person_id: UUID
    person_name: str
    officeholding_id: UUID
    office_id: UUID
    office_name: str
    chamber: str
    state: str | None = None
    district: str | None = None
    district_or_class: str | None = None
    party: str | None = None
    portrait_source_image_url: str | None = None
    person_detail_path: str


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
    """One contest row in the `/election/[date]` index and the upcoming timeline.

    Fed by `_ELECTION_CONTESTS_BY_DATE_SQL` and `_UPCOMING_ELECTION_CONTESTS_SQL`,
    which must stay column-identical. The `electoral_division_*` and
    `district_number` fields are the seat context the race index groups and
    labels by; `electoral_division_id` alone is a UUID no reader can interpret.

    `result_status` and `winning_person_name` used to live here and were removed
    on 2026-08-17: neither query ever selected them, so they serialized as `null`
    on every row of every response and no caller could ever read a real value.
    Contest results are exposed by `ContestDetailResponse.result_winner_*`, which
    is populated from the candidacy status.
    """

    contest_id: UUID
    office_id: UUID
    name: str
    election_type: ElectionTypeLiteral
    office_name: str
    office_level: OfficeLevelLiteral
    state: str | None = None
    jurisdiction_id: UUID | None = None
    electoral_division_id: UUID | None = None
    electoral_division_type: str | None = None
    electoral_division_state: str | None = None
    district_number: str | None = None
    candidate_count: int


class ElectionDateAggregateResponse(BaseModel):
    date: date
    total_contests: int
    total_candidacies: int
    contests: list[ElectionContestSummary] = Field(default_factory=list)


class UpcomingElectionTimelineEntry(BaseModel):
    date: date
    contests: list[ElectionContestSummary] = Field(default_factory=list)
