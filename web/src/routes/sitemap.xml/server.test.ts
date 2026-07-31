import { afterEach, describe, expect, it, vi } from "vitest";
import {
  buildCandidateHref,
  buildCommitteeHref,
  hasCanonicalCandidateSlug,
  type CandidateListItem,
  type CandidateListResponse,
  type CommitteeListResponse
} from "$lib/campaign-finance-detail/contract";
import {
  buildElectionDateRoutePath,
  type CongressMemberSummary,
  type UpcomingElectionTimelineEntry
} from "$lib/civic-detail/contract";
import { buildEntityRouteHref } from "$lib/entity-detail/contract";
import { CANDIDATE_ROUTE_INDEXABILITY } from "$lib/seo/candidate_indexability";
import { PERSON_ROUTE_INDEXABILITY } from "$lib/seo/person_indexability";

const personIndexabilityState = vi.hoisted(() => ({
  isIndexable: false
}));
const civicDetailMockState = vi.hoisted(() => ({
  fetchCongressMembers: undefined as ((api: any) => Promise<any>) | undefined,
  fetchUpcomingElectionTimeline: undefined as ((api: any) => Promise<any>) | undefined
}));
const STATIC_PATHS = ["/", "/congress", "/candidates", "/committees", "/coverage", "/calendar", "/data-sources"];
const SITEMAP_PAGE_CONCURRENCY = 6;
const SITEMAP_PROTOCOL_NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9";
const PLANNED_CANDIDATE_SHARD_KIND = "candidate";
const KNOWN_ANSWER_CANDIDATE_SHARD_PATH = `/sitemap-${PLANNED_CANDIDATE_SHARD_KIND}-0.xml`;
const KNOWN_ANSWER_CANDIDATE_SHARD_URL = `https://civibus.org${KNOWN_ANSWER_CANDIDATE_SHARD_PATH}`;
const PLANNED_CANDIDATE_SHARD_PATH = new RegExp(
  `^/sitemap-${PLANNED_CANDIDATE_SHARD_KIND}-\\d+\\.xml$`
);

