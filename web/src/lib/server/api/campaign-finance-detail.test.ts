import { ApiResponseError } from "$lib/server/api/client";
import { describe, expect, it, vi } from "vitest";
import {
  COMMITTEE_TRANSACTIONS_LIMIT,
  buildCandidateDetailPath,
  buildCandidateIndependentExpendituresPath,
  buildCandidateIndependentExpendituresSummaryPath,
  buildCandidateListPath,
  buildCandidateSummaryPath,
  buildCandidatesBySlugPath,
  buildCountyCampaignFinanceSummaryPath,
  buildCommitteeDetailPath,
  buildCommitteeFilingBreakdownPath,
  buildCommitteeIndependentExpendituresMadePath,
  buildCommitteeListPath,
  buildCommitteeSummaryPath,
  buildCommitteeTransactionsPath,
  buildCommitteesBySlugPath,
  buildPersonContributionInsightsPath,
  buildPersonTopDonorsPath,
  buildPersonTopEmployersPath
} from "$lib/campaign-finance-detail/contract";
import {
  fetchCandidateDetail,
  fetchCandidateDetailBundle,
  fetchContestCandidateFinanceByPersonId,
  fetchCandidateList,
  fetchPersonCandidateFinanceSections,
  fetchPersonContributionInsights,
  fetchPersonTopDonors,
  fetchPersonTopEmployers,
  fetchCandidatesBySlug,
  fetchCandidateIndependentExpenditures,
  fetchCandidateIndependentExpendituresSummary,
  fetchCandidateSummary,
  fetchCountyCampaignFinanceSummary,
  fetchCommitteeTransactions,
  fetchCommitteeList,
  fetchCommitteesBySlug,
  fetchCommitteeDetailBundle,
  fetchCommitteeFilingBreakdown,
  fetchCommitteeIndependentExpendituresMade,
  fetchCommitteeSummary
} from "./campaign-finance-detail";
import type { ApiClient } from "./client";

const COMMITTEE_ID = "33333333-3333-4333-8333-333333333333";
const SECOND_COMMITTEE_ID = "99999999-9999-4999-8999-999999999999";
const CANDIDATE_ID = "44444444-4444-4444-8444-444444444444";
const PERSON_ID = "11111111-1111-4111-8111-111111111111";
const FILING_ID = "77777777-7777-4777-8777-777777777777";
const SELECTED_CYCLE_FIELDS = {
  selected_cycle: 2026,
  coverage_start_date: "2025-01-01",
  coverage_end_date: "2026-12-31",
  available_cycles: [2022, 2024, 2026]
};

const CANDIDATE_DETAIL = {
  id: CANDIDATE_ID,
  fec_candidate_id: "H0NC01001",
  name: "Candidate One",
  slug: "candidate-one",
  slug_is_unique: true,
  person_id: null,
  party: null,
  office: "H",
  state: null,
  district: null,
  incumbent_challenge: null,
  principal_committee_id: COMMITTEE_ID,
  sources: []
};

const COMMITTEE_SUMMARY = {
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
  summary_source: "derived" as const,
  ...SELECTED_CYCLE_FIELDS
};

const COMMITTEE_FILING_BREAKDOWN = {
  committee_id: COMMITTEE_ID,
  committee_name: "Committee One",
  filings: [
    {
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
    }
  ]
};

const COMMITTEE_IE_ACTIVITY = {
  committee_id: COMMITTEE_ID,
  support_total: "1500.00",
  oppose_total: "250.00",
  ie_transaction_count: 3,
  excluded_outlier_count: 1,
  targets: [
    {
      candidate_id: CANDIDATE_ID,
      fec_candidate_id: "H0NC01001",
      candidate_name: "Target Candidate",
      person_id: PERSON_ID,
      party: "DEM",
      office: "H",
      state: "NC",
      district: "01",
      slug: "target-candidate",
      slug_is_unique: true,
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
    }
  ]
};

const COUNTY_CAMPAIGN_FINANCE_SUMMARY = {
  state: "nc",
  county_slug: "wake",
  donor_total_cents: 12500,
  transaction_count: 2,
  top_recipient_committees: [
    {
      committee_id: COMMITTEE_ID,
      committee_name: "Committee One",
      donor_total_cents: 12500,
      transaction_count: 2
    }
  ],
  top_linked_candidates: [
    {
      candidate_id: CANDIDATE_ID,
      candidate_name: "Candidate One",
      donor_total_cents: 12500,
      transaction_count: 2
    }
  ],
  sources: [
    {
      domain: "campaign_finance",
      jurisdiction: "state/nc",
      data_source_name: "NC Board",
      data_source_url: "https://example.org/source",
      source_record_key: "county-wake-1",
      record_url: "https://example.org/record/county-wake-1",
      pull_date: "2026-04-20T12:00:00Z"
    }
  ]
};

const CANDIDATE_LIST_RESPONSE = {
  items: [
    {
      id: CANDIDATE_ID,
      fec_candidate_id: "H0NC01001",
      name: "Candidate One",
      person_id: PERSON_ID,
      party: "DEM",
      office: "H",
      state: "NC",
      district: "01",
      slug: "candidate-one",
      slug_is_unique: true
    }
  ],
  has_next: true,
  offset: 0,
  limit: 25
};

