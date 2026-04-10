import { describe, expect, it } from "vitest";
import {
  COMMITTEE_TRANSACTIONS_LIMIT,
  buildCandidateDetailPath,
  buildCandidateHref,
  buildCandidateListPath,
  buildCandidateSummaryPath,
  buildCandidatesBySlugPath,
  buildCommitteeDetailPath,
  buildCommitteeFilingBreakdownPath,
  buildCommitteeHref,
  buildCommitteeListPath,
  buildCommitteeSummaryPath,
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
