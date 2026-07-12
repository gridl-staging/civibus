
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
    # Stage 5: candidates linked to this committee via active
    # ``cf.candidate_committee_link`` rows, reusing the shared candidate list DTO
    # so Stage 6 can route by ``person_id`` / slug without a second contract.
    linked_candidates: list[CandidateListItem] = Field(default_factory=list)


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


class DonorSearchRecipient(BaseModel):
    person_id: UUID
    candidate_id: UUID
    fec_candidate_id: str
    candidate_name: str
    committee_id: UUID
    fec_committee_id: str
    committee_name: str
    total_amount: Decimal
    transaction_count: int


class DonorSearchResult(BaseModel):
    id: UUID
    contributor_name: str
    contributor_employer: str | None = None
    contributor_occupation: str | None = None
    contributor_city: str | None = None
    contributor_state: str | None = None
    normalized_zip5: str | None = None
    total_amount: Decimal
    transaction_count: int
    latest_transaction_date: date | None = None
    recipients: list[DonorSearchRecipient] = Field(default_factory=list)
    sources: list[SourceInfo] = Field(default_factory=list)


class DonorSearchResponse(BaseModel):
    query: str
    by: Literal["name", "employer", "zip"]
    limit: int
    offset: int
    results: list[DonorSearchResult] = Field(default_factory=list)


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
    # Stage 5: rows above the aggregate-summary outlier ceiling are excluded from
    # ``support_total`` / ``oppose_total`` / ``support_count`` / ``oppose_count`` /
    # ``top_spenders`` and counted here. The raw IE list endpoint stays source-faithful.
    excluded_outlier_count: int = 0


class CommitteeIndependentExpenditureTarget(BaseModel):
    candidate_id: UUID
    fec_candidate_id: str
    candidate_name: str
    person_id: UUID | None = None
    party: str | None = None
    office: str
    state: str | None = None
    district: str | None = None
    slug: str
    slug_is_unique: bool
    support_total: Decimal
    oppose_total: Decimal
    transaction_count: int
    sources: list[SourceInfo] = Field(default_factory=list)


class CommitteeIndependentExpenditureActivity(BaseModel):
    committee_id: UUID
    support_total: Decimal
    oppose_total: Decimal
    ie_transaction_count: int
    excluded_outlier_count: int = 0
    targets: list[CommitteeIndependentExpenditureTarget] = Field(default_factory=list)


class ContributionInsightsMonthlyTotal(BaseModel):
    month: str
    total_amount: Decimal
    transaction_count: int


class ContributionInsightsItemizedBucket(BaseModel):
    label: str
    min_amount: Decimal
    max_amount: Decimal | None = None
    total_amount: Decimal
    transaction_count: int


class ContributionInsightsDollarsBucket(BaseModel):
    label: str
    total_amount: Decimal
    source: Literal["transactions", "committee_summary"]


class ContributionInsightsGeographyRow(BaseModel):
    label: str
    total_amount: Decimal
    transaction_count: int


class ContributionInsightsDistrictShare(BaseModel):
    in_district_amount: Decimal | None = None
    out_of_district_amount: Decimal | None = None
    unknown_district_amount: Decimal | None = None
    share: Decimal | None = None
    available: bool


class ContributionInsightsGeography(BaseModel):
    by_state: list[ContributionInsightsGeographyRow] = Field(default_factory=list)
    by_district: list[ContributionInsightsGeographyRow] = Field(default_factory=list)
    district_share: ContributionInsightsDistrictShare


class ContributionInsightsMetadata(BaseModel):
    coverage_start_date: date
    coverage_end_date: date | None = None
    cycles_included: list[int] = Field(default_factory=list)
    committee_count: int
    approximate_geography: bool
    excluded_geography: str | None = None
    caveats: list[str] = Field(default_factory=list)


class ContributionInsightsSmallDollarShare(BaseModel):
    small_dollar_amount: Decimal | None = None
    total_contribution_amount: Decimal | None = None
    share: Decimal | None = None
    available: bool


ContributionInsightsCycleTotalsSource = Literal["committee_summary", "itemized_transactions", "mixed_sources", "none"]


class ContributionInsightsCycleTotal(BaseModel):
    cycle: int
    itemized_individual_contribution_amount: Decimal
    itemized_transaction_count: int
    unitemized_individual_contribution_amount: Decimal
    total_individual_contribution_amount: Decimal
    source: ContributionInsightsCycleTotalsSource


class ContributionInsightsCareerTotals(BaseModel):
    itemized_individual_contribution_amount: Decimal = Decimal("0.00")
    itemized_transaction_count: int = 0
    unitemized_individual_contribution_amount: Decimal = Decimal("0.00")
    total_individual_contribution_amount: Decimal = Decimal("0.00")
    source: ContributionInsightsCycleTotalsSource = "none"