const PERSON_CONTRIBUTION_INSIGHTS = {
  person_id: PERSON_ID,
  has_data: true,
  metadata: {
    ...SELECTED_CYCLE_FIELDS,
    cycles_included: [2022, 2024, 2026],
    committee_count: 1,
    approximate_geography: false,
    excluded_geography: "Unitemized contributions are excluded from geography.",
    caveats: []
  },
  monthly_totals: [{ month: "2026-01", total_amount: "1234.56", transaction_count: 4 }],
  itemized_size_buckets: [
    {
      label: "$200 and under",
      min_amount: "0.01",
      max_amount: "200.00",
      total_amount: "250.00",
      transaction_count: 3
    }
  ],
  dollars_by_size: [
    {
      label: "Unitemized (<$200)",
      total_amount: "100.00",
      source: "committee_summary" as const
    }
  ],
  cycle_totals: [
    {
      cycle: 2026,
      itemized_individual_contribution_amount: "1234.56",
      itemized_transaction_count: 4,
      unitemized_individual_contribution_amount: "0.00",
      total_individual_contribution_amount: "1234.56",
      source: "itemized_transactions" as const
    }
  ],
  career_totals: {
    itemized_individual_contribution_amount: "1234.56",
    itemized_transaction_count: 4,
    unitemized_individual_contribution_amount: "0.00",
    total_individual_contribution_amount: "1234.56",
    source: "itemized_transactions" as const
  },
  geography: {
    by_state: [{ label: "NC", total_amount: "900.00", transaction_count: 3 }],
    by_district: [],
    district_share: {
      in_district_amount: null,
      out_of_district_amount: null,
      unknown_district_amount: null,
      share: null,
      available: false
    }
  },
  small_dollar_share: {
    small_dollar_amount: "350.00",
    total_contribution_amount: "1000.00",
    share: "0.3500",
    available: true
  }
};

const PERSON_TOP_DONORS = [
  { name: "Top Person Donor", total_amount: "500.00", transaction_count: 2 },
  { name: "Second Person Donor", total_amount: "250.00", transaction_count: 1 }
];

const PERSON_TOP_EMPLOYERS = [
  { employer: "ACME CORP", total_amount: "500.00", transaction_count: 2 },
  { employer: "STATE UNIVERSITY", total_amount: "250.00", transaction_count: 1 }
];

const COMMITTEE_LIST_RESPONSE = {
  items: [
    {
      id: COMMITTEE_ID,
      fec_committee_id: "C12345678",
      name: "Committee One",
      committee_type: "P",
      party: "DEM",
      state: "NC",
      slug: "committee-one",
      slug_is_unique: true
    }
  ],
  has_next: false,
  offset: 0,
  limit: 50
};

const CANDIDATE_SLUG_MATCHES = [
  {
    id: CANDIDATE_ID,
    fec_candidate_id: "H0NC01001",
    name: "Candidate One",
    party: "DEM",
    office: "H",
    state: "NC",
    district: "01",
    slug: "candidate-one",
    slug_is_unique: false
  },
  {
    id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    fec_candidate_id: "H0NC01002",
    name: "Candidate One",
    party: "REP",
    office: "H",
    state: "NC",
    district: "02",
    slug: "candidate-one",
    slug_is_unique: false
  }
];

const COMMITTEE_SLUG_MATCHES = [
  {
    id: COMMITTEE_ID,
    fec_committee_id: "C12345678",
    name: "Committee One",
    committee_type: "P",
    party: "DEM",
    state: "NC",
    slug: "committee-one",
    slug_is_unique: false
  },
  {
    id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    fec_committee_id: "C87654321",
    name: "Committee One",
    committee_type: "Q",
    party: null,
    state: "GA",
    slug: "committee-one",
    slug_is_unique: false
  }
];

