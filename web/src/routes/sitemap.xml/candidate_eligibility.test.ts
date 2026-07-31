import { describe, expect, it, vi } from "vitest";
import {
  buildCandidateHref,
  hasCanonicalCandidateSlug,
  type CandidateListItem
} from "$lib/campaign-finance-detail/contract";

vi.mock("$env/dynamic/public", () => ({
  env: { PUBLIC_ORIGIN: "https://civibus.org" }
}));

const { GET: GET_KIND_SITEMAP } = await import("../sitemap-[kind]-[page].xml/+server");

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
  } as unknown as Parameters<typeof GET_KIND_SITEMAP>[0];
}

function extractLocPaths(xml: string): string[] {
  return [...xml.matchAll(/<loc>https:\/\/civibus\.org([^<]*)<\/loc>/g)].map((match) => match[1]!);
}

function extractCandidateLocPaths(xml: string): string[] {
  return extractLocPaths(xml).filter((path) => path.startsWith("/candidate/"));
}

function extractOffset(path: string): number {
  return Number(new URL(path, "https://civibus.org").searchParams.get("offset") ?? "0");
}

describe("GET /sitemap-candidate-0.xml candidate eligibility known answers", () => {
  const BARE_UUID_CANDIDATE_PATH =
    /^\/candidate\/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

  const CANDIDATE_SAFE_UNIQUE_SLUG: CandidateListItem = {
    id: "11111111-1111-4111-8111-111111111111",
    fec_candidate_id: "H0NC01001",
    name: "Alice Representative",
    party: "DEM",
    office: "H",
    state: "NC",
    district: "01",
    slug: "alice-representative-2026",
    slug_is_unique: true,
    identity_is_safe: true,
    has_official_total: true
  };
  const CANDIDATE_UNSAFE_UNIQUE_SLUG: CandidateListItem = {
    id: "22222222-2222-4222-8222-222222222222",
    fec_candidate_id: "H0TX05005",
    name: "212 N HALF  W. JOHN, RODNEY HOWARD MR.",
    party: "REP",
    office: "H",
    state: "TX",
    district: "05",
    slug: "212-n-half-w-john-rodney-howard-mr",
    slug_is_unique: true,
    identity_is_safe: false,
    has_official_total: true
  };
  const CANDIDATE_SAFE_DUPLICATE_SLUG: CandidateListItem = {
    id: "33333333-3333-4333-8333-333333333333",
    fec_candidate_id: "S0GA02002",
    name: "Duplicate Name",
    party: "DEM",
    office: "S",
    state: "GA",
    district: null,
    slug: "shared-committee-slug",
    slug_is_unique: false,
    identity_is_safe: true,
    has_official_total: true
  };
  const CANDIDATE_SAFE_EMPTY_SLUG: CandidateListItem = {
    id: "44444444-4444-4444-8444-444444444444",
    fec_candidate_id: "P0US00003",
    name: "No Slug Runner",
    party: "IND",
    office: "P",
    state: "US",
    district: null,
    slug: "",
    slug_is_unique: true,
    identity_is_safe: true,
    has_official_total: true
  };
  const CANDIDATE_BARE_UUID_FALLBACK: CandidateListItem = {
    id: "66666666-6666-4666-8666-666666666666",
    fec_candidate_id: "H0NC06006",
    name: "!!!",
    party: "IND",
    office: "H",
    state: "NC",
    district: "06",
    slug: "55555555-5555-4555-8555-555555555555",
    slug_is_unique: true,
    identity_is_safe: false,
    has_official_total: true
  };

  const KNOWN_ANSWER_CANDIDATES: CandidateListItem[] = [
    CANDIDATE_SAFE_UNIQUE_SLUG,
    CANDIDATE_UNSAFE_UNIQUE_SLUG,
    CANDIDATE_SAFE_DUPLICATE_SLUG,
    CANDIDATE_SAFE_EMPTY_SLUG,
    CANDIDATE_BARE_UUID_FALLBACK
  ];

  function oldSlugOnlyCandidatePath(item: CandidateListItem): string {
    const routeId = item.slug_is_unique && item.slug !== "" ? item.slug : item.id;
    return `/candidate/${routeId}`;
  }

  function exclusionReason(
    item: CandidateListItem
  ): "unsafe_identity" | "duplicate_slug" | "empty_slug" | "bare_uuid_fallback" {
    if (BARE_UUID_CANDIDATE_PATH.test(`/candidate/${item.slug}`)) return "bare_uuid_fallback";
    if (!item.identity_is_safe) return "unsafe_identity";
    if (item.slug === "") return "empty_slug";
    return "duplicate_slug";
  }

  function knownAnswerRequestJson() {
    return vi.fn((path: string) => {
      if (path.includes("/v1/candidates")) {
        const offset = extractOffset(path);
        return Promise.resolve({
          items: offset === 0 ? KNOWN_ANSWER_CANDIDATES : [],
          has_next: false,
          offset,
          limit: 200
        });
      }
      throw new Error(`Unexpected API call: ${path}`);
    });
  }

  it("emits only canonical candidate URLs with hand-calculated per-reason exclusion counts", async () => {
    const requestJson = knownAnswerRequestJson();
    const response = await GET_KIND_SITEMAP(
      createRequestEvent("https://civibus.org/sitemap-candidate-0.xml", requestJson, {
        kind: "candidate",
        page: "0"
      })
    );
    const xml = await response.text();

    const eligible = KNOWN_ANSWER_CANDIDATES.filter(hasCanonicalCandidateSlug);
    const excluded = KNOWN_ANSWER_CANDIDATES.filter((item) => !hasCanonicalCandidateSlug(item));
    expect(eligible).toEqual([CANDIDATE_SAFE_UNIQUE_SLUG]);
    expect(
      excluded.reduce<Record<string, number>>((acc, item) => {
        const reason = exclusionReason(item);
        acc[reason] = (acc[reason] ?? 0) + 1;
        return acc;
      }, {})
    ).toEqual({
      unsafe_identity: 1,
      duplicate_slug: 1,
      empty_slug: 1,
      bare_uuid_fallback: 1
    });

    const candidateLocs = extractCandidateLocPaths(xml);
    expect(candidateLocs).toEqual([buildCandidateHref(CANDIDATE_SAFE_UNIQUE_SLUG)]);
    expect(candidateLocs).toEqual(["/candidate/alice-representative-2026"]);
    expect(candidateLocs.filter((loc) => BARE_UUID_CANDIDATE_PATH.test(loc))).toHaveLength(0);
    expect(extractLocPaths(xml)).toHaveLength(1);
  });

  it("rejects the PRE_CANDIDATES - PRE_BARE_UUID proof equation", async () => {
    const requestJson = knownAnswerRequestJson();
    const response = await GET_KIND_SITEMAP(
      createRequestEvent("https://civibus.org/sitemap-candidate-0.xml", requestJson, {
        kind: "candidate",
        page: "0"
      })
    );
    const xml = await response.text();

    const preCandidates = KNOWN_ANSWER_CANDIDATES.length;
    const preBareUuid = KNOWN_ANSWER_CANDIDATES.map(oldSlugOnlyCandidatePath).filter((path) =>
      BARE_UUID_CANDIDATE_PATH.test(path)
    ).length;
    expect(preCandidates).toBe(5);
    expect(preBareUuid).toBe(3);

    const rejectedEquationCandidateCount = preCandidates - preBareUuid;
    const canonicalCandidateCount = KNOWN_ANSWER_CANDIDATES.filter(hasCanonicalCandidateSlug).length;
    const unsafeUniqueSlugGap = KNOWN_ANSWER_CANDIDATES.filter(
      (item) =>
        !item.identity_is_safe &&
        item.slug_is_unique &&
        item.slug !== "" &&
        !BARE_UUID_CANDIDATE_PATH.test(`/candidate/${item.slug}`)
    ).length;
    expect(rejectedEquationCandidateCount).toBe(2);
    expect(canonicalCandidateCount).toBe(1);
    expect(extractCandidateLocPaths(xml)).toHaveLength(canonicalCandidateCount);
    expect(unsafeUniqueSlugGap).toBe(1);
    expect(rejectedEquationCandidateCount - canonicalCandidateCount).toBe(unsafeUniqueSlugGap);
  });
});
