import { ApiResponseError } from "$lib/server/api/client";
import type { EntityDetailResponse } from "$lib/entity-detail/contract";
import { describe, expect, it, vi } from "vitest";
import { actions, load } from "./+page.server";

const PERSON_IDS = [
  "11111111-1111-4111-8111-111111111111",
  "22222222-2222-4222-8222-222222222222",
  "33333333-3333-4333-8333-333333333333",
  "44444444-4444-4444-8444-444444444444",
  "55555555-5555-4555-8555-555555555555"
] as const;
const [PERSON_A, PERSON_B, PERSON_C, PERSON_D, PERSON_E] = PERSON_IDS;
const UNKNOWN_PERSON_ID = "99999999-9999-4999-8999-999999999999";
const CAPPED_UNKNOWN_PERSON_ID = "00000000-0000-4000-8000-000000000099";
const UNAVAILABLE_PERSON_ID = "88888888-8888-4888-8888-888888888888";

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolver) => {
    resolve = resolver;
  });

  return { promise, resolve };
}

function buildPersonDetail(id: string): EntityDetailResponse {
  return {
    id,
    canonical_name: `Person ${id.toUpperCase()}`,
    name_variants: [],
    first_name: "Person",
    middle_name: null,
    last_name: id.toUpperCase(),
    suffix: null,
    occupation: null,
    education: null,
    date_of_birth: null,
    year_of_birth: null,
    bio_text: null,
    bio_source_url: null,
    bio_license: null,
    bio_pulled_at: null,
    identifiers: {},
    primary_address_id: null,
    er_cluster_id: null,
    er_confidence: null,
    current_office: null,
    portrait: null,
    sources: []
  };
}

function buildContributionInsights(personId: string, selectedCycle: number) {
  return {
    person_id: personId,
    has_data: true,
    metadata: {
      selected_cycle: selectedCycle,
      coverage_start_date: `${selectedCycle - 1}-01-01`,
      coverage_end_date: `${selectedCycle}-12-31`,
      available_cycles: [selectedCycle],
      cycles_included: [selectedCycle],
      committee_count: 1,
      approximate_geography: false,
      excluded_geography: null,
      caveats: []
    },
    monthly_totals: [],
    itemized_size_buckets: [],
    dollars_by_size: [],
    cycle_totals: [],
    career_totals: {
      itemized_individual_contribution_amount: "100.00",
      itemized_transaction_count: 1,
      unitemized_individual_contribution_amount: "0.00",
      total_individual_contribution_amount: "100.00",
      source: "itemized_transactions"
    },
    geography: {
      by_state: [],
      by_district: [],
      district_share: {
        in_district_amount: null,
        out_of_district_amount: null,
        unknown_district_amount: null,
        share: null,
        available: false
      }
    },
    small_dollar_share: {
      small_dollar_amount: "100.00",
      total_contribution_amount: "100.00",
      share: "1.0000",
      available: true
    }
  };
}

function createLoadEvent(url: string, requestJson: ReturnType<typeof vi.fn>) {
  return {
    url: new URL(url),
    locals: { api: { requestJson } }
  } as unknown as Parameters<typeof load>[0];
}

function createActionEvent(query: string, requestJson: ReturnType<typeof vi.fn>) {
  const formData = new FormData();
  formData.set("q", query);

  return {
    request: {
      formData: () => Promise.resolve(formData)
    },
    locals: { api: { requestJson } }
  } as unknown as Parameters<typeof actions.addSearch>[0];
}

