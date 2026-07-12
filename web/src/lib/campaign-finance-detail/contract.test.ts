import { describe, expect, it } from "vitest";
import {
  CANDIDATES_PAGE_PATH,
  COMMITTEES_PAGE_PATH,
  COMMITTEE_TRANSACTIONS_LIMIT,
  buildCandidateDetailPath,
  buildCandidateHref,
  buildCandidateListPath,
  buildCandidatesPagePath,
  buildCandidateSummaryPath,
  buildCandidatesBySlugPath,
  buildCountyCampaignFinanceSummaryPath,
  buildCommitteeDetailPath,
  buildCommitteeFilingBreakdownPath,
  buildCommitteeHref,
  buildCommitteeIndependentExpendituresMadePath,
  buildCommitteeListPath,
  buildCommitteeSummaryPath,
  buildCommitteesPagePath,
  buildCommitteeTransactionsPath,
  buildCommitteesBySlugPath,
  buildPersonContributionInsightsPath,
  buildPersonTopDonorsPath,
  buildPersonTopEmployersPath,
  type CandidateDetailResponse,
  type CandidateListItem,
  type CandidateListResponse,
  type CommitteeDetailResponse,
  type CommitteeListItem,
  type CommitteeListResponse,
  type CommitteeCycleSummary,
  type CommitteeFundraisingSummary,
  type CommitteeIndependentExpenditureActivity,
  type IndependentExpenditureSummary,
  type PersonContributionInsights
} from "./contract";

const COMMITTEE_ID = "33333333-3333-4333-8333-333333333333";
const CANDIDATE_ID = "44444444-4444-4444-8444-444444444444";

function expectType<T extends true>(): void {}

