/** Route builders and response contracts for campaign-finance pages. */
import { encodeRoutePathSegment, type SourceInfo } from "$lib/entity-detail/contract";

export const COMMITTEE_TRANSACTIONS_LIMIT = 25;
export const CANDIDATES_PAGE_PATH = "/candidates";
export const COMMITTEES_PAGE_PATH = "/committees";
export type SerializedMoney = string;
type ListQueryParamValue = string | number | undefined;
type CampaignFinanceListPathParams = Record<string, ListQueryParamValue>;
type ListRequestParam = string | number;
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

export type IndependentExpenditureSummary = {
  candidate_id: string;
  support_total: SerializedMoney;
  oppose_total: SerializedMoney;
  support_count: number;
  oppose_count: number;
  top_spenders: TopSpenderEntry[];
};

export type CommitteeFundraisingSummary = {
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

export function buildCommitteeSummaryPath(committeeId: string): string {
  return buildCampaignFinancePath("committees", committeeId, "/summary");
}

export function buildCommitteeFilingBreakdownPath(committeeId: string): string {
  return buildCampaignFinancePath("committees", committeeId, "/filings/summary");
}

export type CandidateFundraisingSummary = {
  candidate_id: string;
  candidate_name: string;
  total_raised: SerializedMoney;
  total_spent: SerializedMoney;
  net: SerializedMoney;
  transaction_count: number;
  committees: CommitteeFundraisingSummary[];
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

export function buildCandidateSummaryPath(candidateId: string): string {
  return buildCampaignFinancePath("candidates", candidateId, "/summary");
}

export function buildCountyCampaignFinanceSummaryPath(state: string, countySlug: string): string {
  return `/v1/counties/${encodeRoutePathSegment(state.toLowerCase())}/${encodeRoutePathSegment(
    countySlug.toLowerCase()
  )}/campaign-finance-summary`;
}

export function buildCandidateIndependentExpendituresPath(candidateId: string): string {
  return buildCampaignFinancePath("candidates", candidateId, "/independent-expenditures");
}

export function buildCandidateIndependentExpendituresSummaryPath(candidateId: string): string {
  return buildCampaignFinancePath("candidates", candidateId, "/independent-expenditures/summary");
}

export function buildCommitteeTransactionsPath(committeeId: string): string {
  const searchParams = new URLSearchParams();
  searchParams.set("committee_id", committeeId);
  searchParams.set("limit", String(COMMITTEE_TRANSACTIONS_LIMIT));
  return `/v1/transactions?${searchParams.toString()}`;
}
