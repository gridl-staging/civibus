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
  buildCommitteeListPath,
  buildCommitteeSummaryPath,
  buildCommitteesPagePath,
  buildCommitteeTransactionsPath,
  buildCommitteesBySlugPath,
  type CandidateDetailResponse,
  type CandidateListItem,
  type CandidateListResponse,
  type CommitteeDetailResponse,
  type CommitteeListItem,
  type CommitteeListResponse
} from "./contract";

const COMMITTEE_ID = "33333333-3333-4333-8333-333333333333";
const CANDIDATE_ID = "44444444-4444-4444-8444-444444444444";

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
  });

  it("builds backend-owned candidate summary path", () => {
    expect(buildCandidateSummaryPath(CANDIDATE_ID)).toBe(`/v1/candidates/${CANDIDATE_ID}/summary`);
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
      sources: []
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