describe("campaign-finance detail contract", () => {
  it("builds backend-owned committee and candidate detail paths", () => {
    expect(buildCommitteeDetailPath(COMMITTEE_ID)).toBe(`/v1/committees/${COMMITTEE_ID}`);
    expect(buildCandidateDetailPath(CANDIDATE_ID)).toBe(`/v1/candidates/${CANDIDATE_ID}`);
  });

  it("builds backend-owned committee summary and filing-breakdown paths", () => {
    expect(buildCommitteeSummaryPath(COMMITTEE_ID)).toBe(`/v1/committees/${COMMITTEE_ID}/summary`);
    expect(buildCommitteeFilingBreakdownPath(COMMITTEE_ID)).toBe(
      `/v1/committees/${COMMITTEE_ID}/filings/summary`
    );
    expect(buildCommitteeIndependentExpendituresMadePath(COMMITTEE_ID)).toBe(
      `/v1/committees/${COMMITTEE_ID}/independent-expenditures-made`
    );
  });

  it("builds backend-owned candidate summary path", () => {
    expect(buildCandidateSummaryPath(CANDIDATE_ID)).toBe(`/v1/candidates/${CANDIDATE_ID}/summary`);
  });

  it("builds backend-owned person contribution insights path", () => {
    const personId = "11111111-1111-4111-8111-111111111111";

    expect(buildPersonContributionInsightsPath(personId)).toBe(
      `/v1/person/${personId}/contribution-insights`
    );
  });

  it("builds backend-owned person top donors path", () => {
    const personId = "11111111-1111-4111-8111-111111111111";

    expect(buildPersonTopDonorsPath(personId)).toBe(`/v1/person/${personId}/top-donors`);
  });

  it("builds backend-owned person top employers path", () => {
    const personId = "11111111-1111-4111-8111-111111111111";

    expect(buildPersonTopEmployersPath(personId)).toBe(`/v1/person/${personId}/top-employers`);
  });

  it("PersonContributionInsights mirrors backend serialized money fields", () => {
    const insights: PersonContributionInsights = {
      person_id: "11111111-1111-4111-8111-111111111111",
      has_data: true,
      metadata: {
        coverage_start_date: "2022-01-01",
        coverage_end_date: null,
        cycles_included: [2022, 2024, 2026],
        committee_count: 2,
        approximate_geography: true,
        excluded_geography: "Unitemized contributions are excluded from geography.",
        caveats: ["missing_zcta_district"]
      },
      monthly_totals: [{ month: "2026-01", total_amount: "1234.56", transaction_count: 7 }],
      itemized_size_buckets: [
        {
          label: "$1-$199",
          min_amount: "1.00",
          max_amount: "199.99",
          total_amount: "500.00",
          transaction_count: 4
        }
      ],
      dollars_by_size: [
        {
          label: "Unitemized (<$200)",
          total_amount: "100.00",
          source: "committee_summary"
        },
        {
          label: "$200+",
          total_amount: "900.00",
          source: "transactions"
        }
      ],
      cycle_totals: [
        {
          cycle: 2026,
          itemized_individual_contribution_amount: "700.00",
          itemized_transaction_count: 6,
          unitemized_individual_contribution_amount: "300.00",
          total_individual_contribution_amount: "1000.00",
          source: "mixed_sources"
        }
      ],
      career_totals: {
        itemized_individual_contribution_amount: "1700.00",
        itemized_transaction_count: 12,
        unitemized_individual_contribution_amount: "300.00",
        total_individual_contribution_amount: "2000.00",
        source: "committee_summary"
      },
      geography: {
        by_state: [{ label: "NC", total_amount: "750.00", transaction_count: 5 }],
        by_district: [{ label: "NC-01", total_amount: "250.00", transaction_count: 2 }],
        district_share: {
          in_district_amount: "250.00",
          out_of_district_amount: "500.00",
          unknown_district_amount: "0.00",
          share: "0.3333",
          available: true
        }
      },
      small_dollar_share: {
        small_dollar_amount: "600.00",
        total_contribution_amount: "1000.00",
        share: "0.6000",
        available: true
      }
    };

    expect(insights.monthly_totals[0].total_amount).toBe("1234.56");
    expect(insights.itemized_size_buckets[0].min_amount).toBe("1.00");
    expect(insights.itemized_size_buckets[0].max_amount).toBe("199.99");
    expect(insights.dollars_by_size[0].total_amount).toBe("100.00");
    expect(insights.cycle_totals[0].source).toBe("mixed_sources");
    expect(insights.career_totals.total_individual_contribution_amount).toBe("2000.00");
    expect(insights.small_dollar_share.share).toBe("0.6000");
  });

  it("CandidateFundraisingSummary contract exposes cash_on_hand and summary_source", () => {
    // Type-level proof: the CandidateFundraisingSummary contract MUST include the
    // Stage 3 fields. If either field is missing from the type, this object literal
    // (with `satisfies` and explicit fields) fails to compile.
    const weballSummary = {
      candidate_id: CANDIDATE_ID,
      candidate_name: "Stage 3 Weball Candidate",
      total_raised: "9000.00",
      total_spent: "3500.00",
      net: "5500.00",
      transaction_count: 0,
      itemized_transaction_count: 0,
      committees: [],
      cash_on_hand: "5500.00",
      summary_source: "fec_weball"
    } satisfies import("./contract").CandidateFundraisingSummary;

    const derivedSummary = {
      candidate_id: CANDIDATE_ID,
      candidate_name: "Stage 3 Derived Candidate",
      total_raised: "0.00",
      total_spent: "0.00",
      net: "0.00",
      transaction_count: 0,
      itemized_transaction_count: 0,
      committees: [],
      cash_on_hand: null,
      summary_source: "derived"
    } satisfies import("./contract").CandidateFundraisingSummary;

    expect(weballSummary.cash_on_hand).toBe("5500.00");
    expect(weballSummary.summary_source).toBe("fec_weball");
    expect(derivedSummary.cash_on_hand).toBeNull();
    expect(derivedSummary.summary_source).toBe("derived");
  });

  it("builds backend-owned county campaign-finance summary path", () => {
    expect(buildCountyCampaignFinanceSummaryPath("NC", "wake")).toBe(
      "/v1/counties/nc/wake/campaign-finance-summary"
    );
    expect(buildCountyCampaignFinanceSummaryPath("nc", "new_hanover")).toBe(
      "/v1/counties/nc/new_hanover/campaign-finance-summary"
    );
  });

  it("builds committee transactions with only committee_id + shared limit params", () => {
    const path = buildCommitteeTransactionsPath(COMMITTEE_ID);
    const parsed = new URL(path, "https://web.civibus.local");

    expect(parsed.pathname).toBe("/v1/transactions");
    expect(parsed.searchParams.get("committee_id")).toBe(COMMITTEE_ID);
    expect(parsed.searchParams.get("limit")).toBe(String(COMMITTEE_TRANSACTIONS_LIMIT));
    expect(parsed.searchParams.has("jurisdiction")).toBe(false);
    expect(parsed.searchParams.has("min_date")).toBe(false);
    expect(parsed.searchParams.has("max_date")).toBe(false);
    expect(parsed.searchParams.has("min_amount")).toBe(false);
    expect(parsed.searchParams.has("max_amount")).toBe(false);
    expect(parsed.searchParams.has("offset")).toBe(false);
  });

  it("keeps committee transaction limit as a bounded small slice", () => {
    expect(COMMITTEE_TRANSACTIONS_LIMIT).toBeGreaterThan(0);
    expect(COMMITTEE_TRANSACTIONS_LIMIT).toBeLessThanOrEqual(50);
  });

  it("encodes committee and candidate detail path segments", () => {
    const maliciousId = "../search?entity_type=committee";

    expect(buildCommitteeDetailPath(maliciousId)).toBe(
      "/v1/committees/..%2Fsearch%3Fentity_type%3Dcommittee"
    );
    expect(buildCandidateDetailPath(maliciousId)).toBe(
      "/v1/candidates/..%2Fsearch%3Fentity_type%3Dcommittee"
    );
    expect(buildCommitteeSummaryPath(maliciousId)).toBe(
      "/v1/committees/..%2Fsearch%3Fentity_type%3Dcommittee/summary"
    );
    expect(buildCommitteeFilingBreakdownPath(maliciousId)).toBe(
      "/v1/committees/..%2Fsearch%3Fentity_type%3Dcommittee/filings/summary"
    );
    expect(buildCandidateSummaryPath(maliciousId)).toBe(
      "/v1/candidates/..%2Fsearch%3Fentity_type%3Dcommittee/summary"
    );
  });
});

