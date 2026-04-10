import { describe, expect, it, vi } from "vitest";
import {
  buildCandidateHref,
  buildCommitteeHref,
  type CandidateListResponse,
  type CommitteeListResponse
} from "$lib/campaign-finance-detail/contract";

// Inline mock responses — two pages of candidates, one page of committees
const CANDIDATE_PAGE_1: CandidateListResponse = {
  items: [
    {
      id: "11111111-1111-4111-8111-111111111111",
      fec_candidate_id: "H0NC01001",
      name: "Pat Candidate",
      party: "DEM",
      office: "H",
      state: "NC",
      district: "01",
      slug: "pat-candidate-2026",
      slug_is_unique: true
    },
    {
      id: "22222222-2222-4222-8222-222222222222",
      fec_candidate_id: "S0GA02002",
      name: "Duplicate Name",
      party: "REP",
      office: "S",
      state: "GA",
      district: null,
      slug: "duplicate-name",
      slug_is_unique: false
    }
  ],
  has_next: true,
  offset: 0,
  limit: 200
};

const CANDIDATE_PAGE_2: CandidateListResponse = {
  items: [
    {
      id: "33333333-3333-4333-8333-333333333333",
      fec_candidate_id: "P0US00003",
      name: "Solo Runner",
      party: "IND",
      office: "P",
      state: "US",
      district: null,
      slug: "solo-runner-2026",
      slug_is_unique: true
    }
  ],
  has_next: false,
  offset: 200,
  limit: 200
};

const COMMITTEE_PAGE_1: CommitteeListResponse = {
  items: [
    {
      id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      fec_committee_id: "C00000001",
      name: "Citizens for Civibus",
      committee_type: "O",
      party: "DEM",
      state: "NC",
      slug: "citizens-for-civibus-2026",
      slug_is_unique: true
    }
  ],
  has_next: false,
  offset: 0,
  limit: 200
};

// Mock $env/dynamic/public before importing the handler
vi.mock("$env/dynamic/public", () => ({
  env: { PUBLIC_ORIGIN: "https://civibus.org" }
}));

// Import after mocks are set up
const { GET } = await import("./+server");

function createRequestEvent(url: string, requestJson: ReturnType<typeof vi.fn>) {
  return {
    url: new URL(url),
    locals: {
      api: { requestJson }
    }
  } as unknown as Parameters<typeof GET>[0];
}

function createPaginatedListRequestJson() {
  return vi.fn((path: string) => {
    if (path.includes("/v1/candidates") && path.includes("offset=200")) {
      return Promise.resolve(CANDIDATE_PAGE_2);
    }
    if (path.includes("/v1/candidates")) {
      return Promise.resolve(CANDIDATE_PAGE_1);
    }
    if (path.includes("/v1/committees")) {
      return Promise.resolve(COMMITTEE_PAGE_1);
    }
    throw new Error(`Unexpected API call: ${path}`);
  });
}

function createEmptyListRequestJson() {
  return vi.fn((path: string) => {
    if (path.includes("/v1/candidates")) {
      return Promise.resolve({ items: [], has_next: false, offset: 0, limit: 200 });
    }
    if (path.includes("/v1/committees")) {
      return Promise.resolve({ items: [], has_next: false, offset: 0, limit: 200 });
    }
    throw new Error(`Unexpected API call: ${path}`);
  });
}

describe("GET /sitemap.xml", () => {
  it("walks paginated candidate and committee lists and emits valid sitemap XML", async () => {
    const requestJson = createPaginatedListRequestJson();

    const response = await GET(createRequestEvent("https://civibus.org/sitemap.xml", requestJson));

    // Correct Content-Type
    expect(response.headers.get("Content-Type")).toBe("application/xml");

    const xml = await response.text();

    // Valid XML envelope
    expect(xml).toContain('<?xml version="1.0" encoding="UTF-8"?>');
    expect(xml).toContain('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">');
    expect(xml).toContain("</urlset>");

    // Static pages
    expect(xml).toContain("<loc>https://civibus.org/</loc>");
    expect(xml).toContain("<loc>https://civibus.org/candidates</loc>");
    expect(xml).toContain("<loc>https://civibus.org/committees</loc>");

    // Detail URLs are sourced through shared href builders, not duplicated literals.
    const expectedCandidateLocs = [...CANDIDATE_PAGE_1.items, ...CANDIDATE_PAGE_2.items].map(
      (candidate) => `<loc>https://civibus.org${buildCandidateHref(candidate)}</loc>`
    );
    const expectedCommitteeLocs = COMMITTEE_PAGE_1.items.map(
      (committee) => `<loc>https://civibus.org${buildCommitteeHref(committee)}</loc>`
    );

    for (const loc of [...expectedCandidateLocs, ...expectedCommitteeLocs]) {
      expect(xml).toContain(loc);
    }
  });

  it("paginates candidates across multiple API calls", async () => {
    const requestJson = createPaginatedListRequestJson();

    await GET(createRequestEvent("https://civibus.org/sitemap.xml", requestJson));

    // Should have called candidates twice (page 1 + page 2) and committees once
    const candidateCalls = requestJson.mock.calls.filter(
      (call) => typeof call[0] === "string" && call[0].includes("/v1/candidates")
    );
    const committeeCalls = requestJson.mock.calls.filter(
      (call) => typeof call[0] === "string" && call[0].includes("/v1/committees")
    );

    expect(candidateCalls).toHaveLength(2);
    expect(committeeCalls).toHaveLength(1);

    const firstCandidateCall = new URL(candidateCalls[0]?.[0] ?? "", "https://civibus.org");
    const secondCandidateCall = new URL(candidateCalls[1]?.[0] ?? "", "https://civibus.org");
    const firstCommitteeCall = new URL(committeeCalls[0]?.[0] ?? "", "https://civibus.org");

    expect(firstCandidateCall.searchParams.get("limit")).toBe("200");
    expect(firstCandidateCall.searchParams.get("offset")).toBe("0");
    expect(secondCandidateCall.searchParams.get("limit")).toBe("200");
    expect(secondCandidateCall.searchParams.get("offset")).toBe("200");
    expect(firstCommitteeCall.searchParams.get("limit")).toBe("200");
    expect(firstCommitteeCall.searchParams.get("offset")).toBe("0");
  });

  it("falls back to event URL origin when PUBLIC_ORIGIN is absent", async () => {
    // Reset module registry so +server.ts re-imports the env mock
    vi.resetModules();
    vi.doMock("$env/dynamic/public", () => ({
      env: { PUBLIC_ORIGIN: "" }
    }));

    const freshModule = await import("./+server");

    const requestJson = createEmptyListRequestJson();

    const response = await freshModule.GET(
      createRequestEvent("https://dev.civibus.local/sitemap.xml", requestJson)
    );

    const xml = await response.text();

    // Should use the event URL origin as fallback
    expect(xml).toContain("<loc>https://dev.civibus.local/</loc>");
    expect(xml).not.toContain("civibus.org");
  });
});
