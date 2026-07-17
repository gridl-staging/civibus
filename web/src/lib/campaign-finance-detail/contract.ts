/** Route builders and response contracts for campaign-finance pages. */
import { encodeRoutePathSegment, type SourceInfo } from "$lib/entity-detail/contract";

export const COMMITTEE_TRANSACTIONS_LIMIT = 25;
export const CANDIDATES_PAGE_PATH = "/candidates";
export const COMMITTEES_PAGE_PATH = "/committees";
export type SerializedMoney = string;
type ListQueryParamValue = string | number | undefined;
type CampaignFinanceListPathParams = Record<string, ListQueryParamValue>;
type ListRequestParam = string | number;
export type SelectedCycleRequest = {
  cycle?: ListRequestParam;
};
export type SelectedCycleMetadata = {
  selected_cycle: number;
  coverage_start_date: string;
  coverage_end_date: string;
  available_cycles: number[];
};
type SlugRoutableItem = {
  id: string;
  slug: string;
  slug_is_unique: boolean;
};

/** Committee detail payload returned by the campaign-finance API. */
export type CommitteeDetailResponse = {
  id: string;
  fec_committee_id: string;
  name: string;
  slug: string;
  slug_is_unique: boolean;
  organization_id: string | null;
  committee_type: string | null;
  committee_designation: string | null;
  party: string | null;
  state: string | null;
  city: string | null;
  zip_code: string | null;
  treasurer_name: string | null;
  sources: SourceInfo[];
  linked_candidates: CandidateListItem[];
};

export type CandidateDetailResponse = {
  id: string;
  fec_candidate_id: string;
  name: string;
  slug: string;
  slug_is_unique: boolean;
  person_id: string | null;
  party: string | null;
  office: string;
  state: string | null;
  district: string | null;
  incumbent_challenge: string | null;
  principal_committee_id: string | null;
  sources: SourceInfo[];
};

export type CandidateListItem = {
  id: string;
  fec_candidate_id: string;
  name: string;
  person_id?: string | null;
  party: string | null;
  office: string;
  state: string | null;
  district: string | null;
  slug: string;
  slug_is_unique: boolean;
};

export type CommitteeListItem = {
  id: string;
  fec_committee_id: string;
  name: string;
  committee_type: string | null;
  party: string | null;
  state: string | null;
  slug: string;
  slug_is_unique: boolean;
};

export type CandidateListResponse = {
  items: CandidateListItem[];
  has_next: boolean;
  offset: number;
  limit: number;
};

export type CommitteeListResponse = {
  items: CommitteeListItem[];
  has_next: boolean;
  offset: number;
  limit: number;
};

export type CandidateSlugMatchResponse = CandidateListItem[];
export type CommitteeSlugMatchResponse = CommitteeListItem[];

export type CandidateListRequest = {
  state?: string;
  office?: string;
  person_id?: string;
  limit?: ListRequestParam;
  offset?: ListRequestParam;
};

export type CommitteeListRequest = {
  state?: string;
  committee_type?: string;
  limit?: ListRequestParam;
  offset?: ListRequestParam;
};

/** Canonical transaction row used by committee detail record tables. */
export type CampaignFinanceTransactionResponse = {
  id: string;
  filing_id: string;
  committee_id: string;
  transaction_type: string;
  transaction_identifier: string | null;
  transaction_date: string | null;
  amount: number;
  contributor_name_raw: string | null;
  contributor_employer: string | null;
  contributor_occupation: string | null;
  contributor_city: string | null;
  contributor_state: string | null;
  contributor_zip: string | null;
  contributor_person_id: string | null;
  contributor_organization_id: string | null;
  contributor_address_id: string | null;
  recipient_candidate_id: string | null;
  recipient_committee_id: string | null;
  memo_text: string | null;
  is_memo: boolean;
  amendment_indicator: string;
  date_is_reliable: boolean;
  support_oppose?: "S" | "O" | null;
  dissemination_date?: string | null;
  aggregate_amount?: number | null;
};

export type IndependentExpenditureResponse = {
  id: string;
  filing_id: string | null;
  committee_id: string;
  committee_name: string;
  amount: number;
  transaction_date: string | null;
  purpose: string | null;
  dissemination_date: string | null;
  aggregate_amount: number | null;
  support_oppose: "S" | "O";
};

export type TopSpenderEntry = {
  committee_id: string;
  committee_name: string;
  support_oppose: "S" | "O";
  total_amount: SerializedMoney;
  transaction_count: number;
};