describe("Stage 1 slug fields on detail responses", () => {
  it("CandidateDetailResponse includes slug and slug_is_unique", () => {
    const candidate: CandidateDetailResponse = {
      id: CANDIDATE_ID,
      fec_candidate_id: "H0NC01001",
      name: "Jane Smith",
      slug: "jane-smith",
      slug_is_unique: true,
      person_id: null,
      party: "DEM",
      office: "H",
      state: "NC",
      district: "01",
      incumbent_challenge: null,
      principal_committee_id: null,
      sources: []
    };
    expect(candidate.slug).toBe("jane-smith");
    expect(candidate.slug_is_unique).toBe(true);
  });

  it("CommitteeDetailResponse includes slug and slug_is_unique", () => {
    const committee: CommitteeDetailResponse = {
      id: COMMITTEE_ID,
      fec_committee_id: "C12345678",
      name: "Friends of Jane",
      slug: "friends-of-jane",
      slug_is_unique: false,
      organization_id: null,
      committee_type: "P",
      committee_designation: null,
      party: null,
      state: null,
      city: null,
      zip_code: null,
      treasurer_name: null,
      sources: [],
      linked_candidates: []
    };
    expect(committee.slug).toBe("friends-of-jane");
    expect(committee.slug_is_unique).toBe(false);
  });
});

