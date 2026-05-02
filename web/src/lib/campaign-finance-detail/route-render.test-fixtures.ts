import type {
  CampaignFinanceTransactionResponse,
  CandidateFundraisingSummary,
  CommitteeFilingBreakdown,
  CommitteeFundraisingSummary,
  IndependentExpenditureResponse,
  IndependentExpenditureSummary
} from "./contract";

export const COMMITTEE_ID = "33333333-3333-4333-8333-333333333333";
export const CANDIDATE_ID = "44444444-4444-4444-8444-444444444444";
export const PERSON_ID = "11111111-1111-4111-8111-111111111111";
export const ORG_ID = "22222222-2222-4222-8222-222222222222";

export function asDeferredValue<T>(value: T): Promise<T> {
  return value as unknown as Promise<T>;
}

export const CANDIDATE_CANONICAL_DATA = {
  routeKind: "canonical-detail" as const,
  detail: {
    id: CANDIDATE_ID,
    fec_candidate_id: "H0NC01001",
    name: "Pat Candidate",
    slug: "pat-candidate",
    slug_is_unique: true,
    person_id: null,
    party: "DEM",
    office: "H",
    state: "NC",
    district: "01",
    incumbent_challenge: "I",
    principal_committee_id: COMMITTEE_ID,
    sources: []
  },
  summary: asDeferredValue<CandidateFundraisingSummary>({
    candidate_id: CANDIDATE_ID,
    candidate_name: "Pat Candidate",
    total_raised: "250.00",
    total_spent: "80.00",
    net: "170.00",
    transaction_count: 5,
    committees: [
      {
        committee_id: COMMITTEE_ID,
        committee_name: "Citizens for Civibus",
        slug: "citizens-for-civibus",
        slug_is_unique: true,
        total_raised: "250.00",
        total_spent: "80.00",
        net: "170.00",
        transaction_count: 5,
        jurisdiction: "federal/fec",
        data_through: "2026-03-19T00:00:00Z",
        cash_receipts_total: "210.00",
        in_kind_receipts_total: "30.00",
        loan_receipts_total: "10.00",
        contribution_receipts_total: "220.00",
        top_donors: [],
        top_vendors: [],
        spend_categories: null
      }
    ]
  }),
  ieTransactions: asDeferredValue<IndependentExpenditureResponse[]>([]),
  ieSummary: asDeferredValue<IndependentExpenditureSummary | null>(null)
};

export const CANDIDATE_EMPTY_CANONICAL_DATA = {
  ...CANDIDATE_CANONICAL_DATA,
  detail: {
    ...CANDIDATE_CANONICAL_DATA.detail,
    id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    name: "Candidate Empty",
    slug: "candidate-empty",
    slug_is_unique: false,
    person_id: null,
    principal_committee_id: null
  },
  summary: asDeferredValue<CandidateFundraisingSummary>({
    candidate_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    candidate_name: "Candidate Empty",
    total_raised: "0.00",
    total_spent: "0.00",
    net: "0.00",
    transaction_count: 0,
    committees: []
  }),
  ieTransactions: asDeferredValue<IndependentExpenditureResponse[]>([]),
  ieSummary: asDeferredValue<IndependentExpenditureSummary | null>(null)
};

export const CANDIDATE_CANONICAL_DATA_WITH_L10_DEVIATION = {
  ...CANDIDATE_CANONICAL_DATA,
  keelL10Reference: {
    totalRaised: "1000.00",
    sourceLabel: "NC SBOE anchor",
    methodologyHref: "/methodology",
    deviationThresholdRatio: 0.2
  }
};

export const CANDIDATE_CANONICAL_DATA_WITH_IE = {
  ...CANDIDATE_CANONICAL_DATA,
  ieTransactions: asDeferredValue<IndependentExpenditureResponse[]>([
    {
      id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      filing_id: null,
      committee_id: COMMITTEE_ID,
      committee_name: "Independent Expenditure Committee",
      amount: 5000,
      transaction_date: "2026-03-19",
      purpose: "Broadcast ad",
      dissemination_date: "2026-03-20",
      aggregate_amount: 5000,
      support_oppose: "S" as const
    }
  ]),
  ieSummary: asDeferredValue<IndependentExpenditureSummary>({
    candidate_id: CANDIDATE_ID,
    support_total: "10000.00",
    oppose_total: "2500.00",
    support_count: 2,
    oppose_count: 1,
    top_spenders: [
      {
        committee_id: COMMITTEE_ID,
        committee_name: "Independent Expenditure Committee",
        support_oppose: "S" as const,
        total_amount: "7000.00",
        transaction_count: 2
      }
    ]
  })
};

export const SAMPLE_TRANSACTION = {
  id: "55555555-5555-4555-8555-555555555555",
  filing_id: "66666666-6666-4666-8666-666666666666",
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

export const COMMITTEE_CANONICAL_DATA = {
  routeKind: "canonical-detail" as const,
  detail: {
    id: COMMITTEE_ID,
    fec_committee_id: "C12345678",
    name: "Citizens for Civibus",
    slug: "citizens-for-civibus",
    slug_is_unique: true,
    organization_id: null,
    committee_type: "Q",
    committee_designation: "P",
    party: "DEM",
    state: "NC",
    city: "Raleigh",
    zip_code: "27601",
    treasurer_name: "Jordan Treasurer",
    sources: []
  },
  transactions: asDeferredValue<CampaignFinanceTransactionResponse[]>([]),
  summary: asDeferredValue<CommitteeFundraisingSummary>({
    committee_id: COMMITTEE_ID,
    committee_name: "Citizens for Civibus",
    total_raised: "125.00",
    total_spent: "40.00",
    net: "85.00",
    transaction_count: 1,
    jurisdiction: "federal/fec",
    data_through: "2026-03-19T00:00:00Z",
    cash_receipts_total: "100.00",
    in_kind_receipts_total: "15.00",
    loan_receipts_total: "10.00",
    contribution_receipts_total: "105.00",
    top_donors: [],
    top_vendors: [],
    spend_categories: null
  }),
  filingBreakdown: asDeferredValue<CommitteeFilingBreakdown>({
    committee_id: COMMITTEE_ID,
    committee_name: "Citizens for Civibus",
    filings: []
  })
};
