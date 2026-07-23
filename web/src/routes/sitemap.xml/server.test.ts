import { afterEach, describe, expect, it, vi } from "vitest";
import {
  buildCandidateHref,
  buildCommitteeHref,
  type CandidateListResponse,
  type CommitteeListResponse
} from "$lib/campaign-finance-detail/contract";
import {
  buildElectionDateRoutePath,
  type CongressMemberSummary,
  type UpcomingElectionTimelineEntry
} from "$lib/civic-detail/contract";

const personIndexabilityState = vi.hoisted(() => ({
  isIndexable: false
}));
const civicDetailMockState = vi.hoisted(() => ({
  fetchCongressMembers: undefined as ((api: any) => Promise<any>) | undefined,
  fetchUpcomingElectionTimeline: undefined as ((api: any) => Promise<any>) | undefined
}));
const STATIC_PATHS = ["/", "/congress", "/candidates", "/committees", "/coverage", "/calendar", "/data-sources"];

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

const UPCOMING_TIMELINE: UpcomingElectionTimelineEntry[] = [
  {
    date: "2026-11-03",
    contests: []
  },
  {
    date: "2027-03-09",
    contests: []
  }
];

const CONGRESS_MEMBERS: CongressMemberSummary[] = [
  {
    person_id: "44444444-4444-4444-8444-444444444444",
    person_name: "Ada Representative",
    officeholding_id: "55555555-5555-4555-8555-555555555555",
    office_id: "66666666-6666-4666-8666-666666666666",
    office_name: "U.S. Representative for North Carolina's 4th congressional district",
    chamber: "House",
    state: "NC",
    district: "04",
    district_or_class: "04",
    party: "Democratic",
    portrait_source_image_url: null,
    person_detail_path: "/person/44444444-4444-4444-8444-444444444444"
  },
  {
    person_id: "77777777-7777-4777-8777-777777777777",
    person_name: "Ben Senator",
    officeholding_id: "88888888-8888-4888-8888-888888888888",
    office_id: "99999999-9999-4999-8999-999999999999",
    office_name: "U.S. Senator for Georgia",
    chamber: "Senate",
    state: "GA",
    district: null,
    district_or_class: "Class II",
    party: "Republican",
    portrait_source_image_url: null,
    person_detail_path: "/person/77777777-7777-4777-8777-777777777777"
  }
];

vi.mock("$env/dynamic/public", () => ({
  env: { PUBLIC_ORIGIN: "https://civibus.org" }
}));

vi.mock("$lib/seo/person_indexability", () => ({
  PERSON_ROUTE_HAS_SSR_RICH_CONTENT: personIndexabilityState.isIndexable,
  PERSON_ROUTE_INDEXABILITY: {
    get hasSsrRichContent() {
      return personIndexabilityState.isIndexable;
    },
    get isIndexable() {
      return personIndexabilityState.isIndexable;
    },
    get robots() {
      return personIndexabilityState.isIndexable ? null : "noindex";
    }
  }
}));

vi.mock("$lib/server/api/civic-detail", async (importOriginal) => {
  const actual = (await importOriginal()) as typeof import("$lib/server/api/civic-detail");
  return {
    ...actual,
    fetchCongressMembers(api: any) {
      return civicDetailMockState.fetchCongressMembers === undefined
        ? actual.fetchCongressMembers(api)
        : civicDetailMockState.fetchCongressMembers(api);
    },
    fetchUpcomingElectionTimeline(api: any) {
      return civicDetailMockState.fetchUpcomingElectionTimeline === undefined
        ? actual.fetchUpcomingElectionTimeline(api)
        : civicDetailMockState.fetchUpcomingElectionTimeline(api);
    }
  };
});

const { GET } = await import("./+server");

afterEach(() => {
  personIndexabilityState.isIndexable = false;
  civicDetailMockState.fetchCongressMembers = undefined;
  civicDetailMockState.fetchUpcomingElectionTimeline = undefined;
});

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
    if (path.includes("/v1/elections/timeline/upcoming")) {
      return Promise.resolve(UPCOMING_TIMELINE);
    }
    if (path.includes("/v1/congress/members")) {
      return Promise.resolve(CONGRESS_MEMBERS);
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
    if (path.includes("/v1/elections/timeline/upcoming")) {
      return Promise.resolve([]);
    }
    if (path.includes("/v1/congress/members")) {
      return Promise.resolve(CONGRESS_MEMBERS);
    }
    throw new Error(`Unexpected API call: ${path}`);
  });
}

function extractLocPaths(xml: string): string[] {
  return [...xml.matchAll(/<loc>https:\/\/civibus\.org([^<]*)<\/loc>/g)].map((match) => match[1]!);
}

function extractPersonLocPaths(xml: string): string[] {
  return extractLocPaths(xml).filter((path) => path.startsWith("/person/"));
}

function createDeferredPromise<T>() {
  let resolvePromise: (value: T | PromiseLike<T>) => void = () => undefined;
  let rejectPromise: (reason?: unknown) => void = () => undefined;
  const promise = new Promise<T>((resolve, reject) => {
    resolvePromise = resolve;
    rejectPromise = reject;
  });
  return {
    promise,
    resolve: resolvePromise,
    reject: rejectPromise
  };
}