describe("campaign-finance list item and envelope types", () => {
  const candidateListItem: CandidateListItem = {
    id: CANDIDATE_ID,
    fec_candidate_id: "H0NC01001",
    name: "Jane Smith",
    party: "DEM",
    office: "H",
    state: "NC",
    district: "01",
    slug: "jane-smith",
    slug_is_unique: true
  };

  const committeeListItem: CommitteeListItem = {
    id: COMMITTEE_ID,
    fec_committee_id: "C12345678",
    name: "Friends of Jane",
    committee_type: "P",
    party: "DEM",
    state: "NC",
    slug: "friends-of-jane",
    slug_is_unique: true
  };

  it("CandidateListItem carries slug and slug_is_unique", () => {
    expect(candidateListItem.slug).toBe("jane-smith");
    expect(candidateListItem.slug_is_unique).toBe(true);
  });

  it("CommitteeListItem carries slug and slug_is_unique", () => {
    expect(committeeListItem.slug).toBe("friends-of-jane");
    expect(committeeListItem.slug_is_unique).toBe(true);
  });

  it("CandidateListResponse wraps items in a pagination envelope", () => {
    const response: CandidateListResponse = {
      items: [candidateListItem],
      has_next: false,
      offset: 0,
      limit: 50
    };
    expect(response.items).toHaveLength(1);
    expect(response.has_next).toBe(false);
    expect(response.offset).toBe(0);
    expect(response.limit).toBe(50);
  });

  it("CommitteeListResponse wraps items in a pagination envelope", () => {
    const response: CommitteeListResponse = {
      items: [committeeListItem],
      has_next: true,
      offset: 0,
      limit: 25
    };
    expect(response.items).toHaveLength(1);
    expect(response.has_next).toBe(true);
  });
});

describe("campaign-finance by-slug and list path builders", () => {
  it("builds candidate by-slug path with encoded slug", () => {
    expect(buildCandidatesBySlugPath("jane-smith")).toBe("/v1/candidates/by-slug/jane-smith");
  });

  it("builds committee by-slug path with encoded slug", () => {
    expect(buildCommitteesBySlugPath("friends-of-jane")).toBe(
      "/v1/committees/by-slug/friends-of-jane"
    );
  });

  it("encodes special characters in by-slug paths", () => {
    expect(buildCandidatesBySlugPath("o'brien")).toBe("/v1/candidates/by-slug/o'brien");
    expect(buildCommitteesBySlugPath("a/b")).toBe("/v1/committees/by-slug/a%2Fb");
  });

  it("builds candidate list path with no params", () => {
    expect(buildCandidateListPath({})).toBe("/v1/candidates");
  });

  it("builds candidate list path with filter params", () => {
    const path = buildCandidateListPath({ state: "NC", office: "H", limit: 25, offset: 50 });
    const parsed = new URL(path, "https://test.local");
    expect(parsed.pathname).toBe("/v1/candidates");
    expect(parsed.searchParams.get("state")).toBe("NC");
    expect(parsed.searchParams.get("office")).toBe("H");
    expect(parsed.searchParams.get("limit")).toBe("25");
    expect(parsed.searchParams.get("offset")).toBe("50");
  });

  it("builds committee list path with filter params", () => {
    const path = buildCommitteeListPath({ state: "GA", committee_type: "P" });
    const parsed = new URL(path, "https://test.local");
    expect(parsed.pathname).toBe("/v1/committees");
    expect(parsed.searchParams.get("state")).toBe("GA");
    expect(parsed.searchParams.get("committee_type")).toBe("P");
  });

  it("omits undefined filter params from list paths", () => {
    const path = buildCandidateListPath({ state: undefined, office: "S" });
    const parsed = new URL(path, "https://test.local");
    expect(parsed.searchParams.has("state")).toBe(false);
    expect(parsed.searchParams.get("office")).toBe("S");
  });

  it("drops blank string filter params from candidate list and page paths", () => {
    const listPath = buildCandidateListPath({ state: "", office: "S", limit: 25 });
    const pagePath = buildCandidatesPagePath({ state: "", office: "S", limit: 25 });
    const parsedList = new URL(listPath, "https://test.local");
    const parsedPage = new URL(pagePath, "https://test.local");

    expect(parsedList.searchParams.has("state")).toBe(false);
    expect(parsedList.searchParams.get("office")).toBe("S");
    expect(parsedPage.searchParams.has("state")).toBe(false);
    expect(parsedPage.searchParams.get("office")).toBe("S");
  });

  it("builds candidates page path with no params", () => {
    expect(buildCandidatesPagePath({})).toBe(CANDIDATES_PAGE_PATH);
  });

  it("builds candidates page path with partial filter params", () => {
    const path = buildCandidatesPagePath({ office: "H", limit: 25 });
    const parsed = new URL(path, "https://test.local");

    expect(parsed.pathname).toBe(CANDIDATES_PAGE_PATH);
    expect(parsed.searchParams.get("office")).toBe("H");
    expect(parsed.searchParams.get("limit")).toBe("25");
    expect(parsed.searchParams.has("state")).toBe(false);
    expect(parsed.searchParams.has("offset")).toBe(false);
  });

  it("builds candidates page path for offset-only pagination links", () => {
    const path = buildCandidatesPagePath({ offset: 50, limit: 25 });
    const parsed = new URL(path, "https://test.local");

    expect(parsed.pathname).toBe(CANDIDATES_PAGE_PATH);
    expect(parsed.searchParams.get("offset")).toBe("50");
    expect(parsed.searchParams.get("limit")).toBe("25");
    expect(parsed.searchParams.has("state")).toBe(false);
    expect(parsed.searchParams.has("office")).toBe(false);
  });
});