function createRouteApi(
  knownIds: readonly string[] = PERSON_IDS,
  selectedCycleById: Readonly<Record<string, number>> = {},
  includeCandidates = false
) {
  const known = new Set(knownIds);
  const requestJson = vi.fn(async (path: string): Promise<unknown> => {
    const detailMatch = path.match(/^\/v1\/person\/([^/?]+)$/);
    if (detailMatch !== null) {
      const personId = decodeURIComponent(detailMatch[1]);
      if (!known.has(personId)) {
        throw new ApiResponseError(404, { detail: "Person not found" });
      }
      return buildPersonDetail(personId);
    }

    const insightsMatch = path.match(/^\/v1\/person\/([^/?]+)\/contribution-insights$/);
    if (insightsMatch !== null) {
      const personId = decodeURIComponent(insightsMatch[1]);
      return buildContributionInsights(personId, selectedCycleById[personId] ?? 2026);
    }

    const candidateListMatch = path.match(
      /^\/v1\/candidates\?person_id=([^&]+)&limit=10&offset=0$/
    );
    if (candidateListMatch !== null) {
      const personId = decodeURIComponent(candidateListMatch[1]);
      if (includeCandidates) {
        return {
          items: [{ id: `candidate-${personId}`, person_id: personId }],
          has_next: false,
          offset: 0,
          limit: 10
        };
      }
      return { items: [], has_next: false, offset: 0, limit: 10 };
    }

    const candidateDetailMatch = path.match(/^\/v1\/candidates\/candidate-([^/?]+)$/);
    if (candidateDetailMatch !== null) {
      const personId = decodeURIComponent(candidateDetailMatch[1]);
      return {
        id: `candidate-${personId}`,
        person_id: personId,
        principal_committee_id: null
      };
    }

    const candidateMoneyMatch = path.match(
      /^\/v1\/candidates\/candidate-([^/?]+)\/(summary|independent-expenditures|independent-expenditures\/summary)\?cycle=(\d{4})$/
    );
    if (candidateMoneyMatch !== null) {
      return candidateMoneyMatch[2] === "summary" ? { committees: [] } : null;
    }

    const rankedMatch = path.match(
      /^\/v1\/person\/([^/?]+)\/(top-donors|top-employers)\?cycle=(\d{4})$/
    );
    if (rankedMatch !== null) {
      return [];
    }

    throw new Error(`Unexpected path: ${path}`);
  });

  return requestJson;
}

async function loadCompare(url: string, requestJson = createRouteApi()) {
  return load(createLoadEvent(url, requestJson));
}