export type IndependentExpenditureSummary = SelectedCycleMetadata & {
  candidate_id: string;
  support_total: SerializedMoney;
  oppose_total: SerializedMoney;
  support_count: number;
  oppose_count: number;
  top_spenders: TopSpenderEntry[];
  excluded_outlier_count: number;
};

/**
 */
export type CommitteeIndependentExpenditureTarget = {
  candidate_id: string;
  fec_candidate_id: string;
  candidate_name: string;
  person_id: string | null;
  party: string | null;
  office: string;
  state: string | null;
  district: string | null;
  slug: string;
  slug_is_unique: boolean;
  support_total: SerializedMoney;
  oppose_total: SerializedMoney;
  transaction_count: number;
  sources: SourceInfo[];
};

export type CommitteeIndependentExpenditureActivity = {
  committee_id: string;
  support_total: SerializedMoney;
  oppose_total: SerializedMoney;
  ie_transaction_count: number;
  excluded_outlier_count: number;
  targets: CommitteeIndependentExpenditureTarget[];
};

export type CommitteeCycleSummary = {
  cycle: number;
  total_receipts: SerializedMoney;
  total_disbursements: SerializedMoney;
  cash_on_hand: SerializedMoney | null;
  coverage_start_date: string | null;
  coverage_end_date: string | null;
};

export type ReceiptSourceComponent = {
  label: string;
  total_amount: SerializedMoney;
  source: "fec_committee_summary" | "none";
};

/**
 */
export type CommitteeFundraisingSummary = SelectedCycleMetadata & {
  committee_id: string;
  committee_name: string;
  slug?: string;
  slug_is_unique?: boolean;
  total_raised: SerializedMoney;
  total_spent: SerializedMoney;
  net: SerializedMoney;
  transaction_count: number;
  jurisdiction: string | null;
  data_through: string | null;
  cash_receipts_total: SerializedMoney;
  in_kind_receipts_total: SerializedMoney;
  loan_receipts_total: SerializedMoney;
  contribution_receipts_total: SerializedMoney;
  top_donors: RankedTransactionParty[];
  top_vendors: RankedTransactionParty[];
  spend_categories: SpendCategorySummary[] | null;
  itemized_transaction_count: number;
  cycle_summaries: CommitteeCycleSummary[];
  summary_source: "fec_committee_summary" | "derived";
  receipt_source_composition: ReceiptSourceComponent[];
  selected_cycle_coverage_complete: boolean;
  can_render_share: boolean;
  receipt_source_caveats: string[];
  debts_owed_by_committee?: SerializedMoney | null;
};

export type RankedTransactionParty = {
  name: string;
  total_amount: SerializedMoney;
  transaction_count: number;
};

export type SpendCategorySummary = {
  category: string;
  total_amount: SerializedMoney;
  transaction_count: number;
};

/**
 */
export type FilingPeriodSummary = {
  filing_id: string;
  filing_fec_id: string;
  filing_name: string | null;
  report_type: string | null;
  amendment_indicator: string;
  coverage_start_date: string | null;
  coverage_end_date: string | null;
  receipt_date: string | null;
  total_raised: SerializedMoney;
  total_spent: SerializedMoney;
  net: SerializedMoney;
  transaction_count: number;
  cash_on_hand: SerializedMoney | null;
  row_id: string;
};

export type CommitteeFilingBreakdown = {
  committee_id: string;
  committee_name: string;
  filings: FilingPeriodSummary[];
};

export type ContributionInsightsMonthlyTotal = {
  month: string;
  total_amount: SerializedMoney;
  transaction_count: number;
};

export type ContributionInsightsItemizedBucket = {
  label: string;
  min_amount: SerializedMoney;
  max_amount: SerializedMoney | null;
  total_amount: SerializedMoney;
  transaction_count: number;
};

export type ContributionInsightsDollarsBucket = {
  label: string;
  total_amount: SerializedMoney;
  source: "transactions" | "committee_summary";
};

export type ContributionInsightsGeographyRow = {
  label: string;
  total_amount: SerializedMoney;
  transaction_count: number;
};

export type ContributionInsightsDistrictShare = {
  in_district_amount: SerializedMoney | null;
  out_of_district_amount: SerializedMoney | null;
  unknown_district_amount: SerializedMoney | null;
  share: SerializedMoney | null;
  available: boolean;
};

export type ContributionInsightsGeography = {
  by_state: ContributionInsightsGeographyRow[];
  by_district: ContributionInsightsGeographyRow[];
  district_share: ContributionInsightsDistrictShare;
  geography_mode: "district" | "statewide" | "state_bars_only" | "excluded";
  classified_amount: SerializedMoney;
  classified_transaction_count: number;
  unknown_amount: SerializedMoney;
  unknown_transaction_count: number;
};