describe("buildCommitteesPagePath", () => {
  it("builds committees page path with no params", () => {
    expect(buildCommitteesPagePath({})).toBe(COMMITTEES_PAGE_PATH);
  });

  it("builds committees page path with state-only filter", () => {
    const path = buildCommitteesPagePath({ state: "GA" });
    const parsed = new URL(path, "https://test.local");

    expect(parsed.pathname).toBe(COMMITTEES_PAGE_PATH);
    expect(parsed.searchParams.get("state")).toBe("GA");
    expect(parsed.searchParams.has("committee_type")).toBe(false);
  });

  it("builds committees page path with committee_type-only filter", () => {
    const path = buildCommitteesPagePath({ committee_type: "Q" });
    const parsed = new URL(path, "https://test.local");

    expect(parsed.pathname).toBe(COMMITTEES_PAGE_PATH);
    expect(parsed.searchParams.get("committee_type")).toBe("Q");
    expect(parsed.searchParams.has("state")).toBe(false);
  });

  it("builds committees page path with pagination params", () => {
    const path = buildCommitteesPagePath({ offset: 50, limit: 25 });
    const parsed = new URL(path, "https://test.local");

    expect(parsed.pathname).toBe(COMMITTEES_PAGE_PATH);
    expect(parsed.searchParams.get("offset")).toBe("50");
    expect(parsed.searchParams.get("limit")).toBe("25");
    expect(parsed.searchParams.has("state")).toBe(false);
    expect(parsed.searchParams.has("committee_type")).toBe(false);
  });

  it("builds committees page path with combined filters and pagination", () => {
    const path = buildCommitteesPagePath({ state: "NC", committee_type: "P", offset: 25, limit: 25 });
    const parsed = new URL(path, "https://test.local");

    expect(parsed.pathname).toBe(COMMITTEES_PAGE_PATH);
    expect(parsed.searchParams.get("state")).toBe("NC");
    expect(parsed.searchParams.get("committee_type")).toBe("P");
    expect(parsed.searchParams.get("offset")).toBe("25");
    expect(parsed.searchParams.get("limit")).toBe("25");
  });

  it("omits undefined params from committees page path", () => {
    const path = buildCommitteesPagePath({ state: undefined, committee_type: "Q", limit: 25 });
    const parsed = new URL(path, "https://test.local");

    expect(parsed.searchParams.has("state")).toBe(false);
    expect(parsed.searchParams.get("committee_type")).toBe("Q");
    expect(parsed.searchParams.get("limit")).toBe("25");
  });

  it("drops blank string filter params from committee list and page paths", () => {
    const listPath = buildCommitteeListPath({ state: "", committee_type: "Q", limit: 25 });
    const pagePath = buildCommitteesPagePath({ state: "", committee_type: "Q", limit: 25 });
    const parsedList = new URL(listPath, "https://test.local");
    const parsedPage = new URL(pagePath, "https://test.local");

    expect(parsedList.searchParams.has("state")).toBe(false);
    expect(parsedList.searchParams.get("committee_type")).toBe("Q");
    expect(parsedPage.searchParams.has("state")).toBe(false);
    expect(parsedPage.searchParams.get("committee_type")).toBe("Q");
  });
});

