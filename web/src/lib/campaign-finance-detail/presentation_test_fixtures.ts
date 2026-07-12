import type { CandidateDetailBundle, CommitteeDetailBundle } from "$lib/server/api/campaign-finance-detail";

export const COMMITTEE_ID = "33333333-3333-4333-8333-333333333333";
export const CANDIDATE_ID = "44444444-4444-4444-8444-444444444444";
export const PERSON_ID = "11111111-1111-4111-8111-111111111111";
export const ORG_ID = "22222222-2222-4222-8222-222222222222";
export const FILING_ID = "66666666-6666-4666-8666-666666666666";

type DetailSource = {
  domain: string;
  jurisdiction: string | null;
  data_source_name: string;
  data_source_url: string;
  source_record_key: string | null;
  record_url: string | null;
  pull_date: string;
};

export const DEFAULT_COMMITTEE_DETAIL = {
  id: COMMITTEE_ID,
  fec_committee_id: "C12345678",
  name: "Committee One",
  slug: "committee-one",
  slug_is_unique: true,
  organization_id: null,
  committee_type: null,
  committee_designation: null,
  party: null,
  state: null,
  city: null,
  zip_code: null,
  treasurer_name: null,
  sources: [] as DetailSource[],
  linked_candidates: [] as import("$lib/campaign-finance-detail/contract").CandidateListItem[]
};

export const DEFAULT_SUMMARY = {
  committee_id: COMMITTEE_ID,
  committee_name: "Committee One",
  total_raised: "125.00",
  total_spent: "50.00",
  net: "75.00",
  transaction_count: 1,
  jurisdiction: "federal/fec",
  data_through: "2026-03-19T00:00:00Z",
  cash_receipts_total: "100.00",
  in_kind_receipts_total: "15.00",
  loan_receipts_total: "10.00",
  contribution_receipts_total: "125.00",
  top_donors: [{ name: "Donor One", total_amount: "80.00", transaction_count: 2 }],
  top_vendors: [{ name: "Vendor One", total_amount: "50.00", transaction_count: 1 }],
  spend_categories: [{ category: "media", total_amount: "25.00", transaction_count: 1 }],
  itemized_transaction_count: 1,
  cycle_summaries: [],
  summary_source: "derived" as const
};

export const DEFAULT_FILING_PERIOD = {
  filing_id: FILING_ID,
  filing_fec_id: "FEC-100",
  filing_name: "Q1 filing",
  report_type: "Q1",
  amendment_indicator: "N",
  coverage_start_date: "2026-01-01",
  coverage_end_date: "2026-03-31",
  receipt_date: "2026-04-10",
  total_raised: "125.00",
  total_spent: "50.00",
  net: "75.00",
  transaction_count: 1,
  cash_on_hand: "75.00",
  row_id: `${FILING_ID}:N`
};

export const DEFAULT_FILING_BREAKDOWN = {
  committee_id: COMMITTEE_ID,
  committee_name: "Committee One",
  filings: [DEFAULT_FILING_PERIOD]
};

export const DEFAULT_COMMITTEE_IE_ACTIVITY = {
  committee_id: COMMITTEE_ID,
  support_total: "0.00",
  oppose_total: "0.00",
  ie_transaction_count: 0,
  excluded_outlier_count: 0,
  targets: []
};

export const DEFAULT_TRANSACTION = {
  id: "55555555-5555-4555-8555-555555555555",
  filing_id: FILING_ID,
  committee_id: COMMITTEE_ID,
  transaction_type: "contribution",
  transaction_identifier: "TX-1",
  transaction_date: "2026-03-19",
  amount: 125,
  contributor_name_raw: "Donor One",
  contributor_employer: null,
  contributor_occupation: null,
  contributor_city: null,
  contributor_state: null,
  contributor_zip: null,
  contributor_person_id: PERSON_ID,
  contributor_organization_id: ORG_ID,
  contributor_address_id: null,
  recipient_candidate_id: CANDIDATE_ID,
  recipient_committee_id: COMMITTEE_ID,
  memo_text: null,
  is_memo: false,
  amendment_indicator: "N",
  date_is_reliable: true
};

export const DEFAULT_CANDIDATE_DETAIL = {
  id: CANDIDATE_ID,
  fec_candidate_id: "H0NC01001",
  name: "Candidate One",
  slug: "candidate-one",
  slug_is_unique: true,
  person_id: PERSON_ID,
  party: "DEM",
  office: "H",
  state: "NC",
  district: "01",
  incumbent_challenge: "I",
  principal_committee_id: COMMITTEE_ID,
  sources: [] as DetailSource[]
};

export const DEFAULT_CANDIDATE_SUMMARY = {
  candidate_id: CANDIDATE_ID,
  candidate_name: "Candidate One",
  total_raised: "0.00",
  total_spent: "0.00",
  net: "0.00",
  transaction_count: 0,
  committees: [],
  cash_on_hand: null,
  summary_source: "derived" as const,
  itemized_transaction_count: 0
};

export function buildCandidateBundle(): CandidateDetailBundle {
  return {
    detail: DEFAULT_CANDIDATE_DETAIL,
    summary: Promise.resolve(DEFAULT_CANDIDATE_SUMMARY),
    ieTransactions: Promise.resolve([]),
    ieSummary: Promise.resolve(null)
  };
}

export function buildCommitteeBundle(): CommitteeDetailBundle {
  return {
    detail: DEFAULT_COMMITTEE_DETAIL,
    transactions: Promise.resolve([]),
    summary: Promise.resolve(DEFAULT_SUMMARY),
    filingBreakdown: Promise.resolve(DEFAULT_FILING_BREAKDOWN),
    independentExpendituresMade: Promise.resolve(DEFAULT_COMMITTEE_IE_ACTIVITY)
  };
}
