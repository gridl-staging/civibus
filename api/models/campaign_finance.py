
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from api.models._validation import validate_inclusive_bounds
from api.models.provenance import SourceInfo


class CommitteeResponse(BaseModel):
    id: UUID
    fec_committee_id: str
    name: str
    slug: str
    slug_is_unique: bool
    organization_id: UUID | None = None
    committee_type: str | None = None
    committee_designation: str | None = None
    party: str | None = None
    state: str | None = None
    city: str | None = None
    zip_code: str | None = None
    treasurer_name: str | None = None
    sources: list[SourceInfo]


class CandidateResponse(BaseModel):
    id: UUID
    fec_candidate_id: str
    name: str
    slug: str
    slug_is_unique: bool
    person_id: UUID | None = None
    party: str | None = None
    office: str
    state: str | None = None
    district: str | None = None
    incumbent_challenge: str | None = None
    principal_committee_id: UUID | None = None
    sources: list[SourceInfo]


class FilingResponse(BaseModel):

    id: UUID
    filing_fec_id: str
    committee_id: UUID
    candidate_id: UUID | None = None
    election_id: UUID | None = None
    report_type: str | None = None
    amendment_indicator: str
    filing_name: str | None = None
    coverage_start_date: date | None = None
    coverage_end_date: date | None = None
    due_date: date | None = None
    receipt_date: date | None = None
    accepted_date: date | None = None
    is_amended: bool
    amended_from_filing_id: UUID | None = None
    days_late: int | None = None
    sources: list[SourceInfo]


class TransactionResponse(BaseModel):

    id: UUID
    filing_id: UUID
    committee_id: UUID
    transaction_type: str
    transaction_identifier: str | None = None
    transaction_date: date | None = None
    amount: float
    contributor_name_raw: str | None = None
    contributor_employer: str | None = None
    contributor_occupation: str | None = None
    contributor_city: str | None = None
    contributor_state: str | None = None
    contributor_zip: str | None = None
    contributor_person_id: UUID | None = None
    contributor_organization_id: UUID | None = None
    contributor_address_id: UUID | None = None
    recipient_candidate_id: UUID | None = None
    recipient_committee_id: UUID | None = None
    memo_text: str | None = None
    is_memo: bool
    amendment_indicator: str
    date_is_reliable: bool
    support_oppose: str | None = None
    dissemination_date: date | None = None
    aggregate_amount: float | None = None


class IndependentExpenditureResponse(BaseModel):
    id: UUID
    filing_id: UUID | None = None
    committee_id: UUID
    committee_name: str
    amount: float
    transaction_date: date | None = None
    purpose: str | None = None
    dissemination_date: date | None = None
    aggregate_amount: float | None = None
    support_oppose: Literal["S", "O"]


class TopSpenderEntry(BaseModel):
    committee_id: UUID
    committee_name: str
    support_oppose: Literal["S", "O"]
    total_amount: Decimal
    transaction_count: int


class IndependentExpenditureSummary(BaseModel):
    candidate_id: UUID
    support_total: Decimal
    oppose_total: Decimal
    support_count: int
    oppose_count: int
    top_spenders: list[TopSpenderEntry]


class TransactionListParams(BaseModel):

    committee_id: UUID | None = None
    jurisdiction: str | None = None
    min_date: date | None = None
    max_date: date | None = None
    min_amount: float | None = None
    max_amount: float | None = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_range_bounds(self) -> TransactionListParams:
        validate_inclusive_bounds(
            self.min_date,
            self.max_date,
            min_name="min_date",
            max_name="max_date",
        )
        validate_inclusive_bounds(
            self.min_amount,
            self.max_amount,
            min_name="min_amount",
            max_name="max_amount",
        )
        return self


class CandidateListItem(BaseModel):
    id: UUID
    fec_candidate_id: str
    name: str
    person_id: UUID | None = None
    party: str | None = None
    office: str
    state: str | None = None
    district: str | None = None
    slug: str
    slug_is_unique: bool


class CommitteeListItem(BaseModel):
    id: UUID
    fec_committee_id: str
    name: str
    committee_type: str | None = None
    party: str | None = None
    state: str | None = None
    slug: str
    slug_is_unique: bool