describe("buildCandidateHref and buildCommitteeHref", () => {
  it("uses slug path when slug_is_unique is true", () => {
    expect(
      buildCandidateHref({ id: CANDIDATE_ID, slug: "jane-smith", slug_is_unique: true })
    ).toBe("/candidate/jane-smith");
  });

  it("falls back to UUID path when slug_is_unique is false", () => {
    expect(
      buildCandidateHref({ id: CANDIDATE_ID, slug: "john-smith", slug_is_unique: false })
    ).toBe(`/candidate/${CANDIDATE_ID}`);
  });

  it("uses slug path for committees when unique", () => {
    expect(
      buildCommitteeHref({ id: COMMITTEE_ID, slug: "friends-of-jane", slug_is_unique: true })
    ).toBe("/committee/friends-of-jane");
  });

  it("falls back to UUID for committees when not unique", () => {
    expect(
      buildCommitteeHref({ id: COMMITTEE_ID, slug: "pac-fund", slug_is_unique: false })
    ).toBe(`/committee/${COMMITTEE_ID}`);
  });

  it("encodes special characters in slug href paths", () => {
    expect(
      buildCandidateHref({ id: CANDIDATE_ID, slug: "a/b", slug_is_unique: true })
    ).toBe("/candidate/a%2Fb");
  });
});