describe("GET /sitemap.xml", () => {
  it("walks paginated candidate and committee lists and emits valid sitemap XML", async () => {
    const requestJson = createPaginatedListRequestJson();

    const response = await GET(createRequestEvent("https://civibus.org/sitemap.xml", requestJson));

    expect(response.headers.get("Content-Type")).toBe("application/xml");

    const xml = await response.text();

    expect(xml).toContain('<?xml version="1.0" encoding="UTF-8"?>');
    expect(xml).toContain('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">');
    expect(xml).toContain("</urlset>");

    expect(extractLocPaths(xml).slice(0, STATIC_PATHS.length)).toEqual(STATIC_PATHS);

    const expectedCandidateLocs = [...CANDIDATE_PAGE_1.items, ...CANDIDATE_PAGE_2.items].map(
      (candidate) => `<loc>https://civibus.org${buildCandidateHref(candidate)}</loc>`
    );
    const expectedCommitteeLocs = COMMITTEE_PAGE_1.items.map(
      (committee) => `<loc>https://civibus.org${buildCommitteeHref(committee)}</loc>`
    );

    for (const loc of [...expectedCandidateLocs, ...expectedCommitteeLocs]) {
      expect(xml).toContain(loc);
    }

    const expectedElectionLocs = UPCOMING_TIMELINE.map(
      (entry) => `<loc>https://civibus.org${buildElectionDateRoutePath(entry.date)}</loc>`
    );
    for (const loc of expectedElectionLocs) {
      expect(xml).toContain(loc);
    }

    expect(extractPersonLocPaths(xml)).toEqual([]);
  });

  it("emits every Congress member person path when person routes are indexable", async () => {
    vi.resetModules();
    personIndexabilityState.isIndexable = true;
    const fetchCongressMembers = vi.fn((api) => api.requestJson("/v1/congress/members"));
    civicDetailMockState.fetchCongressMembers = fetchCongressMembers;
    const moduleUnderTest = await import("./+server");
    const requestJson = createEmptyListRequestJson();

    const response = await moduleUnderTest.GET(
      createRequestEvent("https://civibus.org/sitemap.xml", requestJson)
    );
    const xml = await response.text();

    const expectedPersonPaths = CONGRESS_MEMBERS.map((member) => member.person_detail_path);
    expect(fetchCongressMembers).toHaveBeenCalledTimes(1);
    expect(extractPersonLocPaths(xml)).toHaveLength(expectedPersonPaths.length);
    expect(extractPersonLocPaths(xml)).toEqual(expectedPersonPaths);
  });

  it("derives Congress member paths from encoded person ids instead of trusting upstream paths", async () => {
    vi.resetModules();
    personIndexabilityState.isIndexable = true;
    civicDetailMockState.fetchCongressMembers = vi.fn(() =>
      Promise.resolve([
        {
          ...CONGRESS_MEMBERS[0],
          person_id: "person/with?path#syntax",
          person_detail_path: "//attacker.example/injected"
        }
      ])
    );
    const moduleUnderTest = await import("./+server");
    const requestJson = createEmptyListRequestJson();

    const response = await moduleUnderTest.GET(
      createRequestEvent("https://civibus.org/sitemap.xml", requestJson)
    );
    const xml = await response.text();

    expect(extractPersonLocPaths(xml)).toEqual(["/person/person%2Fwith%3Fpath%23syntax"]);
    expect(xml).not.toContain("attacker.example");
    expect(xml).not.toContain("/injected");
  });

  it("omits Congress member person paths while person routes are not indexable", async () => {
    const requestJson = createPaginatedListRequestJson();

    const response = await GET(createRequestEvent("https://civibus.org/sitemap.xml", requestJson));
    const xml = await response.text();

    const congressMemberCalls = requestJson.mock.calls.filter(
      (call) => typeof call[0] === "string" && call[0].includes("/v1/congress/members")
    );
    expect(congressMemberCalls).toHaveLength(0);
    expect(extractPersonLocPaths(xml)).toHaveLength(0);
  });

  it("paginates candidates across multiple API calls", async () => {
    const requestJson = createPaginatedListRequestJson();

    await GET(createRequestEvent("https://civibus.org/sitemap.xml", requestJson));

    const candidateCalls = requestJson.mock.calls.filter(
      (call) => typeof call[0] === "string" && call[0].includes("/v1/candidates")
    );
    const committeeCalls = requestJson.mock.calls.filter(
      (call) => typeof call[0] === "string" && call[0].includes("/v1/committees")
    );
    const timelineCalls = requestJson.mock.calls.filter(
      (call) => typeof call[0] === "string" && call[0].includes("/v1/elections/timeline/upcoming")
    );

    expect(candidateCalls).toHaveLength(2);
    expect(committeeCalls).toHaveLength(1);
    expect(timelineCalls).toHaveLength(1);

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

    expect(xml).toContain("<loc>https://dev.civibus.local/</loc>");
    expect(xml).not.toContain("civibus.org");
  });

  it("rejects when candidate or committee API pagination fails", async () => {
    const upstreamError = new Error("upstream list API unavailable");
    const requestJson = vi.fn((path: string) => {
      if (path.includes("/v1/candidates") && path.includes("offset=200")) {
        return Promise.reject(upstreamError);
      }
      if (path.includes("/v1/candidates")) {
        return Promise.resolve(CANDIDATE_PAGE_1);
      }
      if (path.includes("/v1/committees")) {
        return Promise.resolve(COMMITTEE_PAGE_1);
      }
      if (path.includes("/v1/elections/timeline/upcoming")) {
        return Promise.resolve([]);
      }
      throw new Error(`Unexpected API call: ${path}`);
    });

    await expect(GET(createRequestEvent("https://civibus.org/sitemap.xml", requestJson))).rejects.toThrow(
      upstreamError
    );
  });

  it("rejects when pagination returns a non-positive page size", async () => {
    const requestJson = vi.fn((path: string) => {
      if (path.includes("/v1/candidates")) {
        return Promise.resolve({ items: [], has_next: true, offset: 0, limit: 0 });
      }
      if (path.includes("/v1/committees")) {
        return Promise.resolve(COMMITTEE_PAGE_1);
      }
      if (path.includes("/v1/elections/timeline/upcoming")) {
        return Promise.resolve(UPCOMING_TIMELINE);
      }
      throw new Error(`Unexpected API call: ${path}`);
    });

    await expect(GET(createRequestEvent("https://civibus.org/sitemap.xml", requestJson))).rejects.toThrow(
      "Sitemap pagination requires a positive integer page size."
    );
  });

  it("rejects when timeline fetch fails", async () => {
    const timelineError = new Error("timeline unavailable");
    const requestJson = vi.fn((path: string) => {
      if (path.includes("/v1/candidates") && path.includes("offset=200")) {
        return Promise.resolve(CANDIDATE_PAGE_2);
      }
      if (path.includes("/v1/candidates")) {
        return Promise.resolve(CANDIDATE_PAGE_1);
      }
      if (path.includes("/v1/committees")) {
        return Promise.resolve(COMMITTEE_PAGE_1);
      }
      if (path.includes("/v1/elections/timeline/upcoming")) {
        return Promise.reject(timelineError);
      }
      throw new Error(`Unexpected API call: ${path}`);
    });

    await expect(
      GET(createRequestEvent("https://civibus.org/sitemap.xml", requestJson))
    ).rejects.toThrow(timelineError);
  });

  it("starts timeline fetch before candidate pagination completes", async () => {
    vi.resetModules();
    const candidateSecondPage = createDeferredPromise<CandidateListResponse>();
    const timelineResponse = createDeferredPromise<UpcomingElectionTimelineEntry[]>();

    const requestJson = vi.fn((path: string) => {
      if (path.includes("/v1/candidates") && path.includes("offset=200")) {
        return candidateSecondPage.promise;
      }
      if (path.includes("/v1/candidates")) {
        return Promise.resolve(CANDIDATE_PAGE_1);
      }
      if (path.includes("/v1/committees")) {
        return Promise.resolve(COMMITTEE_PAGE_1);
      }
      throw new Error(`Unexpected API call: ${path}`);
    });

    const fetchUpcomingElectionTimeline = vi.fn(() => timelineResponse.promise);
    civicDetailMockState.fetchUpcomingElectionTimeline = fetchUpcomingElectionTimeline;
    const moduleUnderTest = await import("./+server");
    const responsePromise = moduleUnderTest.GET(
      createRequestEvent("https://civibus.org/sitemap.xml", requestJson)
    );

    await Promise.resolve();

    try {
      expect(fetchUpcomingElectionTimeline).toHaveBeenCalledTimes(1);
    } finally {
      candidateSecondPage.resolve(CANDIDATE_PAGE_2);
      timelineResponse.resolve(UPCOMING_TIMELINE);
      await responsePromise;
    }
  });

  it("sources timeline entries through fetchUpcomingElectionTimeline", async () => {
    const requestJson = vi.fn((path: string) => {
      if (path.includes("/v1/candidates")) {
        return Promise.resolve({ items: [], has_next: false, offset: 0, limit: 200 });
      }
      if (path.includes("/v1/committees")) {
        return Promise.resolve({ items: [], has_next: false, offset: 0, limit: 200 });
      }
      throw new Error(`Unexpected API call: ${path}`);
    });

    const fetchUpcomingElectionTimeline = vi.fn(() => Promise.resolve(UPCOMING_TIMELINE));
    vi.resetModules();
    civicDetailMockState.fetchUpcomingElectionTimeline = fetchUpcomingElectionTimeline;
    const moduleUnderTest = await import("./+server");

    const response = await moduleUnderTest.GET(
      createRequestEvent("https://civibus.org/sitemap.xml", requestJson)
    );
    const xml = await response.text();

    expect(fetchUpcomingElectionTimeline).toHaveBeenCalledTimes(1);
    expect(xml).toContain(
      `<loc>https://civibus.org${buildElectionDateRoutePath(UPCOMING_TIMELINE[0]!.date)}</loc>`
    );
  });
});