describe("campaign-finance detail api", () => {
  it("fetches committee detail bundle with detail, transactions, summary, filing breakdown, and IE activity", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === buildCommitteeDetailPath(COMMITTEE_ID)) {
        return {
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
          sources: [],
          linked_candidates: []
        };
      }

      if (path === buildCommitteeTransactionsPath(COMMITTEE_ID)) {
        return [
          {
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
            contributor_person_id: null,
            contributor_organization_id: null,
            contributor_address_id: null,
            recipient_candidate_id: null,
            recipient_committee_id: null,
            memo_text: null,
            is_memo: false,
            amendment_indicator: "N",
            date_is_reliable: true
          }
        ];
      }

      if (path === buildCommitteeSummaryPath(COMMITTEE_ID)) {
        return COMMITTEE_SUMMARY;
      }

      if (path === buildCommitteeFilingBreakdownPath(COMMITTEE_ID)) {
        return COMMITTEE_FILING_BREAKDOWN;
      }

      if (path === buildCommitteeIndependentExpendituresMadePath(COMMITTEE_ID)) {
        return COMMITTEE_IE_ACTIVITY;
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const data = await fetchCommitteeDetailBundle(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { id: COMMITTEE_ID }
    );

    expect(data.detail.id).toBe(COMMITTEE_ID);

    expect(data.transactions).toBeInstanceOf(Promise);
    expect(data.summary).toBeInstanceOf(Promise);
    expect(data.filingBreakdown).toEqual(COMMITTEE_FILING_BREAKDOWN);
    expect(data.independentExpendituresMade).toBeInstanceOf(Promise);

    expect(await data.transactions).toHaveLength(1);
    expect(await data.summary).toEqual(COMMITTEE_SUMMARY);
    expect(await data.independentExpendituresMade).toEqual(COMMITTEE_IE_ACTIVITY);

    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      buildCommitteeDetailPath(COMMITTEE_ID),
      `/v1/transactions?committee_id=${COMMITTEE_ID}&limit=${COMMITTEE_TRANSACTIONS_LIMIT}`,
      buildCommitteeSummaryPath(COMMITTEE_ID),
      buildCommitteeFilingBreakdownPath(COMMITTEE_ID),
      buildCommitteeIndependentExpendituresMadePath(COMMITTEE_ID)
    ]);
  });

  it("fetches committee-made independent expenditures only from the committee IE endpoint", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === buildCommitteeIndependentExpendituresMadePath(COMMITTEE_ID)) {
        return COMMITTEE_IE_ACTIVITY;
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const activity = await fetchCommitteeIndependentExpendituresMade(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { id: COMMITTEE_ID }
    );

    expect(activity).toEqual(COMMITTEE_IE_ACTIVITY);
    expect(requestJson).toHaveBeenCalledTimes(1);
    expect(requestJson).toHaveBeenCalledWith(buildCommitteeIndependentExpendituresMadePath(COMMITTEE_ID));
  });

  it("fetches candidate detail without calling transactions", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === buildCandidateDetailPath(CANDIDATE_ID)) {
        return {
          id: CANDIDATE_ID,
          fec_candidate_id: "H0NC01001",
          name: "Candidate One",
          slug: "candidate-one",
          slug_is_unique: true,
          person_id: null,
          party: null,
          office: "H",
          state: null,
          district: null,
          incumbent_challenge: null,
          principal_committee_id: null,
          sources: []
        };
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const data = await fetchCandidateDetail(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { id: CANDIDATE_ID }
    );

    expect(data.id).toBe(CANDIDATE_ID);
    expect(requestJson).toHaveBeenCalledTimes(1);
    expect(requestJson).toHaveBeenCalledWith(buildCandidateDetailPath(CANDIDATE_ID));
  });

  it("fetches committee summary only from the summary endpoint", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === buildCommitteeSummaryPath(COMMITTEE_ID)) {
        return COMMITTEE_SUMMARY;
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const summary = await fetchCommitteeSummary(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { id: COMMITTEE_ID }
    );

    expect(summary).toEqual(COMMITTEE_SUMMARY);
    expect(requestJson).toHaveBeenCalledTimes(1);
    expect(requestJson).toHaveBeenCalledWith(buildCommitteeSummaryPath(COMMITTEE_ID));
  });

  it("fetches committee filing breakdown only from the filings summary endpoint", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === buildCommitteeFilingBreakdownPath(COMMITTEE_ID)) {
        return COMMITTEE_FILING_BREAKDOWN;
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const filingBreakdown = await fetchCommitteeFilingBreakdown(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { id: COMMITTEE_ID }
    );

    expect(filingBreakdown).toEqual(COMMITTEE_FILING_BREAKDOWN);
    expect(requestJson).toHaveBeenCalledTimes(1);
    expect(requestJson).toHaveBeenCalledWith(buildCommitteeFilingBreakdownPath(COMMITTEE_ID));
  });

  it("fetches candidate summary from the candidate summary endpoint", async () => {
    const candidateSummary = {
      candidate_id: CANDIDATE_ID,
      candidate_name: "Candidate One",
      total_raised: "250.00",
      total_spent: "100.00",
      net: "150.00",
      transaction_count: 5,
      committees: [COMMITTEE_SUMMARY],
      cash_on_hand: null,
      summary_source: "derived" as const,
      itemized_transaction_count: 5
    };

    const requestJson = vi.fn(async (path: string) => {
      if (path === buildCandidateSummaryPath(CANDIDATE_ID)) {
        return candidateSummary;
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const summary = await fetchCandidateSummary(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { id: CANDIDATE_ID }
    );

    expect(summary).toEqual(candidateSummary);
    expect(requestJson).toHaveBeenCalledTimes(1);
    expect(requestJson).toHaveBeenCalledWith(buildCandidateSummaryPath(CANDIDATE_ID));
  });

  it("fetches candidate summary with FEC weball cash_on_hand and summary_source pass-through", async () => {
    const weballSummary = {
      candidate_id: CANDIDATE_ID,
      candidate_name: "Weball Candidate",
      total_raised: "9000.00",
      total_spent: "3500.00",
      net: "5500.00",
      transaction_count: 0,
      committees: [],
      cash_on_hand: "5500.00",
      summary_source: "fec_weball" as const,
      itemized_transaction_count: 0
    };

    const requestJson = vi.fn(async (path: string) => {
      if (path === buildCandidateSummaryPath(CANDIDATE_ID)) {
        return weballSummary;
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const summary = await fetchCandidateSummary(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { id: CANDIDATE_ID }
    );

    // The fetcher must pass cash_on_hand and summary_source through without rewriting.
    expect(summary.cash_on_hand).toBe("5500.00");
    expect(summary.summary_source).toBe("fec_weball");
    expect(summary).toEqual(weballSummary);
  });

  it("fetches county campaign-finance summary from the county summary endpoint", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === buildCountyCampaignFinanceSummaryPath("NC", "wake")) {
        return COUNTY_CAMPAIGN_FINANCE_SUMMARY;
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const summary = await fetchCountyCampaignFinanceSummary(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { state: "NC", countySlug: "wake" }
    );

    expect(summary).toEqual(COUNTY_CAMPAIGN_FINANCE_SUMMARY);
    expect(requestJson).toHaveBeenCalledTimes(1);
    expect(requestJson).toHaveBeenCalledWith(buildCountyCampaignFinanceSummaryPath("NC", "wake"));
  });

  it("fetches person contribution insights from the person insights endpoint", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === buildPersonContributionInsightsPath(PERSON_ID)) {
        return PERSON_CONTRIBUTION_INSIGHTS;
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const insights = await fetchPersonContributionInsights(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { id: PERSON_ID }
    );

    expect(insights.monthly_totals[0].total_amount).toBe("1234.56");
    expect(insights.small_dollar_share.share).toBe("0.3500");
    expect(insights).toEqual(PERSON_CONTRIBUTION_INSIGHTS);
    expect(requestJson).toHaveBeenCalledTimes(1);
    expect(requestJson).toHaveBeenCalledWith(buildPersonContributionInsightsPath(PERSON_ID));
  });

  it("fetches person top donors from the person top-donors endpoint", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === buildPersonTopDonorsPath(PERSON_ID)) {
        return PERSON_TOP_DONORS;
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const donors = await fetchPersonTopDonors(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { id: PERSON_ID }
    );

    expect(donors).toEqual(PERSON_TOP_DONORS);
    expect(requestJson).toHaveBeenCalledTimes(1);
    expect(requestJson).toHaveBeenCalledWith(buildPersonTopDonorsPath(PERSON_ID));
  });

  it("fetches person top employers from the person top-employers endpoint", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === buildPersonTopEmployersPath(PERSON_ID)) {
        return PERSON_TOP_EMPLOYERS;
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const employers = await fetchPersonTopEmployers(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { id: PERSON_ID }
    );

    expect(employers).toEqual(PERSON_TOP_EMPLOYERS);
    expect(requestJson).toHaveBeenCalledTimes(1);
    expect(requestJson).toHaveBeenCalledWith(buildPersonTopEmployersPath(PERSON_ID));
  });

  it("fetches selected-cycle finance endpoints through exact cycle-scoped API paths", async () => {
    const candidateSummary = {
      candidate_id: CANDIDATE_ID,
      candidate_name: "Candidate One",
      total_raised: "250.00",
      total_spent: "100.00",
      net: "150.00",
      transaction_count: 5,
      committees: [COMMITTEE_SUMMARY],
      cash_on_hand: null,
      summary_source: "derived" as const,
      itemized_transaction_count: 5,
      selected_cycle: 2024,
      coverage_start_date: "2023-01-01",
      coverage_end_date: "2024-12-31",
      available_cycles: [2022, 2024, 2026]
    };
    const ieSummary = {
      candidate_id: CANDIDATE_ID,
      support_total: "0.00",
      oppose_total: "0.00",
      support_count: 0,
      oppose_count: 0,
      top_spenders: [],
      excluded_outlier_count: 0,
      selected_cycle: 2024,
      coverage_start_date: "2023-01-01",
      coverage_end_date: "2024-12-31",
      available_cycles: [2022, 2024, 2026]
    };
    const requestJson = vi.fn(async (path: string) => {
      if (path === buildPersonContributionInsightsPath(PERSON_ID, { cycle: 2024 })) {
        return {
          ...PERSON_CONTRIBUTION_INSIGHTS,
          metadata: {
            ...PERSON_CONTRIBUTION_INSIGHTS.metadata,
            selected_cycle: 2024,
            coverage_start_date: "2023-01-01",
            coverage_end_date: "2024-12-31"
          }
        };
      }
      if (path === buildPersonTopDonorsPath(PERSON_ID, { cycle: 2024 })) {
        return PERSON_TOP_DONORS;
      }
      if (path === buildPersonTopEmployersPath(PERSON_ID, { cycle: 2024 })) {
        return PERSON_TOP_EMPLOYERS;
      }
      if (path === buildCandidateSummaryPath(CANDIDATE_ID, { cycle: 2024 })) {
        return candidateSummary;
      }
      if (path === buildCommitteeSummaryPath(COMMITTEE_ID, { cycle: 2024 })) {
        return { ...COMMITTEE_SUMMARY, selected_cycle: 2024 };
      }
      if (path === buildCandidateIndependentExpendituresPath(CANDIDATE_ID, { cycle: 2024 })) {
        return [];
      }
      if (path === buildCandidateIndependentExpendituresSummaryPath(CANDIDATE_ID, { cycle: 2024 })) {
        return ieSummary;
      }
      if (path === buildCommitteeTransactionsPath(COMMITTEE_ID, { cycle: 2024 })) {
        return [];
      }

      throw new Error(`unexpected path: ${path}`);
    });
    const apiClient = { requestJson: requestJson as ApiClient["requestJson"] };

    await expect(fetchPersonContributionInsights(apiClient, { id: PERSON_ID, cycle: 2024 })).resolves.toMatchObject({
      metadata: { selected_cycle: 2024, coverage_start_date: "2023-01-01", coverage_end_date: "2024-12-31" }
    });
    await expect(fetchPersonTopDonors(apiClient, { id: PERSON_ID, cycle: 2024 })).resolves.toEqual(PERSON_TOP_DONORS);
    await expect(fetchPersonTopEmployers(apiClient, { id: PERSON_ID, cycle: 2024 })).resolves.toEqual(
      PERSON_TOP_EMPLOYERS
    );
    await expect(fetchCandidateSummary(apiClient, { id: CANDIDATE_ID, cycle: 2024 })).resolves.toEqual(
      candidateSummary
    );
    await expect(fetchCommitteeSummary(apiClient, { id: COMMITTEE_ID, cycle: 2024 })).resolves.toMatchObject({
      selected_cycle: 2024
    });
    await expect(fetchCandidateIndependentExpenditures(apiClient, { id: CANDIDATE_ID, cycle: 2024 })).resolves.toEqual(
      []
    );
    await expect(
      fetchCandidateIndependentExpendituresSummary(apiClient, { id: CANDIDATE_ID, cycle: 2024 })
    ).resolves.toEqual(ieSummary);
    await expect(fetchCommitteeTransactions(apiClient, { id: COMMITTEE_ID, cycle: 2024 })).resolves.toEqual([]);
    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      buildPersonContributionInsightsPath(PERSON_ID, { cycle: 2024 }),
      buildPersonTopDonorsPath(PERSON_ID, { cycle: 2024 }),
      buildPersonTopEmployersPath(PERSON_ID, { cycle: 2024 }),
      buildCandidateSummaryPath(CANDIDATE_ID, { cycle: 2024 }),
      buildCommitteeSummaryPath(COMMITTEE_ID, { cycle: 2024 }),
      buildCandidateIndependentExpendituresPath(CANDIDATE_ID, { cycle: 2024 }),
      buildCandidateIndependentExpendituresSummaryPath(CANDIDATE_ID, { cycle: 2024 }),
      buildCommitteeTransactionsPath(COMMITTEE_ID, { cycle: 2024 })
    ]);
  });

  it("fetches contest candidate finance with backend-owned selected-cycle facts and exact cycle paths", async () => {
    const candidateSummary = {
      candidate_id: CANDIDATE_ID,
      candidate_name: "Candidate One",
      total_raised: "250.00",
      total_spent: "100.00",
      net: "150.00",
      transaction_count: 5,
      committees: [],
      cash_on_hand: "75.00",
      summary_source: "fec_weball" as const,
      itemized_transaction_count: 5,
      selected_cycle: 2024,
      coverage_start_date: "2023-01-01",
      coverage_end_date: "2024-12-31",
      available_cycles: [2022, 2024, 2026]
    };
    const ieSummary = {
      candidate_id: CANDIDATE_ID,
      support_total: "10.00",
      oppose_total: "5.00",
      support_count: 1,
      oppose_count: 1,
      top_spenders: [],
      excluded_outlier_count: 0,
      selected_cycle: 2024,
      coverage_start_date: "2023-01-01",
      coverage_end_date: "2024-12-31",
      available_cycles: [2022, 2024, 2026]
    };
    const requestJson = vi.fn(async (path: string) => {
      if (path === `/v1/candidates?person_id=${PERSON_ID}&limit=10&offset=0`) {
        return CANDIDATE_LIST_RESPONSE;
      }
      if (path === buildCandidateDetailPath(CANDIDATE_ID)) {
        return { ...CANDIDATE_DETAIL, person_id: PERSON_ID, principal_committee_id: null };
      }
      if (path === buildCandidateSummaryPath(CANDIDATE_ID, { cycle: 2024 })) {
        return candidateSummary;
      }
      if (path === buildCandidateIndependentExpendituresPath(CANDIDATE_ID, { cycle: 2024 })) {
        return [];
      }
      if (path === buildCandidateIndependentExpendituresSummaryPath(CANDIDATE_ID, { cycle: 2024 })) {
        return ieSummary;
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const sections = await fetchContestCandidateFinanceByPersonId(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { candidacies: [{ personId: PERSON_ID }], cycle: 2024 }
    );

    expect(sections[PERSON_ID]).toMatchObject({
      personId: PERSON_ID,
      candidateHref: "/candidate/candidate-one",
      summary: {
        selected_cycle: 2024,
        coverage_start_date: "2023-01-01",
        coverage_end_date: "2024-12-31",
        total_raised: "250.00",
        total_spent: "100.00",
        cash_on_hand: "75.00"
      },
      ieSummary: {
        selected_cycle: 2024,
        coverage_end_date: "2024-12-31"
      },
      ieTransactions: []
    });
    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      `/v1/candidates?person_id=${PERSON_ID}&limit=10&offset=0`,
      buildCandidateDetailPath(CANDIDATE_ID),
      buildCandidateSummaryPath(CANDIDATE_ID, { cycle: 2024 }),
      buildCandidateIndependentExpendituresPath(CANDIDATE_ID, { cycle: 2024 }),
      buildCandidateIndependentExpendituresSummaryPath(CANDIDATE_ID, { cycle: 2024 })
    ]);
  });

  it("passes backend 422 responses through for cycle-scoped requests", async () => {
    const requestJson = vi
      .fn()
      .mockRejectedValue(new ApiResponseError(422, { detail: [{ loc: ["query", "cycle"], msg: "Unsupported cycle" }] }));

    await expect(
      fetchCandidateIndependentExpendituresSummary(
        { requestJson: requestJson as ApiClient["requestJson"] },
        { id: CANDIDATE_ID, cycle: 2025 }
      )
    ).rejects.toMatchObject({
      status: 422,
      body: { detail: [{ loc: ["query", "cycle"], msg: "Unsupported cycle" }] }
    });
    expect(requestJson).toHaveBeenCalledWith(
      buildCandidateIndependentExpendituresSummaryPath(CANDIDATE_ID, { cycle: 2025 })
    );
  });

  it("fetches candidate detail bundle with detail, summary, and IE data in parallel", async () => {
    const candidateSummary = {
      candidate_id: CANDIDATE_ID,
      candidate_name: "Candidate One",
      total_raised: "250.00",
      total_spent: "100.00",
      net: "150.00",
      transaction_count: 5,
      committees: [COMMITTEE_SUMMARY],
      cash_on_hand: null,
      summary_source: "derived" as const,
      itemized_transaction_count: 5
    };

    const ieTransactions = [
      {
        id: "88888888-8888-4888-8888-888888888888",
        filing_id: null,
        committee_id: COMMITTEE_ID,
        committee_name: "Outside PAC",
        amount: 5000,
        transaction_date: "2026-03-01",
        purpose: "TV ads",
        dissemination_date: "2026-03-02",
        aggregate_amount: 10000,
        support_oppose: "S" as const
      }
    ];

    const ieSummary = {
      candidate_id: CANDIDATE_ID,
      support_total: "5000.00",
      oppose_total: "0.00",
      support_count: 1,
      oppose_count: 0,
      top_spenders: [],
      excluded_outlier_count: 0
    };

    const requestJson = vi.fn(async (path: string) => {
      if (path === buildCandidateDetailPath(CANDIDATE_ID)) {
        return CANDIDATE_DETAIL;
      }

      if (path === buildCandidateSummaryPath(CANDIDATE_ID)) {
        return candidateSummary;
      }

      if (path === buildCandidateIndependentExpendituresPath(CANDIDATE_ID)) {
        return ieTransactions;
      }

      if (path === buildCandidateIndependentExpendituresSummaryPath(CANDIDATE_ID)) {
        return ieSummary;
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const bundle = await fetchCandidateDetailBundle(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { id: CANDIDATE_ID }
    );

    expect(bundle.detail).toEqual(CANDIDATE_DETAIL);

    expect(bundle.summary).toBeInstanceOf(Promise);
    expect(bundle.ieTransactions).toBeInstanceOf(Promise);
    expect(bundle.ieSummary).toBeInstanceOf(Promise);

    expect(await bundle.summary).toEqual(candidateSummary);
    expect(await bundle.ieTransactions).toEqual(ieTransactions);
    expect(await bundle.ieSummary).toEqual(ieSummary);

    expect(requestJson).toHaveBeenCalledTimes(4);
    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      buildCandidateDetailPath(CANDIDATE_ID),
      buildCandidateSummaryPath(CANDIDATE_ID),
      buildCandidateIndependentExpendituresPath(CANDIDATE_ID),
      buildCandidateIndependentExpendituresSummaryPath(CANDIDATE_ID)
    ]);
  });

  it("fetches candidate list using URLSearchParams serialization and preserves envelope payloads", async () => {
    const requestJson = vi.fn(async (path: string) => {
      void path;
      return CANDIDATE_LIST_RESPONSE;
    });

    const result = await fetchCandidateList(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { state: "NC", office: "H", limit: 25, offset: 50 }
    );

    expect(result).toEqual(CANDIDATE_LIST_RESPONSE);
    expect(requestJson).toHaveBeenCalledTimes(1);
    const calledPath = requestJson.mock.calls[0][0];
    const parsed = new URL(calledPath, "https://web.civibus.local");
    expect(parsed.pathname).toBe("/v1/candidates");
    expect(parsed.searchParams.get("state")).toBe("NC");
    expect(parsed.searchParams.get("office")).toBe("H");
    expect(parsed.searchParams.get("limit")).toBe("25");
    expect(parsed.searchParams.get("offset")).toBe("50");
    expect(calledPath).toBe(buildCandidateListPath({ state: "NC", office: "H", limit: 25, offset: 50 }));
  });

  it("serializes person_id candidate-list filtering for person detail finance linkage", async () => {
    const requestJson = vi.fn(async (path: string) => {
      void path;
      return CANDIDATE_LIST_RESPONSE;
    });

    const result = await fetchCandidateList(
      { requestJson: requestJson as ApiClient["requestJson"] },
      {
        person_id: "11111111-1111-4111-8111-111111111111",
        limit: 10,
        offset: 0
      }
    );

    expect(result).toEqual(CANDIDATE_LIST_RESPONSE);
    const calledPath = requestJson.mock.calls[0][0];
    const parsed = new URL(calledPath, "https://web.civibus.local");
    expect(parsed.pathname).toBe("/v1/candidates");
    expect(parsed.searchParams.get("person_id")).toBe("11111111-1111-4111-8111-111111111111");
    expect(parsed.searchParams.get("limit")).toBe("10");
    expect(parsed.searchParams.get("offset")).toBe("0");
  });

  it("fetches committee list using URLSearchParams serialization and preserves envelope payloads", async () => {
    const requestJson = vi.fn(async (path: string) => {
      void path;
      return COMMITTEE_LIST_RESPONSE;
    });

    const result = await fetchCommitteeList(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { state: "GA", committee_type: "P", limit: 50, offset: 0 }
    );

    expect(result).toEqual(COMMITTEE_LIST_RESPONSE);
    expect(requestJson).toHaveBeenCalledTimes(1);
    const calledPath = requestJson.mock.calls[0][0];
    const parsed = new URL(calledPath, "https://web.civibus.local");
    expect(parsed.pathname).toBe("/v1/committees");
    expect(parsed.searchParams.get("state")).toBe("GA");
    expect(parsed.searchParams.get("committee_type")).toBe("P");
    expect(parsed.searchParams.get("limit")).toBe("50");
    expect(parsed.searchParams.get("offset")).toBe("0");
    expect(calledPath).toBe(
      buildCommitteeListPath({ state: "GA", committee_type: "P", limit: 50, offset: 0 })
    );
  });

  it("fetches candidates by slug and preserves slug-collision arrays", async () => {
    const requestJson = vi.fn(async () => CANDIDATE_SLUG_MATCHES);

    const result = await fetchCandidatesBySlug(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { slug: "candidate-one" }
    );

    expect(result).toEqual(CANDIDATE_SLUG_MATCHES);
    expect(requestJson).toHaveBeenCalledWith(buildCandidatesBySlugPath("candidate-one"));
  });

  it("fetches committees by slug and preserves slug-collision arrays", async () => {
    const requestJson = vi.fn(async () => COMMITTEE_SLUG_MATCHES);

    const result = await fetchCommitteesBySlug(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { slug: "committee-one" }
    );

    expect(result).toEqual(COMMITTEE_SLUG_MATCHES);
    expect(requestJson).toHaveBeenCalledWith(buildCommitteesBySlugPath("committee-one"));
  });

  it("preserves backend 422 malformed UUID semantics for committee detail requests", async () => {
    const requestJson = vi
      .fn()
      .mockRejectedValue(
        new ApiResponseError(422, { detail: [{ loc: ["path", "committee_id"], msg: "Input should be a valid UUID" }] })
      );

    await expect(
      fetchCommitteeDetailBundle(
        { requestJson: requestJson as ApiClient["requestJson"] },
        { id: "not-a-uuid" }
      )
    ).rejects.toMatchObject({
      status: 422,
      body: { detail: [{ loc: ["path", "committee_id"], msg: "Input should be a valid UUID" }] }
    });
  });

  it("builds person-linked candidate finance sections with summary, IE, and donor/vendor-table inputs", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === "/v1/candidates?person_id=11111111-1111-4111-8111-111111111111&limit=10&offset=0") {
        return {
          items: [
            {
              id: CANDIDATE_ID,
              fec_candidate_id: "H0NC01001",
              name: "Candidate One",
              person_id: "11111111-1111-4111-8111-111111111111",
              party: "DEM",
              office: "H",
              state: "NC",
              district: "01",
              slug: "candidate-one",
              slug_is_unique: true
            }
          ],
          has_next: false,
          offset: 0,
          limit: 10
        };
      }

      if (path === buildCandidateDetailPath(CANDIDATE_ID)) {
        return CANDIDATE_DETAIL;
      }

      if (path === buildCandidateSummaryPath(CANDIDATE_ID)) {
        return {
          candidate_id: CANDIDATE_ID,
          candidate_name: "Candidate One",
          total_raised: "250.00",
          total_spent: "100.00",
          net: "150.00",
          transaction_count: 5,
          committees: [
            COMMITTEE_SUMMARY,
            {
              ...COMMITTEE_SUMMARY,
              committee_id: SECOND_COMMITTEE_ID,
              committee_name: "Committee Two"
            }
          ],
          cash_on_hand: null,
          summary_source: "derived" as const,
          itemized_transaction_count: 5
        };
      }

      if (path === buildCandidateIndependentExpendituresPath(CANDIDATE_ID)) {
        return [];
      }

      if (path === buildCandidateIndependentExpendituresSummaryPath(CANDIDATE_ID)) {
        return {
          candidate_id: CANDIDATE_ID,
          support_total: "0.00",
          oppose_total: "0.00",
          support_count: 0,
          oppose_count: 0,
          top_spenders: [],
          excluded_outlier_count: 0
        };
      }

      if (path === buildPersonContributionInsightsPath(PERSON_ID)) {
        return PERSON_CONTRIBUTION_INSIGHTS;
      }

      if (path === buildCommitteeTransactionsPath(COMMITTEE_ID)) {
        return [
          {
            id: "f1111111-1111-4111-8111-111111111111",
            filing_id: "f2222222-2222-4222-8222-222222222222",
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
            contributor_person_id: null,
            contributor_organization_id: null,
            contributor_address_id: null,
            recipient_candidate_id: null,
            recipient_committee_id: null,
            memo_text: null,
            is_memo: false,
            amendment_indicator: "N",
            date_is_reliable: true
          }
        ];
      }

      if (path === buildCommitteeTransactionsPath(SECOND_COMMITTEE_ID)) {
        return [
          {
            id: "f3333333-3333-4333-8333-333333333333",
            filing_id: "f4444444-4444-4444-8444-444444444444",
            committee_id: SECOND_COMMITTEE_ID,
            transaction_type: "expenditure",
            transaction_identifier: "TX-2",
            transaction_date: "2026-03-20",
            amount: 250,
            contributor_name_raw: "Vendor Two",
            contributor_employer: null,
            contributor_occupation: null,
            contributor_city: null,
            contributor_state: null,
            contributor_zip: null,
            contributor_person_id: null,
            contributor_organization_id: null,
            contributor_address_id: null,
            recipient_candidate_id: null,
            recipient_committee_id: null,
            memo_text: null,
            is_memo: false,
            amendment_indicator: "N",
            date_is_reliable: true
          }
        ];
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const sections = await fetchPersonCandidateFinanceSections(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { personId: "11111111-1111-4111-8111-111111111111", limit: 10 }
    );

    expect(sections).toHaveLength(1);
    expect(sections[0].candidate.id).toBe(CANDIDATE_ID);
    await expect(sections[0].summary).resolves.toMatchObject({ candidate_id: CANDIDATE_ID });
    expect(sections[0].ieSummary).toMatchObject({ candidate_id: CANDIDATE_ID });
    await expect(sections[0].ieTransactions).resolves.toEqual([]);
    await expect(sections[0].donorVendorTransactions).resolves.toMatchObject([
      { committee_id: SECOND_COMMITTEE_ID, transaction_identifier: "TX-2" },
      { committee_id: COMMITTEE_ID, transaction_identifier: "TX-1" }
    ]);
    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      "/v1/candidates?person_id=11111111-1111-4111-8111-111111111111&limit=10&offset=0",
      buildCandidateDetailPath(CANDIDATE_ID),
      buildCandidateSummaryPath(CANDIDATE_ID),
      buildCandidateIndependentExpendituresPath(CANDIDATE_ID),
      buildCandidateIndependentExpendituresSummaryPath(CANDIDATE_ID),
      buildCommitteeTransactionsPath(COMMITTEE_ID),
      buildCommitteeTransactionsPath(SECOND_COMMITTEE_ID)
    ]);
  });

  it("sorts merged person donor/vendor transactions by descending date with deterministic id tie-breakers", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === "/v1/candidates?person_id=11111111-1111-4111-8111-111111111111&limit=10&offset=0") {
        return {
          items: [
            {
              id: CANDIDATE_ID,
              fec_candidate_id: "H0NC01001",
              name: "Candidate One",
              person_id: "11111111-1111-4111-8111-111111111111",
              party: "DEM",
              office: "H",
              state: "NC",
              district: "01",
              slug: "candidate-one",
              slug_is_unique: true
            }
          ],
          has_next: false,
          offset: 0,
          limit: 10
        };
      }

      if (path === buildCandidateDetailPath(CANDIDATE_ID)) {
        return CANDIDATE_DETAIL;
      }

      if (path === buildCandidateSummaryPath(CANDIDATE_ID)) {
        return {
          candidate_id: CANDIDATE_ID,
          candidate_name: "Candidate One",
          total_raised: "250.00",
          total_spent: "100.00",
          net: "150.00",
          transaction_count: 5,
          committees: [
            {
              ...COMMITTEE_SUMMARY,
              committee_id: SECOND_COMMITTEE_ID,
              committee_name: "Committee Two"
            },
            COMMITTEE_SUMMARY
          ],
          cash_on_hand: null,
          summary_source: "derived" as const,
          itemized_transaction_count: 5
        };
      }

      if (path === buildCandidateIndependentExpendituresPath(CANDIDATE_ID)) {
        return [];
      }

      if (path === buildCandidateIndependentExpendituresSummaryPath(CANDIDATE_ID)) {
        return {
          candidate_id: CANDIDATE_ID,
          support_total: "0.00",
          oppose_total: "0.00",
          support_count: 0,
          oppose_count: 0,
          top_spenders: [],
          excluded_outlier_count: 0
        };
      }

      if (path === buildPersonContributionInsightsPath(PERSON_ID)) {
        return PERSON_CONTRIBUTION_INSIGHTS;
      }

      if (path === buildCommitteeTransactionsPath(COMMITTEE_ID)) {
        return [
          {
            id: "aaaaaaaa-1111-4111-8111-111111111111",
            filing_id: "f2222222-2222-4222-8222-222222222222",
            committee_id: COMMITTEE_ID,
            transaction_type: "contribution",
            transaction_identifier: "TX-older",
            transaction_date: "2026-03-19",
            amount: 125,
            contributor_name_raw: "Donor One",
            contributor_employer: null,
            contributor_occupation: null,
            contributor_city: null,
            contributor_state: null,
            contributor_zip: null,
            contributor_person_id: null,
            contributor_organization_id: null,
            contributor_address_id: null,
            recipient_candidate_id: null,
            recipient_committee_id: null,
            memo_text: null,
            is_memo: false,
            amendment_indicator: "N",
            date_is_reliable: true
          },
          {
            id: "cccccccc-1111-4111-8111-111111111111",
            filing_id: "f2222222-2222-4222-8222-222222222229",
            committee_id: COMMITTEE_ID,
            transaction_type: "contribution",
            transaction_identifier: "TX-same-date-c",
            transaction_date: "2026-03-20",
            amount: 75,
            contributor_name_raw: "Donor C",
            contributor_employer: null,
            contributor_occupation: null,
            contributor_city: null,
            contributor_state: null,
            contributor_zip: null,
            contributor_person_id: null,
            contributor_organization_id: null,
            contributor_address_id: null,
            recipient_candidate_id: null,
            recipient_committee_id: null,
            memo_text: null,
            is_memo: false,
            amendment_indicator: "N",
            date_is_reliable: true
          }
        ];
      }

      if (path === buildCommitteeTransactionsPath(SECOND_COMMITTEE_ID)) {
        return [
          {
            id: "bbbbbbbb-1111-4111-8111-111111111111",
            filing_id: "f4444444-4444-4444-8444-444444444444",
            committee_id: SECOND_COMMITTEE_ID,
            transaction_type: "expenditure",
            transaction_identifier: "TX-newer",
            transaction_date: "2026-03-21",
            amount: 250,
            contributor_name_raw: "Vendor Two",
            contributor_employer: null,
            contributor_occupation: null,
            contributor_city: null,
            contributor_state: null,
            contributor_zip: null,
            contributor_person_id: null,
            contributor_organization_id: null,
            contributor_address_id: null,
            recipient_candidate_id: null,
            recipient_committee_id: null,
            memo_text: null,
            is_memo: false,
            amendment_indicator: "N",
            date_is_reliable: true
          },
          {
            id: "bbbbbbbb-9999-4999-8999-999999999999",
            filing_id: "f4444444-4444-4444-8444-444444444445",
            committee_id: SECOND_COMMITTEE_ID,
            transaction_type: "expenditure",
            transaction_identifier: "TX-same-date-b",
            transaction_date: "2026-03-20",
            amount: 150,
            contributor_name_raw: "Vendor B",
            contributor_employer: null,
            contributor_occupation: null,
            contributor_city: null,
            contributor_state: null,
            contributor_zip: null,
            contributor_person_id: null,
            contributor_organization_id: null,
            contributor_address_id: null,
            recipient_candidate_id: null,
            recipient_committee_id: null,
            memo_text: null,
            is_memo: false,
            amendment_indicator: "N",
            date_is_reliable: true
          }
        ];
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const sections = await fetchPersonCandidateFinanceSections(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { personId: "11111111-1111-4111-8111-111111111111", limit: 10 }
    );

    await expect(sections[0].donorVendorTransactions).resolves.toMatchObject([
      { id: "bbbbbbbb-1111-4111-8111-111111111111", transaction_date: "2026-03-21" },
      { id: "bbbbbbbb-9999-4999-8999-999999999999", transaction_date: "2026-03-20" },
      { id: "cccccccc-1111-4111-8111-111111111111", transaction_date: "2026-03-20" },
      { id: "aaaaaaaa-1111-4111-8111-111111111111", transaction_date: "2026-03-19" }
    ]);
  });
});