class CandidateListParams(BaseModel):
    state: str | None = None
    office: str | None = None
    person_id: UUID | None = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class CommitteeListParams(BaseModel):
    state: str | None = None
    committee_type: str | None = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class CandidateListResponse(BaseModel):
    items: list[CandidateListItem]
    has_next: bool
    offset: int
    limit: int


class CommitteeListResponse(BaseModel):
    items: list[CommitteeListItem]
    has_next: bool
    offset: int
    limit: int


class RankedTransactionParty(BaseModel):
    name: str
    total_amount: Decimal
    transaction_count: int


class SpendCategorySummary(BaseModel):
    category: str
    total_amount: Decimal
    transaction_count: int


class CommitteeFundraisingSummary(BaseModel):
    committee_id: UUID
    committee_name: str
    total_raised: Decimal
    total_spent: Decimal
    net: Decimal
    transaction_count: int
    jurisdiction: str | None = None
    data_through: datetime | None = None
    cash_receipts_total: Decimal = Decimal("0.00")
    in_kind_receipts_total: Decimal = Decimal("0.00")
    loan_receipts_total: Decimal = Decimal("0.00")
    contribution_receipts_total: Decimal = Decimal("0.00")
    top_donors: list[RankedTransactionParty] = Field(default_factory=list)
    top_vendors: list[RankedTransactionParty] = Field(default_factory=list)
    spend_categories: list[SpendCategorySummary] | None = None


class CandidateFundraisingSummary(BaseModel):
    candidate_id: UUID
    candidate_name: str
    total_raised: Decimal
    total_spent: Decimal
    net: Decimal
    transaction_count: int
    committees: list[CommitteeFundraisingSummary]


StateCoverageTier = Literal[
    "launch-support candidate",
    "implemented but unproven",
    "freshness-limited",
    "deferred/blocked",
]
StateSupportStatus = Literal["supported", "warning", "unsupported"]


class StateCandidateTopEntry(BaseModel):
    candidate_id: UUID
    candidate_name: str
    total_raised: Decimal


class StateCommitteeTopEntry(BaseModel):
    committee_id: UUID
    committee_name: str
    total_raised: Decimal


class StateIndependentExpenditureTopSpender(BaseModel):
    committee_id: UUID
    committee_name: str
    total_amount: Decimal


class StateSummaryItem(BaseModel):
    state_code: str
    total_raised: Decimal
    total_spent: Decimal
    net: Decimal
    committee_count: int
    transaction_count: int
    federal_candidate_count: int
    ie_support_total: Decimal | None = None
    ie_oppose_total: Decimal | None = None
    ie_support_count: int | None = None
    ie_oppose_count: int | None = None
    coverage_tier: StateCoverageTier | None = None
    support_status: StateSupportStatus
    supported: bool
    warning_text: str | None = None
    data_through: datetime | None = None


class StateDetailResponse(StateSummaryItem):
    sources: list[SourceInfo] = Field(default_factory=list)
    top_candidates: list[StateCandidateTopEntry]
    top_committees: list[StateCommitteeTopEntry]
    top_ie_spenders: list[StateIndependentExpenditureTopSpender]


class CountySummaryRecipientCommittee(BaseModel):
    committee_id: UUID
    committee_name: str
    donor_total_cents: int
    transaction_count: int


class CountySummaryLinkedCandidate(BaseModel):
    candidate_id: UUID
    candidate_name: str
    donor_total_cents: int
    transaction_count: int


class CountyCampaignFinanceSummary(BaseModel):
    state: str
    county_slug: str
    donor_total_cents: int
    transaction_count: int
    top_recipient_committees: list[CountySummaryRecipientCommittee]
    top_linked_candidates: list[CountySummaryLinkedCandidate]
    sources: list[SourceInfo]


class FilingPeriodSummary(BaseModel):
    filing_id: UUID
    filing_fec_id: str
    filing_name: str | None = None
    report_type: str | None = None
    amendment_indicator: str
    coverage_start_date: date | None = None
    coverage_end_date: date | None = None
    receipt_date: date | None = None
    total_raised: Decimal
    total_spent: Decimal
    net: Decimal
    transaction_count: int
    cash_on_hand: Decimal | None = None
    row_id: str


class CommitteeFilingBreakdown(BaseModel):
    committee_id: UUID
    committee_name: str
    filings: list[FilingPeriodSummary]