describe("Stage 5 contract fields", () => {
  it("Stage 5 API-owned fields stay required in the TypeScript contract", () => {
    expectType<{} extends Pick<CommitteeDetailResponse, "linked_candidates"> ? false : true>();
    expectType<
      {} extends Pick<CommitteeFundraisingSummary, "itemized_transaction_count"> ? false : true
    >();
    expectType<{} extends Pick<CommitteeFundraisingSummary, "cycle_summaries"> ? false : true>();
    expectType<{} extends Pick<CommitteeFundraisingSummary, "summary_source"> ? false : true>();
    expectType<
      {} extends Pick<CommitteeIndependentExpenditureActivity, "excluded_outlier_count">
        ? false
        : true
    >();
    expectType<
      {} extends Pick<import("./contract").CandidateFundraisingSummary, "itemized_transaction_count">
        ? false
        : true
    >();
    expectType<
      {} extends Pick<IndependentExpenditureSummary, "excluded_outlier_count"> ? false : true
    >();
    expect(true).toBe(true);
  });

  it("CommitteeDetailResponse includes linked_candidates", () => {
    const committee: CommitteeDetailResponse = {
      id: COMMITTEE_ID,
      fec_committee_id: "C00112233",
      name: "Stage 5 PAC",
      slug: "stage-5-pac",
      slug_is_unique: true,
      organization_id: null,
      committee_type: "Q",
      committee_designation: null,
      party: null,
      state: null,
      city: null,
      zip_code: null,
      treasurer_name: null,
      sources: [],
      linked_candidates: [
        {
          id: CANDIDATE_ID,
          fec_candidate_id: "H0NC01001",
          name: "Linked Candidate",
          person_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
          party: "DEM",
          office: "H",
          state: "NC",
          district: "01",
          slug: "linked-candidate",
          slug_is_unique: true
        }
      ]
    };
    expect(committee.linked_candidates).toHaveLength(1);
    expect(committee.linked_candidates![0].person_id).toBe(
      "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    );
  });

  it("CommitteeFundraisingSummary includes itemized_transaction_count, cycle_summaries, summary_source", () => {
    const officialSummary: CommitteeFundraisingSummary = {
      committee_id: COMMITTEE_ID,
      committee_name: "Official PAC",
      total_raised: "500000.00",
      total_spent: "250000.00",
      net: "250000.00",
      transaction_count: 120,
      jurisdiction: null,
      data_through: null,
      cash_receipts_total: "400000.00",
      in_kind_receipts_total: "10000.00",
      loan_receipts_total: "0.00",
      contribution_receipts_total: "90000.00",
      top_donors: [],
      top_vendors: [],
      spend_categories: null,
      itemized_transaction_count: 120,
      cycle_summaries: [
        {
          cycle: 2024,
          total_receipts: "300000.00",
          total_disbursements: "150000.00",
          cash_on_hand: "150000.00",
          coverage_start_date: "2023-01-01",
          coverage_end_date: "2024-12-31"
        },
        {
          cycle: 2026,
          total_receipts: "200000.00",
          total_disbursements: "100000.00",
          cash_on_hand: null,
          coverage_start_date: "2025-01-01",
          coverage_end_date: null
        }
      ],
      summary_source: "fec_committee_summary"
    };
    expect(officialSummary.itemized_transaction_count).toBe(120);
    expect(officialSummary.cycle_summaries).toHaveLength(2);
    expect(officialSummary.summary_source).toBe("fec_committee_summary");

    const derivedSummary: CommitteeFundraisingSummary = {
      committee_id: COMMITTEE_ID,
      committee_name: "Derived PAC",
      total_raised: "1000.00",
      total_spent: "500.00",
      net: "500.00",
      transaction_count: 5,
      jurisdiction: null,
      data_through: null,
      cash_receipts_total: "1000.00",
      in_kind_receipts_total: "0.00",
      loan_receipts_total: "0.00",
      contribution_receipts_total: "0.00",
      top_donors: [],
      top_vendors: [],
      spend_categories: null,
      itemized_transaction_count: 5,
      cycle_summaries: [],
      summary_source: "derived"
    };
    expect(derivedSummary.summary_source).toBe("derived");
    expect(derivedSummary.cycle_summaries).toHaveLength(0);
  });

  it("CommitteeCycleSummary carries per-cycle official fields", () => {
    const cycle: CommitteeCycleSummary = {
      cycle: 2024,
      total_receipts: "1000000.00",
      total_disbursements: "750000.00",
      cash_on_hand: "250000.00",
      coverage_start_date: "2023-01-01",
      coverage_end_date: "2024-12-31"
    };
    expect(cycle.cycle).toBe(2024);
    expect(cycle.total_receipts).toBe("1000000.00");
    expect(cycle.cash_on_hand).toBe("250000.00");
  });

  it("CandidateFundraisingSummary includes itemized_transaction_count", () => {
    const summary = {
      candidate_id: CANDIDATE_ID,
      candidate_name: "Stage 5 Candidate",
      total_raised: "50000.00",
      total_spent: "25000.00",
      net: "25000.00",
      transaction_count: 42,
      committees: [],
      cash_on_hand: "25000.00",
      summary_source: "fec_weball",
      itemized_transaction_count: 42
    } satisfies import("./contract").CandidateFundraisingSummary;
    expect(summary.itemized_transaction_count).toBe(42);
    expect(summary.transaction_count).toBe(summary.itemized_transaction_count);
  });

  it("IndependentExpenditureSummary includes excluded_outlier_count", () => {
    const summary: IndependentExpenditureSummary = {
      candidate_id: CANDIDATE_ID,
      support_total: "500000.00",
      oppose_total: "200000.00",
      support_count: 10,
      oppose_count: 5,
      top_spenders: [],
      excluded_outlier_count: 2
    };
    expect(summary.excluded_outlier_count).toBe(2);
  });

  it("CommitteeIndependentExpenditureActivity mirrors the Stage 1 committee-made IE payload", () => {
    const activity: CommitteeIndependentExpenditureActivity = {
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
          person_id: "11111111-1111-4111-8111-111111111111",
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

    expect(activity.targets[0].person_id).toBe("11111111-1111-4111-8111-111111111111");
    expect(activity.targets[0].sources[0].record_url).toBe(
      "https://www.fec.gov/data/independent-expenditures/"
    );
  });
});