describe("/compare +page.server load", () => {
  it("never sends malformed people tokens to the backend or labels them as unknown people", async () => {
    const requestJson = vi.fn((path: string): Promise<unknown> => {
      if (path === `/v1/person/${PERSON_A}`) {
        return Promise.resolve(buildPersonDetail(PERSON_A));
      }
      if (path === `/v1/person/${UNKNOWN_PERSON_ID}`) {
        return Promise.reject(new ApiResponseError(404, { detail: "Person not found" }));
      }
      if (path === "/v1/person/not-a-uuid") {
        return Promise.reject(
          new ApiResponseError(422, { detail: "Input should be a valid UUID" })
        );
      }
      return Promise.reject(new Error(`Unexpected path: ${path}`));
    });

    await expect(
      loadCompare(
        `https://example.test/compare?people=${PERSON_A},not-a-uuid,${UNKNOWN_PERSON_ID}`,
        requestJson
      )
    ).rejects.toMatchObject({
      status: 301,
      location: `/compare?people=${PERSON_A}&notice=unknown-people-dropped`
    });
    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      `/v1/person/${PERSON_A}`,
      `/v1/person/${UNKNOWN_PERSON_ID}`
    ]);
  });

  it("canonicalizes all-malformed input to the rendered empty recovery state without requests", async () => {
    const requestJson = vi.fn().mockRejectedValue(
      new ApiResponseError(422, { detail: "Input should be a valid UUID" })
    );

    await expect(
      loadCompare("https://example.test/compare?people=not-a-uuid,still-bad", requestJson)
    ).rejects.toMatchObject({
      status: 301,
      location: "/compare"
    });
    expect(requestJson).not.toHaveBeenCalled();

    const data = await loadCompare("https://example.test/compare", requestJson);
    expect(data).toMatchObject({
      columns: [],
      notices: [],
      canonicalComparison: null,
      prompt: { kind: "add-officeholder" }
    });
    expect(requestJson).not.toHaveBeenCalled();
  });

  it("trims empty tokens, deduplicates, and redirects populated input to lexical order", async () => {
    const requestJson = createRouteApi([PERSON_A, PERSON_B]);

    await expect(
      loadCompare(
        `https://example.test/compare?people=%20${PERSON_B}%20,%20,%20${PERSON_A}%20,${PERSON_A}`,
        requestJson
      )
    ).rejects.toMatchObject({
      status: 301,
      location: `/compare?people=${PERSON_A},${PERSON_B}`
    });
    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      `/v1/person/${PERSON_A}`,
      `/v1/person/${PERSON_B}`
    ]);
  });

  it("redirects a duplicated single id instead of treating it as already canonical", async () => {
    const requestJson = createRouteApi([PERSON_A]);

    await expect(
      loadCompare(
        `https://example.test/compare?people=${PERSON_A},${PERSON_A}`,
        requestJson
      )
    ).rejects.toMatchObject({
      status: 301,
      location: `/compare?people=${PERSON_A}`
    });
  });

  it("returns the add-officeholder prompt for clean zero and one-person requests", async () => {
    const emptyData = await loadCompare("https://example.test/compare", createRouteApi([]));
    expect(emptyData).toMatchObject({
      columns: [],
      notices: [],
      canonicalComparison: null,
      prompt: { kind: "add-officeholder" }
    });

    const onePersonData = await loadCompare(
      `https://example.test/compare?people=${PERSON_A}`,
      createRouteApi([PERSON_A])
    );
    expect(onePersonData.columns.map((column) => column.personId)).toEqual([PERSON_A]);
    expect(onePersonData.canonicalComparison).toBeNull();
    expect(onePersonData.prompt).toEqual({ kind: "add-officeholder" });
    await expect(onePersonData.columns[0].money).resolves.toMatchObject({
      personContributionInsights: { person_id: PERSON_A }
    });
  });

  it.each([
    ["two", [PERSON_A, PERSON_B]],
    ["four", [PERSON_A, PERSON_B, PERSON_C, PERSON_D]]
  ])("loads an already-canonical %s-person comparison", async (_label, people) => {
    const peopleKey = people.join(",");
    const data = await loadCompare(
      `https://example.test/compare?people=${peopleKey}`,
      createRouteApi(people)
    );

    expect(data.columns.map((column) => column.personId)).toEqual(people);
    expect(data.canonicalComparison).toEqual({
      people: peopleKey,
      href: `/compare?people=${peopleKey}`
    });
    expect(data.prompt).toBeNull();
  });

  it("caps before parallel lookups and redirects without starting money fan-out", async () => {
    const details = new Map<string, ReturnType<typeof createDeferred<unknown>>>(
      PERSON_IDS.slice(0, 4).map((id) => [id, createDeferred<unknown>()])
    );
    const requestJson = vi.fn((path: string): Promise<unknown> => {
      const personId = path.replace("/v1/person/", "");
      const detail = details.get(personId);
      return detail?.promise ?? Promise.reject(new Error(`Unexpected path: ${path}`));
    });
    const loadPromise = loadCompare(
      `https://example.test/compare?people=${PERSON_E},${PERSON_D},${PERSON_C},${PERSON_B},${PERSON_A}`,
      requestJson
    );

    await Promise.resolve();
    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      `/v1/person/${PERSON_A}`,
      `/v1/person/${PERSON_B}`,
      `/v1/person/${PERSON_C}`,
      `/v1/person/${PERSON_D}`
    ]);

    for (const [personId, detail] of details) {
      detail.resolve(buildPersonDetail(personId));
    }
    await expect(loadPromise).rejects.toMatchObject({
      status: 301,
      location: `/compare?people=${PERSON_A},${PERSON_B},${PERSON_C},${PERSON_D}&notice=max-4`
    });
    expect(requestJson.mock.calls.some(([path]) => path.includes("contribution-insights"))).toBe(false);
  });

  it("preserves cap and unknown notices for one redirect, then returns a clean canonical link", async () => {
    const requestJson = createRouteApi([PERSON_A, PERSON_B, PERSON_C]);
    const peopleKey = [PERSON_A, PERSON_B, PERSON_C].join(",");
    const initialUrl = `https://example.test/compare?people=${PERSON_E},${CAPPED_UNKNOWN_PERSON_ID},${PERSON_C},${PERSON_B},${PERSON_A}`;
    const redirectedUrl = `https://example.test/compare?people=${peopleKey}&notice=max-4,unknown-people-dropped`;

    await expect(loadCompare(initialUrl, requestJson)).rejects.toMatchObject({
      status: 301,
      location: `/compare?people=${peopleKey}&notice=max-4,unknown-people-dropped`
    });
    expect(requestJson.mock.calls.map(([path]) => path)).not.toContain(
      `/v1/person/${PERSON_E}`
    );

    requestJson.mockClear();
    const data = await loadCompare(redirectedUrl, requestJson);
    expect(data.notices).toEqual(["max-4", "unknown-people-dropped"]);
    expect(data.canonicalComparison).toEqual({
      people: peopleKey,
      href: `/compare?people=${peopleKey}`
    });
  });

  it("drops only 404 details and maps other API failures through the route error owner", async () => {
    const requestJson = vi.fn((path: string): Promise<unknown> => {
      if (path === `/v1/person/${PERSON_A}`) {
        return Promise.resolve(buildPersonDetail(PERSON_A));
      }
      if (path === `/v1/person/${UNKNOWN_PERSON_ID}`) {
        return Promise.reject(new ApiResponseError(404, { detail: "missing" }));
      }
      if (path === `/v1/person/${UNAVAILABLE_PERSON_ID}`) {
        return Promise.reject(new ApiResponseError(503, { detail: "unavailable" }));
      }
      return Promise.reject(new Error(`Unexpected path: ${path}`));
    });

    await expect(
      loadCompare(
        `https://example.test/compare?people=${PERSON_A},${UNKNOWN_PERSON_ID}`,
        requestJson
      )
    ).rejects.toMatchObject({
      status: 301,
      location: `/compare?people=${PERSON_A}&notice=unknown-people-dropped`
    });
    await expect(
      loadCompare(
        `https://example.test/compare?people=${PERSON_A},${UNAVAILABLE_PERSON_ID}`,
        requestJson
      )
    ).rejects.toMatchObject({
      status: 503,
      body: { detail: "unavailable" }
    });
  });

  it("does not reinterpret malformed person detail as an unknown id", async () => {
    const requestJson = vi
      .fn()
      .mockResolvedValue({ id: PERSON_A, canonical_name: "Malformed" });

    await expect(
      loadCompare(`https://example.test/compare?people=${PERSON_A}`, requestJson)
    ).rejects.toThrow("Person payload missing required bio keys");
  });

  it("starts every retained column in parallel and keeps each column on its derived cycle", async () => {
    const insightsByPerson = {
      a: createDeferred<unknown>(),
      b: createDeferred<unknown>()
    };
    const baseApi = createRouteApi(
      [PERSON_A, PERSON_B],
      { [PERSON_A]: 2024, [PERSON_B]: 2026 },
      true
    );
    const requestJson = vi.fn((path: string): Promise<unknown> => {
      if (path === `/v1/person/${PERSON_A}/contribution-insights`) {
        return insightsByPerson.a.promise;
      }
      if (path === `/v1/person/${PERSON_B}/contribution-insights`) {
        return insightsByPerson.b.promise;
      }
      return baseApi(path);
    });
    const data = await loadCompare(
      `https://example.test/compare?people=${PERSON_A},${PERSON_B}`,
      requestJson
    );

    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      `/v1/person/${PERSON_A}`,
      `/v1/person/${PERSON_B}`,
      `/v1/person/${PERSON_A}/contribution-insights`,
      `/v1/person/${PERSON_B}/contribution-insights`
    ]);

    insightsByPerson.a.resolve(buildContributionInsights(PERSON_A, 2024));
    insightsByPerson.b.resolve(buildContributionInsights(PERSON_B, 2026));
    await Promise.all(data.columns.map((column) => column.money));
    const paths = requestJson.mock.calls.map(([path]) => path);
    expect(paths).toContain(`/v1/candidates/candidate-${PERSON_A}/summary?cycle=2024`);
    expect(paths).toContain(`/v1/person/${PERSON_A}/top-donors?cycle=2024`);
    expect(paths).toContain(`/v1/person/${PERSON_A}/top-employers?cycle=2024`);
    expect(paths).toContain(`/v1/candidates/candidate-${PERSON_B}/summary?cycle=2026`);
    expect(paths).toContain(`/v1/person/${PERSON_B}/top-donors?cycle=2026`);
    expect(paths).toContain(`/v1/person/${PERSON_B}/top-employers?cycle=2026`);
  });

  it("keeps money failures isolated while sibling promises wait for all four fields", async () => {
    const siblingEmployers = createDeferred<unknown>();
    const moneyFailure = new ApiResponseError(503, { detail: "donors unavailable" });
    const baseApi = createRouteApi([PERSON_A, PERSON_B]);
    const requestJson = vi.fn((path: string): Promise<unknown> => {
      if (path === `/v1/person/${PERSON_A}/top-donors?cycle=2026`) {
        return Promise.reject(moneyFailure);
      }
      if (path === `/v1/person/${PERSON_B}/top-employers?cycle=2026`) {
        return siblingEmployers.promise;
      }
      return baseApi(path);
    });

    const data = await loadCompare(
      `https://example.test/compare?people=${PERSON_A},${PERSON_B}`,
      requestJson
    );
    const failedColumn = data.columns[0].money;
    const siblingColumn = data.columns[1].money;
    let siblingResolved = false;
    void siblingColumn.then(() => {
      siblingResolved = true;
    });

    await expect(failedColumn).rejects.toBe(moneyFailure);
    await Promise.resolve();
    expect(siblingResolved).toBe(false);

    siblingEmployers.resolve([]);
    await expect(siblingColumn).resolves.toMatchObject({
      personContributionInsights: { person_id: PERSON_B },
      personFinanceSections: [],
      personTopDonors: [],
      personTopEmployers: []
    });
  });
});