export type ContributionInsightsMetadata = SelectedCycleMetadata & {
  cycles_included: number[];
  committee_count: number;
  approximate_geography: boolean;
  excluded_geography: string | null;
  caveats: string[];
};

export type ContributionInsightsSmallDollarShare = {
  small_dollar_amount: SerializedMoney | null;
  total_contribution_amount: SerializedMoney | null;
  share: SerializedMoney | null;
  available: boolean;
};

export type ContributionInsightsTotalsSource =
  | "committee_summary"
  | "itemized_transactions"
  | "mixed_sources"
  | "none";

export type ContributionInsightsCycleTotal = {
  cycle: number;
  itemized_individual_contribution_amount: SerializedMoney;
  itemized_transaction_count: number;
  unitemized_individual_contribution_amount: SerializedMoney;
  total_individual_contribution_amount: SerializedMoney;
  source: ContributionInsightsTotalsSource;
};

export type ContributionInsightsCareerTotals = {
  itemized_individual_contribution_amount: SerializedMoney;
  itemized_transaction_count: number;
  unitemized_individual_contribution_amount: SerializedMoney;
  total_individual_contribution_amount: SerializedMoney;
  source: ContributionInsightsTotalsSource;
};

export type PersonContributionInsights = {
  person_id: string;
  has_data: boolean;
  metadata: ContributionInsightsMetadata;
  monthly_totals: ContributionInsightsMonthlyTotal[];
  itemized_size_buckets: ContributionInsightsItemizedBucket[];
  dollars_by_size: ContributionInsightsDollarsBucket[];
  cycle_totals: ContributionInsightsCycleTotal[];
  career_totals: ContributionInsightsCareerTotals;
  geography: ContributionInsightsGeography;
  small_dollar_share: ContributionInsightsSmallDollarShare;
};

export type PersonTopEmployerRow = {
  employer: string;
  total_amount: SerializedMoney;
  transaction_count: number;
};

function buildCampaignFinancePath(resource: string, id: string, suffix = ""): string {
  return `/v1/${resource}/${encodeRoutePathSegment(id)}${suffix}`;
}

function buildPathWithQuery(basePath: string, params: CampaignFinanceListPathParams): string {
  const searchParams = new URLSearchParams();

  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") {
      searchParams.set(key, String(value));
    }
  }

  const queryString = searchParams.toString();
  return queryString === "" ? basePath : `${basePath}?${queryString}`;
}

function buildCampaignFinanceCollectionPath(
  resource: "candidates" | "committees",
  params: CampaignFinanceListPathParams
): string {
  return buildPathWithQuery(`/v1/${resource}`, params);
}

function buildCampaignFinanceBySlugPath(resource: "candidates" | "committees", slug: string): string {
  return `/v1/${resource}/by-slug/${encodeRoutePathSegment(slug)}`;
}

function buildSlugAwareHref(routeSegment: "candidate" | "committee", item: SlugRoutableItem): string {
  const routeId = item.slug_is_unique ? item.slug : item.id;
  return `/${routeSegment}/${encodeRoutePathSegment(routeId)}`;
}

export function buildCommitteeDetailPath(committeeId: string): string {
  return buildCampaignFinancePath("committees", committeeId);
}

export function buildCommitteeListPath(params: CommitteeListRequest): string {
  return buildCampaignFinanceCollectionPath("committees", params);
}

export function buildCommitteesBySlugPath(slug: string): string {
  return buildCampaignFinanceBySlugPath("committees", slug);
}

export function buildCommitteeHref(item: SlugRoutableItem): string {
  return buildSlugAwareHref("committee", item);
}

function buildSelectedCyclePath(basePath: string, request: SelectedCycleRequest = {}): string {
  return buildPathWithQuery(basePath, { cycle: request.cycle });
}

export function buildCommitteeSummaryPath(
  committeeId: string,
  request: SelectedCycleRequest = {}
): string {
  return buildSelectedCyclePath(buildCampaignFinancePath("committees", committeeId, "/summary"), request);
}

export function buildCommitteeFilingBreakdownPath(committeeId: string): string {
  return buildCampaignFinancePath("committees", committeeId, "/filings/summary");
}

export function buildFilingDetailPath(filingId: string): string {
  return buildCampaignFinancePath("filings", filingId);
}

