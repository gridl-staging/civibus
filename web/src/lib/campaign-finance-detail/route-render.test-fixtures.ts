import type {
  CampaignFinanceTransactionResponse,
  CandidateFundraisingSummary,
  CommitteeFilingBreakdown,
  CommitteeFundraisingSummary,
  CommitteeIndependentExpenditureActivity,
  FilingPeriodSummary,
  IndependentExpenditureResponse,
  IndependentExpenditureSummary
} from "./contract";

export const COMMITTEE_ID = "33333333-3333-4333-8333-333333333333";
export const CANDIDATE_ID = "44444444-4444-4444-8444-444444444444";
export const PERSON_ID = "11111111-1111-4111-8111-111111111111";
export const ORG_ID = "22222222-2222-4222-8222-222222222222";
export const DEFAULT_SELECTED_CYCLE_FIELDS = {
  selected_cycle: 2026,
  coverage_start_date: "2025-01-01",
  coverage_end_date: "2026-12-31",
  available_cycles: [2022, 2024, 2026]
};
const DEFAULT_RECEIPT_SOURCE_FIELDS = {
  receipt_source_composition: [],
  selected_cycle_coverage_complete: false,
  can_render_share: false,
  receipt_source_caveats: []
};
const POPULATED_CANDIDATE_MONEY_COVERAGE = {
  activity_state: "populated" as const,
  completeness: "complete" as const,
  basis: "qualifying_transactions" as const
};
const NOT_LOADED_CANDIDATE_MONEY_COVERAGE = {
  activity_state: "not_loaded" as const,
  completeness: "unknown" as const,
  basis: "no_authoritative_load_evidence" as const
};

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
    identity_is_safe: true,
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
    ...DEFAULT_SELECTED_CYCLE_FIELDS,
    ...DEFAULT_RECEIPT_SOURCE_FIELDS,
    candidate_id: CANDIDATE_ID,
    candidate_name: "Pat Candidate",
    total_raised: "250.00",
    total_spent: "80.00",
    net: "170.00",
    transaction_count: 5,
    committees: [
      {
        ...DEFAULT_SELECTED_CYCLE_FIELDS,
        ...DEFAULT_RECEIPT_SOURCE_FIELDS,
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
        spend_categories: null,
        itemized_transaction_count: 5,
        cycle_summaries: [],
        summary_source: "derived"
      }
    ],
    cash_on_hand: null,
    net_self_funding: null,
    summary_source: "derived",
    itemized_transaction_count: 5,
    coverage: POPULATED_CANDIDATE_MONEY_COVERAGE
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
    identity_is_safe: true,
    person_id: null,
    principal_committee_id: null
  },
  summary: asDeferredValue<CandidateFundraisingSummary>({
    ...DEFAULT_SELECTED_CYCLE_FIELDS,
    ...DEFAULT_RECEIPT_SOURCE_FIELDS,
    candidate_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    candidate_name: "Candidate Empty",
    total_raised: "0.00",
    total_spent: "0.00",
    net: "0.00",
    transaction_count: 0,
    committees: [],
    cash_on_hand: null,
    net_self_funding: null,
    summary_source: "derived",
    itemized_transaction_count: 0,
    coverage: NOT_LOADED_CANDIDATE_MONEY_COVERAGE
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
    ...DEFAULT_SELECTED_CYCLE_FIELDS,
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
    ],
    excluded_outlier_count: 0,
    coverage: {
      activity_state: "populated" as const,
      completeness: "complete" as const,
      basis: "fec_schedule_e_transactions" as const
    }
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

/**
 */
export function buildRouteRenderFilingRow(
  sequence: number,
  coverageEndDate: string | null
): FilingPeriodSummary {
  const paddedSequence = String(sequence).padStart(3, "0");

  return {
    filing_id: `filing-${paddedSequence}`,
    filing_fec_id: `FEC-${paddedSequence}`,
    filing_name: `Filing ${paddedSequence}`,
    report_type: "Q",
    amendment_indicator: "N",
    coverage_start_date: coverageEndDate === null ? null : `${coverageEndDate.slice(0, 8)}01`,
    coverage_end_date: coverageEndDate,
    receipt_date: coverageEndDate,
    total_raised: `${sequence * 100}.00`,
    total_spent: `${sequence * 40}.00`,
    net: `${sequence * 60}.00`,
    transaction_count: sequence,
    cash_on_hand: `${sequence * 70}.00`,
    row_id: `filing-${paddedSequence}:N`
  };
}

function routeRenderCoverageEndDate(sequence: number): string {
  const year = 2021 + Math.floor((sequence - 1) / 12);
  const month = String(((sequence - 1) % 12) + 1).padStart(2, "0");
  return `${year}-${month}-28`;
}

function buildUnorderedRouteRenderFilings(count: number): FilingPeriodSummary[] {
  const orderedRows = Array.from({ length: count }, (_, index) =>
    buildRouteRenderFilingRow(index + 1, routeRenderCoverageEndDate(index + 1))
  );

  return Array.from({ length: count }, (_, index) => orderedRows[(index * 37) % count]);
}

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
    sources: [],
    linked_candidates: []
  },
  transactions: asDeferredValue<CampaignFinanceTransactionResponse[]>([]),
  summary: asDeferredValue<CommitteeFundraisingSummary>({
    ...DEFAULT_SELECTED_CYCLE_FIELDS,
    ...DEFAULT_RECEIPT_SOURCE_FIELDS,
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
    spend_categories: null,
    itemized_transaction_count: 1,
    cycle_summaries: [],
    summary_source: "derived"
  }),
  filingBreakdown: {
    committee_id: COMMITTEE_ID,
    committee_name: "Citizens for Civibus",
    filings: []
  },
  independentExpendituresMade: asDeferredValue<CommitteeIndependentExpenditureActivity>({
    committee_id: COMMITTEE_ID,
    support_total: "0.00",
    oppose_total: "0.00",
    ie_transaction_count: 0,
    excluded_outlier_count: 0,
    targets: []
  })
};