describe("/compare +page.server actions", () => {
  it("addSearch returns only renderable person suggestions from the shared search fetcher", async () => {
    const requestJson = vi.fn().mockResolvedValue({
      items: [
        {
          entity_type: "person",
          entity_id: "11111111-1111-4111-8111-111111111111",
          name: "Jane Doe"
        },
        {
          entity_type: "person",
          entity_id: "not-a-uuid",
          name: "Broken Person"
        },
        {
          entity_type: "org",
          entity_id: "22222222-2222-4222-8222-222222222222",
          name: "Jane Org"
        }
      ],
      has_next: false
    });

    const result = await actions.addSearch(createActionEvent("jane", requestJson));

    expect(requestJson).toHaveBeenCalledWith("/v1/search?q=jane&entity_type=person");
    expect(result).toEqual({
      query: "jane",
      suggestions: [
        {
          entity_type: "person",
          entity_id: "11111111-1111-4111-8111-111111111111",
          name: "Jane Doe"
        }
      ]
    });
  });

  it("addSearch maps backend 422 validation into inline form state", async () => {
    const requestJson = vi.fn().mockRejectedValue(
      new ApiResponseError(422, {
        detail: "query.q: String should have at least 2 characters"
      })
    );

    const result = await actions.addSearch(createActionEvent("j", requestJson));

    expect(result).toMatchObject({
      status: 422,
      data: {
        query: "j",
        suggestions: [],
        validationMessage: "query.q: String should have at least 2 characters"
      }
    });
  });
});