const CANDIDATE_PAGE_1: CandidateListResponse = {
  items: [
    {
      id: "11111111-1111-4111-8111-111111111111",
      fec_candidate_id: "H0NC01001",
      name: "Rich Candidate",
      party: "DEM",
      office: "H",
      state: "NC",
      district: "01",
      slug: "pat-candidate-2026",
      slug_is_unique: true,
      identity_is_safe: true,
      has_official_total: true
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
      slug_is_unique: false,
      identity_is_safe: true,
      has_official_total: true
    },
    {
      id: "55555555-5555-4555-8555-555555555555",
      fec_candidate_id: "H0TX05005",
      name: "212 N HALF  W. JOHN, RODNEY HOWARD MR.",
      party: "DEM",
      office: "H",
      state: "TX",
      district: "05",
      slug: "212-n-half-w-john-rodney-howard-mr",
      slug_is_unique: true,
      identity_is_safe: false,
      has_official_total: true
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
      name: "Out-of-Cycle Official Total Candidate",
      party: "IND",
      office: "P",
      state: "US",
      district: null,
      slug: "solo-runner-2026",
      slug_is_unique: true,
      identity_is_safe: true,
      has_official_total: true
    },
    {
      id: "66666666-6666-4666-8666-666666666666",
      fec_candidate_id: "H0NC06006",
      name: "!!!",
      party: "IND",
      office: "H",
      state: "NC",
      district: "06",
      slug: "",
      slug_is_unique: true,
      identity_is_safe: false,
      has_official_total: false
    },
    {
      id: "77777777-7777-4777-8777-777777777777",
      fec_candidate_id: "H0NC07007",
      name: "Thin Canonical Candidate",
      party: "IND",
      office: "H",
      state: "NC",
      district: "07",
      slug: "thin-canonical-candidate",
      slug_is_unique: true,
      identity_is_safe: true,
      has_official_total: false
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
  has_next: true,
  offset: 0,
  limit: 200
};

const COMMITTEE_PAGE_2: CommitteeListResponse = {
  items: [
    {
      id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      fec_committee_id: "C00000002",
      name: "Future Forward Civibus",
      committee_type: "P",
      party: null,
      state: "GA",
      slug: "future-forward-civibus-2026",
      slug_is_unique: true
    }
  ],
  has_next: true,
  offset: 200,
  limit: 200
};

const COMMITTEE_PAGE_3: CommitteeListResponse = {
  items: [
    {
      id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
      fec_committee_id: "C00000003",
      name: "Local Civibus Committee",
      committee_type: "N",
      party: "IND",
      state: "TX",
      slug: "local-civibus-committee",
      slug_is_unique: false
    }
  ],
  has_next: false,
  offset: 400,
  limit: 200
};

const TERMINAL_COMMITTEE_PAGE: CommitteeListResponse = {
  ...COMMITTEE_PAGE_1,
  has_next: false
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
const { GET: GET_STATIC_SITEMAP } = await import("../sitemap-static.xml/+server");
const { GET: GET_KIND_SITEMAP } = await import("../sitemap-[kind]-[page].xml/+server");

afterEach(() => {
  personIndexabilityState.isIndexable = false;
  civicDetailMockState.fetchCongressMembers = undefined;
  civicDetailMockState.fetchUpcomingElectionTimeline = undefined;
});

function createRequestEvent(
  url: string,
  requestJson: ReturnType<typeof vi.fn>,
  params: Record<string, string> = {}
) {
  return {
    url: new URL(url),
    params,
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
      const offset = extractOffset(path);
      return Promise.resolve(
        offset === 0
          ? CANDIDATE_PAGE_1
          : { items: [], has_next: false, offset, limit: 200 }
      );
    }
    if (path.includes("/v1/committees")) {
      if (path.includes("offset=400")) {
        return Promise.resolve(COMMITTEE_PAGE_3);
      }
      if (path.includes("offset=200")) {
        return Promise.resolve(COMMITTEE_PAGE_2);
      }
      const offset = extractOffset(path);
      return Promise.resolve(
        offset === 0
          ? COMMITTEE_PAGE_1
          : { items: [], has_next: false, offset, limit: 200 }
      );
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
      const offset = extractOffset(path);
      return Promise.resolve({ items: [], has_next: false, offset, limit: 200 });
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

function extractSitemapIndexLocUrls(xml: string): string[] {
  if (!/<sitemapindex(?:\s|>)/.test(xml)) {
    return [];
  }
  return [...xml.matchAll(/<sitemap\b[^>]*>[\s\S]*?<loc>([^<]+)<\/loc>[\s\S]*?<\/sitemap>/g)].map(
    (match) => match[1]!
  );
}

function extractPersonLocPaths(xml: string): string[] {
  return extractLocPaths(xml).filter((path) => path.startsWith("/person/"));
}

function extractCandidateLocPaths(xml: string): string[] {
  return extractLocPaths(xml).filter((path) => path.startsWith("/candidate/"));
}

function extractOffset(path: string): number {
  return Number(new URL(path, "https://civibus.org").searchParams.get("offset") ?? "0");
}

function requestedOffsets(requestJson: ReturnType<typeof vi.fn>, pathFragment: string): number[] {
  return requestJson.mock.calls
    .map((call) => String(call[0]))
    .filter((path) => path.includes(pathFragment))
    .map(extractOffset);
}

function expectSitemapProtocolRoot(xml: string, rootElement: "sitemapindex" | "urlset"): void {
  const rootMatch = xml.match(new RegExp(`^(?:<\\?xml[^>]*>\\s*)?<${rootElement}\\b([^>]*)>`));

  expect(rootMatch).not.toBeNull();
  expect(rootMatch?.[1]).toMatch(
    new RegExp(`\\sxmlns=(["'])${SITEMAP_PROTOCOL_NAMESPACE.replaceAll(".", "\\.")}\\1(?:\\s|$)`)
  );
}

function assertBoundedSitemapIndex(params: {
  indexXml: string;
  shardXmlByUrl: ReadonlyMap<string, string>;
  expectedLegacyPaths: ReadonlySet<string>;
  maximumUrlCount: number;
}): void {
  const { indexXml, shardXmlByUrl, expectedLegacyPaths, maximumUrlCount } = params;
  const shardUrls = extractSitemapIndexLocUrls(indexXml);

  expectSitemapProtocolRoot(indexXml, "sitemapindex");
  expect(indexXml).toMatch(/<\/sitemapindex>\s*$/);
  expect(shardUrls).toHaveLength(new Set(shardUrls).size);
  expect(new Set(shardUrls)).toEqual(new Set(shardXmlByUrl.keys()));

  const allPaths: string[] = [];
  for (const shardUrl of shardUrls) {
    const shardXml = shardXmlByUrl.get(shardUrl);
    expect(shardXml, `missing XML for declared shard ${shardUrl}`).toBeDefined();
    expectSitemapProtocolRoot(shardXml!, "urlset");
    expect(shardXml).toMatch(/<\/urlset>\s*$/);
    expect(shardXml).not.toMatch(/<sitemapindex(?:\s|>)/);

    const shardPaths = extractLocPaths(shardXml!);
    expect(shardPaths).toHaveLength([...shardXml!.matchAll(/<url(?:\s|>)/g)].length);
    expect(shardPaths.length).toBeLessThanOrEqual(maximumUrlCount);
    expect(shardPaths).toHaveLength(new Set(shardPaths).size);
    allPaths.push(...shardPaths);
  }

  expect(allPaths).toHaveLength(new Set(allPaths).size);
  expect(new Set(allPaths)).toEqual(expectedLegacyPaths);
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

async function waitForQueuedPromises(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}

async function expectXmlResponse(response: Response): Promise<string> {
  expect(response.status).toBe(200);
  expect(response.headers.get("Content-Type")).toBe("application/xml");
  expect(response.headers.get("Cache-Control")).toBe("public, max-age=900");
  return response.text();
}

async function collectDeclaredShardXml(
  indexXml: string,
  requestJson: ReturnType<typeof vi.fn>
): Promise<Map<string, string>> {
  const shardXmlByUrl = new Map<string, string>();
  for (const shardUrl of extractSitemapIndexLocUrls(indexXml)) {
    const { pathname } = new URL(shardUrl);
    const response =
      pathname === "/sitemap-static.xml"
        ? await GET_STATIC_SITEMAP(createRequestEvent(shardUrl, requestJson))
        : await GET_KIND_SITEMAP(
            createRequestEvent(shardUrl, requestJson, extractShardParams(pathname))
          );
    shardXmlByUrl.set(shardUrl, await expectXmlResponse(response));
  }
  return shardXmlByUrl;
}

function extractShardParams(pathname: string): Record<string, string> {
  const match = pathname.match(/^\/sitemap-([a-z]+)-(\d+)\.xml$/);
  if (match === null) {
    throw new Error(`Unexpected shard URL in test: ${pathname}`);
  }
  return { kind: match[1]!, page: match[2]! };
}

function expectedKnownAnswerPaths(includePeople: boolean): Set<string> {
  const allCandidateItems = [...CANDIDATE_PAGE_1.items, ...CANDIDATE_PAGE_2.items];
  const expectedCandidatePaths = allCandidateItems
    .filter(
      (item) =>
        hasCanonicalCandidateSlug(item) && CANDIDATE_ROUTE_INDEXABILITY.isIndexable(item)
    )
    .map((item) => buildCandidateHref(item));
  const expectedCommitteePaths = [
    ...COMMITTEE_PAGE_1.items,
    ...COMMITTEE_PAGE_2.items,
    ...COMMITTEE_PAGE_3.items
  ].map((item) => buildCommitteeHref(item));
  const expectedElectionPaths = UPCOMING_TIMELINE.map((entry) =>
    buildElectionDateRoutePath(entry.date)
  );
  const expectedPersonPaths = includePeople
    ? CONGRESS_MEMBERS.flatMap((member) => {
        const path = buildEntityRouteHref("person", member.person_id);
        return path === null ? [] : [path];
      })
    : [];
  return new Set([
    ...STATIC_PATHS,
    ...expectedCandidatePaths,
    ...expectedCommitteePaths,
    ...expectedElectionPaths,
    ...expectedPersonPaths
  ]);
}

function createShardDiscoveryRequestJson(maxCandidateOffset: number, maxCommitteeOffset: number) {
  return vi.fn((path: string) => {
    const offset = extractOffset(path);
    if (path.includes("/v1/candidates")) {
      return Promise.resolve({
        items: offset <= maxCandidateOffset ? [CANDIDATE_PAGE_1.items[0]!] : [],
        has_next: offset < maxCandidateOffset,
        offset,
        limit: 200
      });
    }
    if (path.includes("/v1/committees")) {
      return Promise.resolve({
        items: offset <= maxCommitteeOffset ? [COMMITTEE_PAGE_1.items[0]!] : [],
        has_next: offset < maxCommitteeOffset,
        offset,
        limit: 200
      });
    }
    if (path.includes("/v1/elections/timeline/upcoming")) {
      return Promise.resolve(UPCOMING_TIMELINE);
    }
    throw new Error(`Unexpected API call: ${path}`);
  });
}

describe("GET /sitemap.xml bounded sitemap index", () => {
  it("serves a default-namespace sitemap index and exact bounded shard union", async () => {
    vi.resetModules();
    personIndexabilityState.isIndexable = true;
    civicDetailMockState.fetchCongressMembers = vi.fn(() => Promise.resolve(CONGRESS_MEMBERS));
    const moduleUnderTest = await import("./+server");
    const requestJson = createPaginatedListRequestJson();

    const indexResponse = await moduleUnderTest.GET(
      createRequestEvent("https://civibus.org/sitemap.xml", requestJson)
    );
    const indexXml = await expectXmlResponse(indexResponse);
    const shardXmlByUrl = await collectDeclaredShardXml(indexXml, requestJson);

    assertBoundedSitemapIndex({
      indexXml,
      shardXmlByUrl,
      expectedLegacyPaths: expectedKnownAnswerPaths(true),
      maximumUrlCount: 10_000
    });
    expect(extractSitemapIndexLocUrls(indexXml).map((loc) => new URL(loc).pathname)).toEqual([
      "/sitemap-static.xml",
      "/sitemap-candidate-0.xml",
      "/sitemap-committee-0.xml",
      "/sitemap-person-0.xml"
    ]);
  });

  it("discovers candidate and committee shard ranges with bounded offset probes", async () => {
    const requestJson = createShardDiscoveryRequestJson(20_000, 30_000);

    const response = await GET(createRequestEvent("https://civibus.org/sitemap.xml", requestJson));
    const xml = await expectXmlResponse(response);
    const shardPaths = extractSitemapIndexLocUrls(xml).map((loc) => new URL(loc).pathname);
    const candidateOffsets = requestedOffsets(requestJson, "/v1/candidates");
    const committeeOffsets = requestedOffsets(requestJson, "/v1/committees");

    expect(shardPaths.filter((path) => path.startsWith("/sitemap-candidate-"))).toEqual([
      "/sitemap-candidate-0.xml",
      "/sitemap-candidate-1.xml",
      "/sitemap-candidate-2.xml"
    ]);
    expect(shardPaths.filter((path) => path.startsWith("/sitemap-committee-"))).toEqual([
      "/sitemap-committee-0.xml",
      "/sitemap-committee-1.xml",
      "/sitemap-committee-2.xml",
      "/sitemap-committee-3.xml"
    ]);
    expect(candidateOffsets.length).toBeLessThanOrEqual(6);
    expect(committeeOffsets.length).toBeLessThanOrEqual(7);
    expect(candidateOffsets).not.toContain(200);
    expect(committeeOffsets).not.toContain(200);
  });

  it("fetches each candidate shard only inside its requested source window", async () => {
    const requestJson = createShardDiscoveryRequestJson(30_000, 0);

    const response = await GET_KIND_SITEMAP(
      createRequestEvent("https://civibus.org/sitemap-candidate-1.xml", requestJson, {
        kind: "candidate",
        page: "1"
      })
    );

    await expectXmlResponse(response);
    const offsets = requestedOffsets(requestJson, "/v1/candidates");
    expect(offsets).toHaveLength(50);
    expect(Math.min(...offsets)).toBe(10_000);
    expect(Math.max(...offsets)).toBe(19_800);
  });

  it("fetches each committee shard only inside its requested source window", async () => {
    const requestJson = createShardDiscoveryRequestJson(0, 30_000);

    const response = await GET_KIND_SITEMAP(
      createRequestEvent("https://civibus.org/sitemap-committee-1.xml", requestJson, {
        kind: "committee",
        page: "1"
      })
    );

    await expectXmlResponse(response);
    const offsets = requestedOffsets(requestJson, "/v1/committees");
    expect(offsets).toHaveLength(50);
    expect(Math.min(...offsets)).toBe(10_000);
    expect(Math.max(...offsets)).toBe(19_800);
  });

  it("keeps numbered shard URLs in deterministic offset order when pages finish out of order", async () => {
    const deferred = new Map<number, ReturnType<typeof createDeferredPromise<CandidateListResponse>>>();
    const requestJson = vi.fn((path: string) => {
      if (path.includes("/v1/candidates")) {
        const offset = extractOffset(path);
        const page = createDeferredPromise<CandidateListResponse>();
        deferred.set(offset, page);
        return page.promise;
      }
      throw new Error(`Unexpected API call: ${path}`);
    });
    const responsePromise = GET_KIND_SITEMAP(
      createRequestEvent("https://civibus.org/sitemap-candidate-0.xml", requestJson, {
        kind: "candidate",
        page: "0"
      })
    );

    await waitForQueuedPromises();
    deferred.get(200)?.resolve({ ...CANDIDATE_PAGE_2, has_next: false });
    deferred.get(0)?.resolve(CANDIDATE_PAGE_1);
    for (const [offset, page] of deferred) {
      if (offset > 200) {
        page.resolve({ items: [], has_next: false, offset, limit: 200 });
      }
    }

    const response = await responsePromise;
    const xml = await expectXmlResponse(response);
    expect(extractCandidateLocPaths(xml)).toEqual([
      buildCandidateHref(CANDIDATE_PAGE_1.items[0]!),
      buildCandidateHref(CANDIDATE_PAGE_2.items[0]!)
    ]);
  });

  it("rejects invalid shard params, overflowing single shards, and pagination drift", async () => {
    const invalidKindResponse = await GET_KIND_SITEMAP(
      createRequestEvent("https://civibus.org/sitemap-donor-0.xml", createEmptyListRequestJson(), {
        kind: "donor",
        page: "0"
      })
    );
    const invalidPageResponse = await GET_KIND_SITEMAP(
      createRequestEvent("https://civibus.org/sitemap-candidate-1.5.xml", createEmptyListRequestJson(), {
        kind: "candidate",
        page: "1.5"
      })
    );
    expect(invalidKindResponse.status).toBe(404);
    expect(invalidPageResponse.status).toBe(404);

    civicDetailMockState.fetchCongressMembers = vi.fn(() =>
      Promise.resolve(Array.from({ length: 10_001 }, (_, index) => ({
        ...CONGRESS_MEMBERS[0],
        person_id: `person-${index}`
      })))
    );
    personIndexabilityState.isIndexable = true;
    await expect(
      GET_KIND_SITEMAP(
        createRequestEvent("https://civibus.org/sitemap-person-0.xml", createEmptyListRequestJson(), {
          kind: "person",
          page: "0"
        })
      )
    ).rejects.toThrow(/exceeds sitemap shard size/i);

    const driftRequestJson = vi.fn((path: string) => {
      const offset = extractOffset(path);
      return Promise.resolve({ items: [], has_next: false, offset: offset + 1, limit: 199 });
    });
    await expect(
      GET_KIND_SITEMAP(
        createRequestEvent("https://civibus.org/sitemap-candidate-0.xml", driftRequestJson, {
          kind: "candidate",
          page: "0"
        })
      )
    ).rejects.toThrow(/pagination/i);
  });

  it("rejects empty sitemap pages that still claim a next page", async () => {
    const inconsistentRequestJson = vi.fn((path: string) => {
      const offset = extractOffset(path);
      return Promise.resolve({
        items: [],
        has_next: true,
        offset,
        limit: 200
      });
    });

    await expect(
      GET_KIND_SITEMAP(
        createRequestEvent("https://civibus.org/sitemap-candidate-0.xml", inconsistentRequestJson, {
          kind: "candidate",
          page: "0"
        })
      )
    ).rejects.toThrow(/cannot advertise additional pages after an empty result window/i);
  });

  it("rejects non-zero person sitemap shard pages", async () => {
    const response = await GET_KIND_SITEMAP(
      createRequestEvent("https://civibus.org/sitemap-person-1.xml", createEmptyListRequestJson(), {
        kind: "person",
        page: "1"
      })
    );

    expect(response.status).toBe(404);
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
    const moduleUnderTest = await import("../sitemap-[kind]-[page].xml/+server");

    const response = await moduleUnderTest.GET(
      createRequestEvent("https://civibus.org/sitemap-person-0.xml", createEmptyListRequestJson(), {
        kind: "person",
        page: "0"
      })
    );
    const xml = await expectXmlResponse(response);

    expect(extractPersonLocPaths(xml)).toEqual(["/person/person%2Fwith%3Fpath%23syntax"]);
    expect(xml).not.toContain("attacker.example");
    expect(xml).not.toContain("/injected");
  });

  it("falls back to the request origin when PUBLIC_ORIGIN is absent", async () => {
    vi.resetModules();
    vi.doMock("$env/dynamic/public", () => ({
      env: { PUBLIC_ORIGIN: "" }
    }));
    try {
      const indexModule = await import("./+server");
      const staticModule = await import("../sitemap-static.xml/+server");
      const requestJson = createEmptyListRequestJson();

      const indexResponse = await indexModule.GET(
        createRequestEvent("https://dev.civibus.local/sitemap.xml", requestJson)
      );
      const staticResponse = await staticModule.GET(
        createRequestEvent("https://dev.civibus.local/sitemap-static.xml", requestJson)
      );

      const indexXml = await expectXmlResponse(indexResponse);
      const staticXml = await expectXmlResponse(staticResponse);
      expect(indexXml).toContain("<loc>https://dev.civibus.local/sitemap-static.xml</loc>");
      expect(staticXml).toContain("<loc>https://dev.civibus.local/</loc>");
      expect(`${indexXml}\n${staticXml}`).not.toContain("civibus.org");
    } finally {
      vi.doUnmock("$env/dynamic/public");
      vi.resetModules();
    }
  });
});
