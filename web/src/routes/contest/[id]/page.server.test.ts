import { ApiResponseError } from "$lib/server/api/client";
import type {
  ContestCandidateMoneyResponse,
  ContestDetailResponse
} from "$lib/civic-detail/contract";
import { describe, expect, it, vi } from "vitest";
import { load } from "./+page.server";

const CONTEST_ID = "77777777-7777-4777-8777-777777777777";
const OFFICE_ID = "33333333-3333-4333-8333-333333333333";
const ELECTORAL_DIVISION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const PERSON_ID = "11111111-1111-4111-8111-111111111111";
const CANDIDATE_ID = "22222222-2222-4222-8222-222222222222";
const GEOMETRY_PATH = "/v1/civics/geometry?level=county&state=NC";
const CONTEST_PATH = `/v1/contests/${CONTEST_ID}`;
const MONEY_PATH_2026 = `/v1/contests/${CONTEST_ID}/candidate-money?cycle=2026`;
const INVALID_CYCLE_ERROR = {
  message: "Invalid cycle query parameter.",
  detail: "The cycle query parameter must be a single four-digit election cycle."
};

type LoadResult = {
  contest: ContestDetailResponse;
  geometryByLevel: Record<string, { type: string; features: unknown[] }>;
  contestCandidateMoney: ContestCandidateMoneyResponse | null;
  contestSelectedCycle: number | null;
};

function contestDetail(
  overrides: Partial<ContestDetailResponse> = {}
): ContestDetailResponse {
  return {
    id: CONTEST_ID,
    name: "North Carolina 1st Congressional District — 2026 General Election",
    election_date: "2026-11-03",
    election_type: "general",
    office_id: OFFICE_ID,
    electoral_division_id: ELECTORAL_DIVISION_ID,
    electoral_division_type: "county",
    electoral_division_state: "NC",
    number_of_seats: 1,
    filing_deadline: "2026-09-01",
    is_partisan: true,
    candidate_list_incomplete: false,
    result_winner_candidacy_id: null,
    result_winner_person_id: null,
    result_winner_person_name: null,
    candidacies: [
      {
        candidacy_id: "candidacy-1",
        person_id: PERSON_ID,
        person_name: "Jane Candidate",
        party: "DEM",
        status: "qualified",
        incumbent_challenge: "I"
      }
    ],
    sources: [],
    ...overrides
  };
}

function candidateMoney(selectedCycle = 2026): ContestCandidateMoneyResponse {
  return {
    contest_id: CONTEST_ID,
    selected_cycle: selectedCycle,
    candidate_count: 1,
    total_raised: "5000.00",
    total_ie_support: "100.00",
    total_ie_oppose: "50.00",
    has_unknown_candidate_money: false,
    has_unknown_candidate_ie: false,
    rows: [
      {
        candidacy_id: "candidacy-1",
        person_id: PERSON_ID,
        person_name: "Jane Candidate",
        party: "DEM",
        status: "qualified",
        incumbent_challenge: "I",
        fec_candidate_id: "H0NC01001",
        candidate_id: CANDIDATE_ID,
        candidate_name: "CANDIDATE, JANE",
        candidate_slug: "candidate-jane",
        candidate_slug_is_unique: true,
        candidate_identity_is_safe: true,
        has_fec_money: true,
        total_raised: "5000.00",
        total_spent: "2000.00",
        net: "3000.00",
        cash_on_hand: "1000.00",
        summary_source: "fec_weball",
        fundraising_coverage: null,
        ie_support_total: "100.00",
        ie_oppose_total: "50.00",
        ie_support_count: 1,
        ie_oppose_count: 1,
        ie_coverage: null
      }
    ]
  };
}

function createLoadEvent(
  requestJson: ReturnType<typeof vi.fn>,
  {
    id = CONTEST_ID,
    url = new URL(`https://example.test/contest/${id}`),
    setHeaders = vi.fn()
  }: { id?: string; url?: URL; setHeaders?: ReturnType<typeof vi.fn> } = {}
) {
  return {
    params: { id },
    url,
    setHeaders,
    locals: { api: { requestJson } }
  } as unknown as Parameters<typeof load>[0];
}

