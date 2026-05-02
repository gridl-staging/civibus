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
  buildCommitteeListPath,
  buildCommitteeSummaryPath,
  buildCommitteeTransactionsPath,
  buildCommitteesBySlugPath
} from "$lib/campaign-finance-detail/contract";
import {
  fetchCandidateDetail,
  fetchCandidateDetailBundle,
  fetchCandidateList,
  fetchPersonCandidateFinanceSections,
  fetchCandidatesBySlug,
  fetchCandidateSummary,
  fetchCountyCampaignFinanceSummary,
  fetchCommitteeList,
  fetchCommitteesBySlug,
  fetchCommitteeDetailBundle,
  fetchCommitteeFilingBreakdown,
  fetchCommitteeSummary
} from "./campaign-finance-detail";
import type { ApiClient } from "./client";

const COMMITTEE_ID = "33333333-3333-4333-8333-333333333333";
const SECOND_COMMITTEE_ID = "99999999-9999-4999-8999-999999999999";
const CANDIDATE_ID = "44444444-4444-4444-8444-444444444444";
const FILING_ID = "77777777-7777-4777-8777-777777777777";

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
  spend_categories: [{ category: "media", total_amount: "25.00", transaction_count: 1 }]
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
  it("fetches committee detail bundle with detail, transactions, summary, and filing breakdown", async () => {
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
          sources: []
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

      throw new Error(`unexpected path: ${path}`);
    });

    const data = await fetchCommitteeDetailBundle(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { id: COMMITTEE_ID }
    );

    expect(data.detail.id).toBe(COMMITTEE_ID);

    expect(data.transactions).toBeInstanceOf(Promise);
    expect(data.summary).toBeInstanceOf(Promise);
    expect(data.filingBreakdown).toBeInstanceOf(Promise);

    expect(await data.transactions).toHaveLength(1);
    expect(await data.summary).toEqual(COMMITTEE_SUMMARY);
    expect(await data.filingBreakdown).toEqual(COMMITTEE_FILING_BREAKDOWN);

    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      buildCommitteeDetailPath(COMMITTEE_ID),
      `/v1/transactions?committee_id=${COMMITTEE_ID}&limit=${COMMITTEE_TRANSACTIONS_LIMIT}`,
      buildCommitteeSummaryPath(COMMITTEE_ID),
      buildCommitteeFilingBreakdownPath(COMMITTEE_ID)
    ]);
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
      committees: [COMMITTEE_SUMMARY]
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

  it("fetches candidate detail bundle with detail, summary, and IE data in parallel", async () => {
    const candidateSummary = {
      candidate_id: CANDIDATE_ID,
      candidate_name: "Candidate One",
      total_raised: "250.00",
      total_spent: "100.00",
      net: "150.00",
      transaction_count: 5,
      committees: [COMMITTEE_SUMMARY]
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
      top_spenders: []
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
          ]
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
          top_spenders: []
        };
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
    await expect(sections[0].ieSummary).resolves.toMatchObject({ candidate_id: CANDIDATE_ID });
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
          ]
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
          top_spenders: []
        };
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