export const COMMITTEE_CANONICAL_DATA_WITH_PAGINATED_FILINGS = {
  ...COMMITTEE_CANONICAL_DATA,
  filingBreakdown: {
    committee_id: COMMITTEE_ID,
    committee_name: "Citizens for Civibus",
    total_filings: 220706,
    store_limit: 200,
    has_next: true,
    offset: 0,
    limit: 200,
    filings: buildUnorderedRouteRenderFilings(60)
  }
};

export const COMMITTEE_CANONICAL_DATA_WITH_IE = {
  ...COMMITTEE_CANONICAL_DATA,
  independentExpendituresMade: asDeferredValue<CommitteeIndependentExpenditureActivity>({
    committee_id: COMMITTEE_ID,
    support_total: "1700.00",
    oppose_total: "250.00",
    ie_transaction_count: 4,
    excluded_outlier_count: 1,
    targets: [
      {
        candidate_id: CANDIDATE_ID,
        fec_candidate_id: "H0NC01001",
        candidate_name: "Pat Candidate",
        person_id: PERSON_ID,
        party: "DEM",
        office: "H",
        state: "NC",
        district: "01",
        slug: "pat-candidate",
        slug_is_unique: true,
        identity_is_safe: true,
        support_total: "1500.00",
        oppose_total: "250.00",
        transaction_count: 3,
        sources: [
          {
            domain: "campaign_finance",
            jurisdiction: "federal/fec",
            data_source_name: "FEC Schedule E",
            data_source_url: "https://www.fec.gov",
            source_record_key: "schedule-e-source",
            record_url: "https://www.fec.gov/data/independent-expenditures/",
            pull_date: "2026-07-08T00:00:00Z"
          }
        ]
      },
      {
        candidate_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        fec_candidate_id: "H0NC01002",
        candidate_name: "Lower Target",
        person_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        party: "REP",
        office: "H",
        state: "NC",
        district: "02",
        slug: "lower-target",
        slug_is_unique: true,
        identity_is_safe: true,
        support_total: "200.00",
        oppose_total: "0.00",
        transaction_count: 1,
        sources: []
      }
    ]
  })
};