describe("/contest/[id] +page.server load", () => {
  it("loads the race with exactly one contest call, one money call, and one geometry call", async () => {
    // The load-bearing assertion of this whole route. Before the batched
    // endpoint the page issued 4N+1 backend calls (a candidate-list call plus a
    // four-call detail bundle per candidacy) and measured 17.96s cold on a
    // 21-candidacy contest. Pinning the exact call list is what keeps a future
    // per-candidate fetch from creeping back in unnoticed.
    const requestJson = vi.fn(async (path: string) => {
      if (path === CONTEST_PATH) return contestDetail();
      if (path === GEOMETRY_PATH) return { type: "FeatureCollection", features: [] };
      if (path === MONEY_PATH_2026) return candidateMoney();
      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as LoadResult;

    const calledPaths = requestJson.mock.calls.map(([path]) => String(path));
    expect(calledPaths.sort()).toEqual([CONTEST_PATH, MONEY_PATH_2026, GEOMETRY_PATH].sort());
    expect(calledPaths).toHaveLength(3);
    expect(data.contest.id).toBe(CONTEST_ID);
    expect(data.geometryByLevel.county.features).toEqual([]);
    expect(data.contestCandidateMoney?.rows[0].total_raised).toBe("5000.00");
    expect(data.contestSelectedCycle).toBe(2026);
    // No graph / entity-resolution / slug side lookups on a race page.
    expect(calledPaths.every((path) => !path.startsWith("/v1/graph/"))).toBe(true);
    expect(calledPaths.every((path) => !path.startsWith("/v1/er/"))).toBe(true);
    expect(calledPaths.every((path) => !path.includes("slug"))).toBe(true);
  });

  it("sets a shared cache-control window so repeat and crawler traffic is not recomputed", async () => {
    const setHeaders = vi.fn();
    const requestJson = vi.fn(async (path: string) => {
      if (path === CONTEST_PATH) return contestDetail();
      if (path === GEOMETRY_PATH) return { type: "FeatureCollection", features: [] };
      if (path === MONEY_PATH_2026) return candidateMoney();
      throw new Error(`unexpected path: ${path}`);
    });

    await load(createLoadEvent(requestJson, { setHeaders }));

    expect(setHeaders).toHaveBeenCalledWith({
      "cache-control": "public, max-age=120, s-maxage=120, stale-while-revalidate=60"
    });
  });

  it("surfaces a failed money fetch instead of rendering it as missing data", async () => {
    // The defect this replaces: every per-candidacy fetch was wrapped in a bare
    // `catch {}` that returned an empty section, so a backend outage rendered as
    // "data is not yet available" and looked identical to a genuine data gap.
    // A guard that cannot fail is not a guard.
    const requestJson = vi.fn(async (path: string) => {
      if (path === CONTEST_PATH) return contestDetail();
      if (path === GEOMETRY_PATH) return { type: "FeatureCollection", features: [] };
      if (path === MONEY_PATH_2026) {
        throw new ApiResponseError(500, "boom");
      }
      throw new Error(`unexpected path: ${path}`);
    });
    const setHeaders = vi.fn();

    await expect(load(createLoadEvent(requestJson, { setHeaders }))).rejects.toMatchObject({
      status: 500,
      body: { message: "boom" }
    });
    expect(requestJson).toHaveBeenCalledTimes(3);
    expect(setHeaders).not.toHaveBeenCalled();
  });

  it("uses the cycle query override when the reader pins one", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === CONTEST_PATH) return contestDetail();
      if (path === GEOMETRY_PATH) return { type: "FeatureCollection", features: [] };
      if (path === `/v1/contests/${CONTEST_ID}/candidate-money?cycle=2024`) {
        return candidateMoney(2024);
      }
      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(
      createLoadEvent(requestJson, {
        url: new URL(`https://example.test/contest/${CONTEST_ID}?cycle=2024`)
      })
    )) as LoadResult;

    expect(data.contestSelectedCycle).toBe(2024);
  });

  it.each([
    ["blank", `https://example.test/contest/${CONTEST_ID}?cycle=`],
    ["whitespace-only", `https://example.test/contest/${CONTEST_ID}?cycle=%20%20`],
    ["non-numeric", `https://example.test/contest/${CONTEST_ID}?cycle=abcd`],
    ["decimal", `https://example.test/contest/${CONTEST_ID}?cycle=2024.5`],
    ["numeric alias", `https://example.test/contest/${CONTEST_ID}?cycle=2024.0`],
    ["too short", `https://example.test/contest/${CONTEST_ID}?cycle=24`],
    ["duplicated", `https://example.test/contest/${CONTEST_ID}?cycle=2024&cycle=2026`]
  ])("rejects malformed cycle query values before fetch: %s", async (_label, href) => {
    const requestJson = vi.fn();
    const setHeaders = vi.fn();

    await expect(
      load(createLoadEvent(requestJson, { url: new URL(href), setHeaders }))
    ).rejects.toMatchObject({
      status: 400,
      body: INVALID_CYCLE_ERROR
    });
    expect(requestJson).not.toHaveBeenCalled();
    expect(setHeaders).not.toHaveBeenCalled();
  });

  it("surfaces a well-formed unsupported cycle as a backend-owned route error", async () => {
    const backendCycleError = {
      detail: "Unsupported cycle 2030; supported cycles: 2022, 2024, 2026"
    };
    const moneyPath = `/v1/contests/${CONTEST_ID}/candidate-money?cycle=2030`;
    const requestJson = vi.fn(async (path: string) => {
      if (path === CONTEST_PATH) return contestDetail();
      if (path === GEOMETRY_PATH) return { type: "FeatureCollection", features: [] };
      if (path === moneyPath) throw new ApiResponseError(422, backendCycleError);
      throw new Error(`unexpected path: ${path}`);
    });
    const setHeaders = vi.fn();

    await expect(
      load(
        createLoadEvent(requestJson, {
          url: new URL(`https://example.test/contest/${CONTEST_ID}?cycle=2030`),
          setHeaders
        })
      )
    ).rejects.toMatchObject({
      status: 422,
      body: backendCycleError
    });
    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      CONTEST_PATH,
      GEOMETRY_PATH,
      moneyPath
    ]);
    expect(setHeaders).not.toHaveBeenCalled();
  });

  it("omits the cycle parameter when the contest has no usable election date", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === CONTEST_PATH) return contestDetail({ election_date: null });
      if (path === GEOMETRY_PATH) return { type: "FeatureCollection", features: [] };
      // Backend resolves its own default cycle when the client has no opinion.
      if (path === `/v1/contests/${CONTEST_ID}/candidate-money`) return candidateMoney();
      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as LoadResult;

    const calledPaths = requestJson.mock.calls.map(([path]) => String(path));
    expect(calledPaths).toContain(`/v1/contests/${CONTEST_ID}/candidate-money`);
    // The backend's resolved cycle wins over the client's absent one.
    expect(data.contestSelectedCycle).toBe(2026);
  });

  it("skips the money call entirely when the contest has no candidacies", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === CONTEST_PATH) return contestDetail({ candidacies: [] });
      if (path === GEOMETRY_PATH) return { type: "FeatureCollection", features: [] };
      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as LoadResult;

    const calledPaths = requestJson.mock.calls.map(([path]) => String(path));
    expect(calledPaths.some((path) => path.includes("candidate-money"))).toBe(false);
    expect(data.contestCandidateMoney).toBeNull();
    expect(data.contestSelectedCycle).toBe(2026);
  });

  it("preserves backend-owned 404 Contest not found semantics", async () => {
    const requestJson = vi.fn(async () => {
      throw new ApiResponseError(404, "Contest not found");
    });
    const setHeaders = vi.fn();

    await expect(load(createLoadEvent(requestJson, { setHeaders }))).rejects.toMatchObject({
      status: 404,
      body: { message: "Contest not found" }
    });
    expect(requestJson).toHaveBeenCalledTimes(1);
    expect(setHeaders).not.toHaveBeenCalled();
  });

  it("preserves backend malformed UUID 422 semantics", async () => {
    const requestJson = vi.fn(async () => {
      throw new ApiResponseError(422, "bad uuid");
    });
    const setHeaders = vi.fn();

    await expect(
      load(createLoadEvent(requestJson, { id: "not-a-uuid", setHeaders }))
    ).rejects.toMatchObject({ status: 422, body: { message: "bad uuid" } });
    expect(requestJson).toHaveBeenCalledTimes(1);
    expect(setHeaders).not.toHaveBeenCalled();
  });

  it("falls back to empty contest geometry when civic geometry returns backend-owned 404", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === CONTEST_PATH) return contestDetail();
      if (path === MONEY_PATH_2026) return candidateMoney();
      if (path === GEOMETRY_PATH) {
        throw new ApiResponseError(404, "Geometry not found");
      }
      throw new Error(`unexpected path: ${path}`);
    });
    const setHeaders = vi.fn();

    const data = (await load(createLoadEvent(requestJson, { setHeaders }))) as LoadResult;

    // The record is pre-seeded with empty feature collections, so a missing
    // geometry leaves the level empty rather than absent.
    expect(data.geometryByLevel.county.features).toEqual([]);
    // A missing map must not take the money down with it.
    expect(data.contestCandidateMoney?.rows).toHaveLength(1);
    expect(setHeaders).toHaveBeenCalledWith({
      "cache-control": "public, max-age=120, s-maxage=120, stale-while-revalidate=60"
    });
  });

  it("falls back cleanly to an empty geometry map when the division type is unsupported", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === CONTEST_PATH) {
        return contestDetail({ electoral_division_type: "school_zone" });
      }
      if (path === MONEY_PATH_2026) return candidateMoney();
      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as LoadResult;

    const calledPaths = requestJson.mock.calls.map(([path]) => String(path));
    expect(calledPaths.some((path) => path.startsWith("/v1/civics/geometry"))).toBe(false);
    expect(
      Object.values(data.geometryByLevel).every((value) => value.features.length === 0)
    ).toBe(true);
  });
});