export function buildCommitteeIndependentExpendituresMadePath(committeeId: string): string {
  return buildCampaignFinancePath("committees", committeeId, "/independent-expenditures-made");
}

/**
 */
export type CandidateFundraisingSummary = SelectedCycleMetadata & {
  candidate_id: string;
  candidate_name: string;
  total_raised: SerializedMoney;
  total_spent: SerializedMoney;
  net: SerializedMoney;
  transaction_count: number;
  committees: CommitteeFundraisingSummary[];
  // Stage 3: official FEC weball cash-on-hand; null when no weball totals are loaded.
  cash_on_hand: SerializedMoney | null;
  net_self_funding: SerializedMoney | null;
  debts_owed_by_committee?: SerializedMoney | null;
  // Stage 3: which backend source produced total_raised/total_spent/net.
  summary_source: "fec_weball" | "derived";
  itemized_transaction_count: number;
  receipt_source_composition: ReceiptSourceComponent[];
  selected_cycle_coverage_complete: boolean;
  can_render_share: boolean;
  receipt_source_caveats: string[];
};

export type CountySummaryRecipientCommittee = {
  committee_id: string;
  committee_name: string;
  donor_total_cents: number;
  transaction_count: number;
};

export type CountySummaryLinkedCandidate = {
  candidate_id: string;
  candidate_name: string;
  donor_total_cents: number;
  transaction_count: number;
};

export type CountyCampaignFinanceSummaryResponse = {
  state: string;
  county_slug: string;
  donor_total_cents: number;
  transaction_count: number;
  top_recipient_committees: CountySummaryRecipientCommittee[];
  top_linked_candidates: CountySummaryLinkedCandidate[];
  sources: SourceInfo[];
};

export function buildCandidateDetailPath(candidateId: string): string {
  return buildCampaignFinancePath("candidates", candidateId);
}

export function buildCandidateListPath(params: CandidateListRequest): string {
  return buildCampaignFinanceCollectionPath("candidates", params);
}

export function buildCandidatesPagePath(params: CandidateListRequest): string {
  return buildPathWithQuery(CANDIDATES_PAGE_PATH, params);
}

export function buildCommitteesPagePath(params: CommitteeListRequest): string {
  return buildPathWithQuery(COMMITTEES_PAGE_PATH, params);
}

export function buildCandidatesBySlugPath(slug: string): string {
  return buildCampaignFinanceBySlugPath("candidates", slug);
}

export function buildCandidateHref(item: SlugRoutableItem): string {
  return buildSlugAwareHref("candidate", item);
}

export function buildCandidateSummaryPath(
  candidateId: string,
  request: SelectedCycleRequest = {}
): string {
  return buildSelectedCyclePath(buildCampaignFinancePath("candidates", candidateId, "/summary"), request);
}

export function buildPersonContributionInsightsPath(
  personId: string,
  request: SelectedCycleRequest = {}
): string {
  return buildSelectedCyclePath(buildCampaignFinancePath("person", personId, "/contribution-insights"), request);
}

export function buildPersonTopDonorsPath(personId: string, request: SelectedCycleRequest = {}): string {
  return buildSelectedCyclePath(buildCampaignFinancePath("person", personId, "/top-donors"), request);
}

export function buildPersonTopEmployersPath(
  personId: string,
  request: SelectedCycleRequest = {}
): string {
  return buildSelectedCyclePath(buildCampaignFinancePath("person", personId, "/top-employers"), request);
}

export function buildCountyCampaignFinanceSummaryPath(state: string, countySlug: string): string {
  return `/v1/counties/${encodeRoutePathSegment(state.toLowerCase())}/${encodeRoutePathSegment(
    countySlug.toLowerCase()
  )}/campaign-finance-summary`;
}

export function buildCandidateIndependentExpendituresPath(
  candidateId: string,
  request: SelectedCycleRequest = {}
): string {
  return buildSelectedCyclePath(
    buildCampaignFinancePath("candidates", candidateId, "/independent-expenditures"),
    request
  );
}

export function buildCandidateIndependentExpendituresSummaryPath(
  candidateId: string,
  request: SelectedCycleRequest = {}
): string {
  return buildSelectedCyclePath(
    buildCampaignFinancePath("candidates", candidateId, "/independent-expenditures/summary"),
    request
  );
}

export function buildCommitteeTransactionsPath(
  committeeId: string,
  request: SelectedCycleRequest = {}
): string {
  return buildPathWithQuery("/v1/transactions", {
    committee_id: committeeId,
    limit: COMMITTEE_TRANSACTIONS_LIMIT,
    cycle: request.cycle
  });
}
