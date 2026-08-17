import { afterEach, describe, expect, it, vi } from "vitest";
import {
  buildCandidateHref,
  buildCommitteeHref,
  hasCanonicalCandidateSlug,
  type CandidateListResponse,
  type CommitteeListResponse
} from "$lib/campaign-finance-detail/contract";
import { buildElectionDateRoutePath } from "$lib/civic-detail/contract";
import { buildEntityRouteHref } from "$lib/entity-detail/contract";
import { CANDIDATE_ROUTE_INDEXABILITY } from "$lib/seo/candidate_indexability";
import { PERSON_ROUTE_INDEXABILITY } from "$lib/seo/person_indexability";
import {
  CANDIDATE_PAGE_1,
  CANDIDATE_PAGE_2,
  COMMITTEE_PAGE_1,
  COMMITTEE_PAGE_2,
  COMMITTEE_PAGE_3,
  CONGRESS_MEMBERS,
  TERMINAL_COMMITTEE_PAGE,
  UPCOMING_TIMELINE
} from "./server_test_fixtures";

const personIndexabilityState = vi.hoisted(() => ({
  isIndexable: false
}));
const civicDetailMockState = vi.hoisted(() => ({
  fetchCongressMembers: undefined as ((api: any) => Promise<any>) | undefined,
  fetchUpcomingElectionTimeline: undefined as ((api: any) => Promise<any>) | undefined
}));
const STATIC_PATHS = [
  "/",
  "/congress",
  "/candidates",
  "/committees",
  "/coverage",
  "/calendar",
  "/data-sources",
  "/about",
  "/contact",
  "/privacy"
];
const SITEMAP_PROTOCOL_NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9";

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
const { SITEMAP_API_PAGE_LIMIT, SITEMAP_SHARD_SIZE } = await import("$lib/server/sitemap");

const EXPECTED_SITEMAP_SHARD_SIZE = 7_000;
const EXPECTED_SITEMAP_PAGE_COUNT = SITEMAP_SHARD_SIZE / SITEMAP_API_PAGE_LIMIT;
const EXPECTED_SITEMAP_WAVE_COUNTS = Array.from(
  { length: Math.ceil(EXPECTED_SITEMAP_PAGE_COUNT / 10) },
  (_, index) => Math.min((index + 1) * 10, EXPECTED_SITEMAP_PAGE_COUNT)
);

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
  it("pins committee shard size below the measured latency ceiling", () => {
    // Source: docs/live-state/2026_08_04_donor_search_and_sitemap_live_bounds.md,
    // "Stage 1 Sitemap Evidence" -> sitemap-committee-3.xml served 1,976 <loc>
    // entries in 2.810239 s. That shard has the worst measured seconds-per-entry
    // of the committee shards, so it is the conservative basis for the ceiling.
    const measuredSecondsPerEntry = 2.810239 / 1_976;
    const maximumEntriesBelowTenSeconds = Math.floor(10.0 / measuredSecondsPerEntry);
    const maximumPageAlignedEntries =
      Math.floor(maximumEntriesBelowTenSeconds / SITEMAP_API_PAGE_LIMIT) * SITEMAP_API_PAGE_LIMIT;
    const projectedSecondsAtShardSize = SITEMAP_SHARD_SIZE * measuredSecondsPerEntry;

    expect(SITEMAP_SHARD_SIZE).toBe(EXPECTED_SITEMAP_SHARD_SIZE);
    expect(SITEMAP_SHARD_SIZE % SITEMAP_API_PAGE_LIMIT).toBe(0);
    expect(SITEMAP_SHARD_SIZE).toBeLessThanOrEqual(maximumPageAlignedEntries);
    expect(10.0 - projectedSecondsAtShardSize).toBeGreaterThanOrEqual(0.04);
  });

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
      maximumUrlCount: SITEMAP_SHARD_SIZE
    });
    expect(extractSitemapIndexLocUrls(indexXml).map((loc) => new URL(loc).pathname)).toEqual([
      "/sitemap-static.xml",
      "/sitemap-candidate-0.xml",
      "/sitemap-committee-0.xml",
      "/sitemap-person-0.xml"
    ]);
  });

  it("serves canonical static and election loc entries in declared order", async () => {
    const response = await GET_STATIC_SITEMAP(
      createRequestEvent("https://civibus.org/sitemap-static.xml", createPaginatedListRequestJson())
    );
    const xml = await expectXmlResponse(response);
    const expectedPaths = [
      ...STATIC_PATHS,
      ...UPCOMING_TIMELINE.map((entry) => buildElectionDateRoutePath(entry.date))
    ];

    expect(extractLocPaths(xml)).toEqual(expectedPaths);
    expect([...xml.matchAll(/<loc>(.*?)<\/loc>/g)].map((match) => match[1])).toEqual(
      expectedPaths.map((path) => `https://civibus.org${path}`)
    );
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
      "/sitemap-committee-3.xml",
      "/sitemap-committee-4.xml"
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
    expect(offsets).toHaveLength(EXPECTED_SITEMAP_PAGE_COUNT);
    expect(Math.min(...offsets)).toBe(SITEMAP_SHARD_SIZE);
    expect(Math.max(...offsets)).toBe(2 * SITEMAP_SHARD_SIZE - SITEMAP_API_PAGE_LIMIT);
  });

  it("fetches each committee shard inside its requested source window with bounded latency waves", async () => {
    const deferred = new Map<number, ReturnType<typeof createDeferredPromise<CommitteeListResponse>>>();
    const resolvedOffsets = new Set<number>();
    const requestJson = vi.fn((path: string) => {
      if (!path.includes("/v1/committees")) throw new Error(`Unexpected API call: ${path}`);
      const offset = extractOffset(path);
      const page = createDeferredPromise<CommitteeListResponse>();
      deferred.set(offset, page);
      return page.promise;
    });

    const responsePromise = GET_KIND_SITEMAP(
      createRequestEvent("https://civibus.org/sitemap-committee-1.xml", requestJson, { kind: "committee", page: "1" })
    );

    for (const expectedRequestCount of EXPECTED_SITEMAP_WAVE_COUNTS) {
      await vi.waitFor(() => expect(deferred.size).toBe(expectedRequestCount), {
        interval: 1,
        timeout: 1_000
      });
      for (const [offset, page] of deferred) {
        if (resolvedOffsets.has(offset)) continue;
        resolvedOffsets.add(offset);
        page.resolve({
          items: [COMMITTEE_PAGE_1.items[0]!],
          has_next: offset < 2 * SITEMAP_SHARD_SIZE - SITEMAP_API_PAGE_LIMIT,
          offset,
          limit: SITEMAP_API_PAGE_LIMIT
        });
      }
    }

    const response = await responsePromise;
    await expectXmlResponse(response);
    const offsets = requestedOffsets(requestJson, "/v1/committees");
    expect(offsets).toHaveLength(EXPECTED_SITEMAP_PAGE_COUNT);
    expect(Math.min(...offsets)).toBe(SITEMAP_SHARD_SIZE);
    expect(Math.max(...offsets)).toBe(2 * SITEMAP_SHARD_SIZE - SITEMAP_API_PAGE_LIMIT);
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