class PersonContributionInsights(BaseModel):
    person_id: UUID
    has_data: bool
    metadata: ContributionInsightsMetadata
    monthly_totals: list[ContributionInsightsMonthlyTotal] = Field(default_factory=list)
    itemized_size_buckets: list[ContributionInsightsItemizedBucket] = Field(default_factory=list)
    dollars_by_size: list[ContributionInsightsDollarsBucket] = Field(default_factory=list)
    cycle_totals: list[ContributionInsightsCycleTotal] = Field(default_factory=list)
    career_totals: ContributionInsightsCareerTotals = Field(default_factory=ContributionInsightsCareerTotals)
    geography: ContributionInsightsGeography
    small_dollar_share: ContributionInsightsSmallDollarShare


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
    city: str | None = None
    state: str | None = None


class PersonTopEmployerRow(BaseModel):
    employer: str
    total_amount: Decimal
    transaction_count: int


class SpendCategorySummary(BaseModel):
    category: str
    total_amount: Decimal
    transaction_count: int


class CommitteeCycleSummary(BaseModel):
    """One row of official FEC per-cycle committee totals from ``cf.committee_summary``."""

    cycle: int
    total_receipts: Decimal
    total_disbursements: Decimal
    cash_on_hand: Decimal | None = None
    coverage_start_date: date | None = None
    coverage_end_date: date | None = None


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
    # Stage 5: same computed count as ``transaction_count``, exposed under a name
    # that reads truthfully next to the official ``cf.committee_summary`` totals.
    itemized_transaction_count: int = 0
    # Stage 5: per-cycle official rows from ``cf.committee_summary`` in ascending
    # cycle order. Empty when no supported-cycle official rows are loaded.
    cycle_summaries: list[CommitteeCycleSummary] = Field(default_factory=list)
    # Stage 5: which source produced total_raised/total_spent/net.
    # "fec_committee_summary" = summed official supported-cycle rows;
    # "derived" = qualifying-transaction sums.
    summary_source: Literal["fec_committee_summary", "derived"] = "derived"


class CandidateFundraisingSummary(BaseModel):

    candidate_id: UUID
    candidate_name: str
    total_raised: Decimal
    total_spent: Decimal
    net: Decimal
    transaction_count: int
    committees: list[CommitteeFundraisingSummary]
    # Stage 3: official FEC weball cash-on-hand. None when no official totals are loaded.
    cash_on_hand: Decimal | None = None
    # Stage 3: which source produced total_raised/total_spent/net.
    # "fec_weball" = candidate row's official totals; "derived" = sum of linked committee transactions.
    summary_source: Literal["fec_weball", "derived"]
    # Stage 5: same computed count as ``transaction_count`` — the underlying
    # itemized-transaction sum across linked committees. Neither the weball nor the
    # committee-summary feed carries a transaction count, so this stays identical
    # to ``transaction_count`` under a name that stays truthful next to official totals.
    itemized_transaction_count: int = 0


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
    excluded_outlier_count: int = 0


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


# ``CommitteeResponse.linked_candidates`` uses ``CandidateListItem``, which is
# defined below the class body under ``from __future__ import annotations``. The
# explicit rebuild resolves the forward reference deterministically.
CommitteeResponse.model_rebuild()


# ---------------------------------------------------------------------------
# Public API (`/public/v1`) contract models
#
# These are the frozen, authless public-API DTOs. They are deliberately a
# separate owner from the internal ``CongressMemberSummary`` (api/models/civics.py)
# and ``CandidateFundraisingSummary`` above: the public contract must be able to
# evolve independently of the internal query models, so it does not import or
# subclass them. Populated by ``api/routes/public_federal.py`` — no new SQL.
# ---------------------------------------------------------------------------


class PublicFederalOfficial(BaseModel):
    """Public directory row for a current federal official.

    Field-for-field mirror of ``fetch_current_federal_members`` output plus the
    route-built ``person_detail_path`` (the query does not return it).
    """

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


class PublicMemberMoneySummary(BaseModel):
    """Public money + independent-expenditure summary for one federal member.

    ``has_fec_money`` is False when the member has no linked ``cf.candidate`` row;
    in that case the money and IE fields carry zeroes and ``candidate_id`` /
    ``summary_source`` are None.
    """

    person_id: UUID
    person_name: str
    has_fec_money: bool
    candidate_id: UUID | None = None
    total_raised: Decimal
    total_spent: Decimal
    net: Decimal
    cash_on_hand: Decimal | None = None
    summary_source: str | None = None
    ie_support_total: Decimal
    ie_oppose_total: Decimal
    ie_support_count: int
    ie_oppose_count: int
    sources: list[SourceInfo]
