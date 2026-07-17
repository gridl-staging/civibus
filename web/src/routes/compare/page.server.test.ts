import { ApiResponseError } from "$lib/server/api/client";
import type { EntityDetailResponse } from "$lib/entity-detail/contract";
import { describe, expect, it, vi } from "vitest";
import { actions, load } from "./+page.server";

const PERSON_IDS = ["a", "b", "c", "d", "e"] as const;

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
  it("trims empty tokens, deduplicates, and redirects populated input to lexical order", async () => {
    const requestJson = createRouteApi(["a", "b"]);

    await expect(
      loadCompare("https://example.test/compare?people=%20b%20,%20,%20a%20,a", requestJson)
    ).rejects.toMatchObject({
      status: 301,
      location: "/compare?people=a,b"
    });
    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      "/v1/person/a",
      "/v1/person/b"
    ]);
  });

  it("redirects a duplicated single id instead of treating it as already canonical", async () => {
    const requestJson = createRouteApi(["a"]);

    await expect(
      loadCompare("https://example.test/compare?people=a,a", requestJson)
    ).rejects.toMatchObject({
      status: 301,
      location: "/compare?people=a"
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
      "https://example.test/compare?people=a",
      createRouteApi(["a"])
    );
    expect(onePersonData.columns.map((column) => column.personId)).toEqual(["a"]);
    expect(onePersonData.canonicalComparison).toBeNull();
    expect(onePersonData.prompt).toEqual({ kind: "add-officeholder" });
    await expect(onePersonData.columns[0].money).resolves.toMatchObject({
      personContributionInsights: { person_id: "a" }
    });
  });

  it.each([
    ["two", ["a", "b"]],
    ["four", ["a", "b", "c", "d"]]
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
      "https://example.test/compare?people=e,d,c,b,a",
      requestJson
    );

    await Promise.resolve();
    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      "/v1/person/a",
      "/v1/person/b",
      "/v1/person/c",
      "/v1/person/d"
    ]);

    for (const [personId, detail] of details) {
      detail.resolve(buildPersonDetail(personId));
    }
    await expect(loadPromise).rejects.toMatchObject({
      status: 301,
      location: "/compare?people=a,b,c,d&notice=max-4"
    });
    expect(requestJson.mock.calls.some(([path]) => path.includes("contribution-insights"))).toBe(false);
  });

  it("preserves cap and unknown notices for one redirect, then returns a clean canonical link", async () => {
    const requestJson = createRouteApi(["a", "b", "c"]);
    const initialUrl = "https://example.test/compare?people=z,missing,c,b,a";
    const redirectedUrl =
      "https://example.test/compare?people=a,b,c&notice=max-4,unknown-people-dropped";

    await expect(loadCompare(initialUrl, requestJson)).rejects.toMatchObject({
      status: 301,
      location: "/compare?people=a,b,c&notice=max-4,unknown-people-dropped"
    });
    expect(requestJson.mock.calls.map(([path]) => path)).not.toContain("/v1/person/z");

    requestJson.mockClear();
    const data = await loadCompare(redirectedUrl, requestJson);
    expect(data.notices).toEqual(["max-4", "unknown-people-dropped"]);
    expect(data.canonicalComparison).toEqual({
      people: "a,b,c",
      href: "/compare?people=a,b,c"
    });
  });

  it("drops only 404 details and maps other API failures through the route error owner", async () => {
    const requestJson = vi.fn((path: string): Promise<unknown> => {
      if (path === "/v1/person/a") {
        return Promise.resolve(buildPersonDetail("a"));
      }
      if (path === "/v1/person/missing") {
        return Promise.reject(new ApiResponseError(404, { detail: "missing" }));
      }
      if (path === "/v1/person/unavailable") {
        return Promise.reject(new ApiResponseError(503, { detail: "unavailable" }));
      }
      return Promise.reject(new Error(`Unexpected path: ${path}`));
    });

    await expect(
      loadCompare("https://example.test/compare?people=a,missing", requestJson)
    ).rejects.toMatchObject({
      status: 301,
      location: "/compare?people=a&notice=unknown-people-dropped"
    });
    await expect(
      loadCompare("https://example.test/compare?people=a,unavailable", requestJson)
    ).rejects.toMatchObject({
      status: 503,
      body: { detail: "unavailable" }
    });
  });

  it("does not reinterpret malformed person detail as an unknown id", async () => {
    const requestJson = vi.fn().mockResolvedValue({ id: "a", canonical_name: "Malformed" });

    await expect(
      loadCompare("https://example.test/compare?people=a", requestJson)
    ).rejects.toThrow("Person payload missing required bio keys");
  });

  it("starts every retained column in parallel and keeps each column on its derived cycle", async () => {
    const insightsByPerson = {
      a: createDeferred<unknown>(),
      b: createDeferred<unknown>()
    };
    const baseApi = createRouteApi(["a", "b"], { a: 2024, b: 2026 }, true);
    const requestJson = vi.fn((path: string): Promise<unknown> => {
      if (path === "/v1/person/a/contribution-insights") {
        return insightsByPerson.a.promise;
      }
      if (path === "/v1/person/b/contribution-insights") {
        return insightsByPerson.b.promise;
      }
      return baseApi(path);
    });
    const data = await loadCompare("https://example.test/compare?people=a,b", requestJson);

    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      "/v1/person/a",
      "/v1/person/b",
      "/v1/person/a/contribution-insights",
      "/v1/person/b/contribution-insights"
    ]);

    insightsByPerson.a.resolve(buildContributionInsights("a", 2024));
    insightsByPerson.b.resolve(buildContributionInsights("b", 2026));
    await Promise.all(data.columns.map((column) => column.money));
    const paths = requestJson.mock.calls.map(([path]) => path);
    expect(paths).toContain("/v1/candidates/candidate-a/summary?cycle=2024");
    expect(paths).toContain("/v1/person/a/top-donors?cycle=2024");
    expect(paths).toContain("/v1/person/a/top-employers?cycle=2024");
    expect(paths).toContain("/v1/candidates/candidate-b/summary?cycle=2026");
    expect(paths).toContain("/v1/person/b/top-donors?cycle=2026");
    expect(paths).toContain("/v1/person/b/top-employers?cycle=2026");
  });

  it("keeps money failures isolated while sibling promises wait for all four fields", async () => {
    const siblingEmployers = createDeferred<unknown>();
    const moneyFailure = new ApiResponseError(503, { detail: "donors unavailable" });
    const baseApi = createRouteApi(["a", "b"]);
    const requestJson = vi.fn((path: string): Promise<unknown> => {
      if (path === "/v1/person/a/top-donors?cycle=2026") {
        return Promise.reject(moneyFailure);
      }
      if (path === "/v1/person/b/top-employers?cycle=2026") {
        return siblingEmployers.promise;
      }
      return baseApi(path);
    });

    const data = await loadCompare("https://example.test/compare?people=a,b", requestJson);
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
      personContributionInsights: { person_id: "b" },
      personFinanceSections: [],
      personTopDonors: [],
      personTopEmployers: []
    });
  });
});

describe("/compare +page.server actions", () => {
  it("addSearch returns only renderable person suggestions from the shared search fetcher", async () => {
    const requestJson = vi.fn().mockResolvedValue([
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
    ]);

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
