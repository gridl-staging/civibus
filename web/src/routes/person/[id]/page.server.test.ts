import { ApiResponseError } from "$lib/server/api/client";
import type { EntityDetailPageBundle } from "$lib/server/api/entity-detail";
import { describe, expect, it, vi } from "vitest";
import { load } from "./+page.server";

const PERSON_ID = "11111111-1111-4111-8111-111111111111";
const CANDIDATE_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const COMMITTEE_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
const SELECTED_CYCLE_FIELDS = {
  selected_cycle: 2026,
  coverage_start_date: "2025-01-01",
  coverage_end_date: "2026-12-31",
  available_cycles: [2022, 2024, 2026]
};
const INVALID_CYCLE_ERROR = {
  message: "Invalid cycle query parameter.",
  detail: "The cycle query parameter must be a single four-digit election cycle."
};

function createLoadEvent(requestJson: ReturnType<typeof vi.fn>, url = new URL(`https://example.test/person/${PERSON_ID}`)) {
  return {
    params: { id: PERSON_ID },
    url,
    locals: {
      api: {
        requestJson
      }
    }
  } as unknown as Parameters<typeof load>[0];
}

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolver) => {
    resolve = resolver;
  });

  return { promise, resolve };
}

function buildPersonDetail() {
  return {
    id: PERSON_ID,
    canonical_name: "Jane Doe",
    name_variants: [],
    first_name: "Jane",
    middle_name: null,
    last_name: "Doe",
    suffix: null,
    occupation: "Attorney",
    education: "State University",
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

function createPersonRouteApi(cycle?: number) {
  const personDetail = buildPersonDetail();
  const selectedCycle = cycle ?? SELECTED_CYCLE_FIELDS.selected_cycle;
  const contributionInsightsCycleQuery = cycle === undefined ? "" : `?cycle=${cycle}`;
  const selectedCycleQuery = `?cycle=${selectedCycle}`;

  const requestJson = vi.fn(async (path: string): Promise<unknown> => {
    if (path === `/v1/person/${PERSON_ID}`) {
      return personDetail;
    }

    if (path === `/v1/candidates?person_id=${PERSON_ID}&limit=10&offset=0`) {
      return {
        items: [
          {
            id: CANDIDATE_ID,
            fec_candidate_id: "H0NC01001",
            name: "Candidate One",
            person_id: PERSON_ID,
            party: "DEM",
            office: "H",
            state: "NC",
            district: "01",
            slug: "candidate-one",
            slug_is_unique: true
          }
        ],
        has_next: false,
        offset: 0,
        limit: 10
      };
    }

    if (path === `/v1/candidates/${CANDIDATE_ID}`) {
      return {
        id: CANDIDATE_ID,
        fec_candidate_id: "H0NC01001",
        name: "Candidate One",
        slug: "candidate-one",
        slug_is_unique: true,
        person_id: PERSON_ID,
        party: "DEM",
        office: "H",
        state: "NC",
        district: "01",
        incumbent_challenge: "I",
        principal_committee_id: COMMITTEE_ID,
        sources: []
      };
    }

    if (path === `/v1/candidates/${CANDIDATE_ID}/summary${selectedCycleQuery}`) {
      return {
        ...SELECTED_CYCLE_FIELDS,
        selected_cycle: selectedCycle,
        candidate_id: CANDIDATE_ID,
      candidate_name: "Candidate One",
      total_raised: "100.00",
      total_spent: "50.00",
      net: "50.00",
      transaction_count: 2,
      itemized_transaction_count: 2,
      cash_on_hand: "25.00",
      net_self_funding: null,
      debts_owed_by_committee: "5.00",
      summary_source: "fec_weball",
      receipt_source_composition: [
        {
          label: "Gross individual contributions",
          total_amount: "100.00",
          source: "fec_committee_summary"
        }
      ],
      selected_cycle_coverage_complete: true,
      can_render_share: true,
      receipt_source_caveats: [],
      committees: []
    };
    }

    if (path === `/v1/candidates/${CANDIDATE_ID}/independent-expenditures${selectedCycleQuery}`) {
      return [];
    }

    if (path === `/v1/candidates/${CANDIDATE_ID}/independent-expenditures/summary${selectedCycleQuery}`) {
      return {
        ...SELECTED_CYCLE_FIELDS,
        selected_cycle: selectedCycle,
        candidate_id: CANDIDATE_ID,
        support_total: "0.00",
        oppose_total: "0.00",
        support_count: 0,
        oppose_count: 0,
        top_spenders: [],
        excluded_outlier_count: 0
      };
    }

    if (path === `/v1/person/${PERSON_ID}/contribution-insights${contributionInsightsCycleQuery}`) {
      return {
        person_id: PERSON_ID,
        has_data: true,
        metadata: {
          ...SELECTED_CYCLE_FIELDS,
          selected_cycle: selectedCycle,
          coverage_start_date: cycle === undefined ? "2025-01-01" : "2023-01-01",
          coverage_end_date: cycle === undefined ? "2026-12-31" : "2024-12-31",
          cycles_included: [selectedCycle],
          committee_count: 1,
          approximate_geography: false,
          excluded_geography: "Unitemized contributions are excluded from geography.",
          caveats: []
        },
        monthly_totals: [{ month: "2026-01", total_amount: "100.00", transaction_count: 1 }],
        itemized_size_buckets: [],
        dollars_by_size: [],
        cycle_totals: [
          {
            cycle: 2026,
            itemized_individual_contribution_amount: "100.00",
            itemized_transaction_count: 1,
            unitemized_individual_contribution_amount: "0.00",
            total_individual_contribution_amount: "100.00",
            source: "itemized_transactions"
          }
        ],
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
            in_district_amount: "100.00",
            out_of_district_amount: "0.00",
            unknown_district_amount: "0.00",
            share: "1.0000",
            available: true
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

    if (path === `/v1/person/${PERSON_ID}/top-donors${selectedCycleQuery}`) {
      return [{ name: "Top Donor", total_amount: "100.00", transaction_count: 1 }];
    }

    if (path === `/v1/person/${PERSON_ID}/top-employers${selectedCycleQuery}`) {
      return [{ employer: "ACME CORP", total_amount: "100.00", transaction_count: 1 }];
    }

    const transactionPath = `/v1/transactions?committee_id=${COMMITTEE_ID}&limit=25&cycle=${selectedCycle}`;
    if (path === transactionPath) {
      return [];
    }

    throw new Error(`unexpected path: ${path}`);
  });

  return { personDetail, requestJson };
}

describe("/person/[id] +page.server load", () => {
  it("loads canonical person detail and resolves the SSR money headline before deferred finance detail", async () => {
    const { personDetail, requestJson } = createPersonRouteApi();

    const data = (await load(createLoadEvent(requestJson))) as EntityDetailPageBundle;

    expect(data.entityType).toBe("person");
    expect(data.detail).toBe(personDetail);
    expect("matches" in data).toBe(false);
    expect("relationships" in data).toBe(false);
    expect("personCivicHistory" in data).toBe(false);
    expect(data.personMoneyHeadline).toMatchObject({
      kind: "loaded",
      summary: {
        selected_cycle: 2026,
        total_raised: "100.00",
        total_spent: "50.00",
        cash_on_hand: "25.00",
        debts_owed_by_committee: "5.00"
      }
    });
    expect(data.personMoneyHeadline).not.toBeInstanceOf(Promise);
    expect(data.personContributionInsights).toBeInstanceOf(Promise);
    expect(data.personTopDonors).toBeInstanceOf(Promise);
    expect(data.personTopEmployers).toBeInstanceOf(Promise);
    expect(data.personFinanceSections).toBeInstanceOf(Promise);
    await expect(data.personFinanceSections).resolves.toMatchObject([
      {
        candidate: { id: CANDIDATE_ID }
      }
    ]);
    await expect(data.personContributionInsights).resolves.toMatchObject({
      person_id: PERSON_ID,
      small_dollar_share: { share: "1.0000" }
    });
    await expect(data.personTopDonors).resolves.toEqual([
      { name: "Top Donor", total_amount: "100.00", transaction_count: 1 }
    ]);
    await expect(data.personTopEmployers).resolves.toEqual([
      { employer: "ACME CORP", total_amount: "100.00", transaction_count: 1 }
    ]);
    expect(requestJson.mock.calls.map(([path]) => path)).not.toContain(`/v1/er/person/${PERSON_ID}/matches`);
    expect(requestJson.mock.calls.map(([path]) => path)).not.toContain(
      `/v1/graph/person/${PERSON_ID}/relationships`
    );
  });

  it("resolves no-linked-candidacy as the SSR headline state while detail streams", async () => {
    const { requestJson } = createPersonRouteApi();
    requestJson.mockImplementation(async (path: string) => {
      if (path === `/v1/person/${PERSON_ID}`) {
        return buildPersonDetail();
      }

      if (path === `/v1/candidates?person_id=${PERSON_ID}&limit=10&offset=0`) {
        return { items: [], has_next: false, offset: 0, limit: 10 };
      }

      if (path === `/v1/person/${PERSON_ID}/contribution-insights`) {
        return {
          person_id: PERSON_ID,
          has_data: false,
          metadata: {
            ...SELECTED_CYCLE_FIELDS,
            coverage_start_date: "2022-01-01",
            coverage_end_date: "2026-12-31",
            cycles_included: [2022, 2024, 2026],
            committee_count: 0,
            approximate_geography: false,
            excluded_geography: "no_linked_candidate",
            caveats: []
          },
          monthly_totals: [],
          itemized_size_buckets: [],
          dollars_by_size: [],
          cycle_totals: [],
          career_totals: {
            itemized_individual_contribution_amount: "0.00",
            itemized_transaction_count: 0,
            unitemized_individual_contribution_amount: "0.00",
            total_individual_contribution_amount: "0.00",
            source: "none"
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
            small_dollar_amount: null,
            total_contribution_amount: null,
            share: null,
            available: false
          }
        };
      }

      if (path === `/v1/person/${PERSON_ID}/top-donors?cycle=2026`) {
        return [];
      }

      if (path === `/v1/person/${PERSON_ID}/top-employers?cycle=2026`) {
        return [];
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as EntityDetailPageBundle;

    expect(data.personMoneyHeadline).toEqual({
      kind: "no_linked_candidate",
      message: "No campaign-finance candidacies are linked yet."
    });
    await expect(data.personFinanceSections).resolves.toEqual([]);
    await expect(data.personContributionInsights).resolves.toMatchObject({
      has_data: false,
      metadata: { excluded_geography: "no_linked_candidate" }
    });
    await expect(data.personTopDonors).resolves.toEqual([]);
    await expect(data.personTopEmployers).resolves.toEqual([]);
    expect(requestJson.mock.calls.map(([path]) => path)).toContain(
      `/v1/person/${PERSON_ID}/contribution-insights`
    );
    expect(requestJson.mock.calls.map(([path]) => path)).toContain(
      `/v1/person/${PERSON_ID}/top-donors?cycle=2026`
    );
    expect(requestJson.mock.calls.map(([path]) => path)).toContain(
      `/v1/person/${PERSON_ID}/top-employers?cycle=2026`
    );
  });

  it("preserves the selected cycle query for person and linked-candidate finance requests", async () => {
    const { requestJson } = createPersonRouteApi(2024);
    const url = new URL(`https://example.test/person/${PERSON_ID}?cycle=2024`);

    const data = (await load(createLoadEvent(requestJson, url))) as EntityDetailPageBundle;

    await expect(data.personFinanceSections).resolves.toMatchObject([{ candidate: { id: CANDIDATE_ID } }]);
    await expect(data.personContributionInsights).resolves.toMatchObject({
      metadata: {
        selected_cycle: 2024,
        coverage_start_date: "2023-01-01",
        coverage_end_date: "2024-12-31"
      }
    });
    await expect(data.personTopDonors).resolves.toEqual([
      { name: "Top Donor", total_amount: "100.00", transaction_count: 1 }
    ]);
    await expect(data.personTopEmployers).resolves.toEqual([
      { employer: "ACME CORP", total_amount: "100.00", transaction_count: 1 }
    ]);
    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      `/v1/person/${PERSON_ID}`,
      `/v1/candidates?person_id=${PERSON_ID}&limit=10&offset=0`,
      `/v1/person/${PERSON_ID}/contribution-insights?cycle=2024`,
      `/v1/person/${PERSON_ID}/top-donors?cycle=2024`,
      `/v1/person/${PERSON_ID}/top-employers?cycle=2024`,
      `/v1/candidates/${CANDIDATE_ID}`,
      `/v1/candidates/${CANDIDATE_ID}/summary?cycle=2024`,
      `/v1/candidates/${CANDIDATE_ID}/independent-expenditures?cycle=2024`,
      `/v1/candidates/${CANDIDATE_ID}/independent-expenditures/summary?cycle=2024`,
      `/v1/transactions?committee_id=${COMMITTEE_ID}&limit=25&cycle=2024`
    ]);
  });

  it("starts explicit-cycle donor and employer fetches before contribution-insights validation resolves", async () => {
    const contributionInsights = createDeferred<unknown>();
    const contributionInsightsPayload = {
      person_id: PERSON_ID,
      has_data: false,
      metadata: {
        ...SELECTED_CYCLE_FIELDS,
        selected_cycle: 2024,
        coverage_start_date: "2023-01-01",
        coverage_end_date: "2024-12-31",
        cycles_included: [2024],
        committee_count: 0,
        approximate_geography: false,
        excluded_geography: "no_linked_candidate",
        caveats: []
      },
      monthly_totals: [],
      itemized_size_buckets: [],
      dollars_by_size: [],
      cycle_totals: [],
      career_totals: {
        itemized_individual_contribution_amount: "0.00",
        itemized_transaction_count: 0,
        unitemized_individual_contribution_amount: "0.00",
        total_individual_contribution_amount: "0.00",
        source: "none"
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
        small_dollar_amount: null,
        total_contribution_amount: null,
        share: null,
        available: false
      }
    };
    const requestJson = vi.fn((path: string): Promise<unknown> => {
      if (path === `/v1/person/${PERSON_ID}`) {
        return Promise.resolve(buildPersonDetail());
      }
      if (path === `/v1/candidates?person_id=${PERSON_ID}&limit=10&offset=0`) {
        return Promise.resolve({ items: [], has_next: false, offset: 0, limit: 10 });
      }
      if (path === `/v1/person/${PERSON_ID}/contribution-insights?cycle=2024`) {
        return contributionInsights.promise;
      }
      if (path === `/v1/person/${PERSON_ID}/top-donors?cycle=2024`) {
        return Promise.resolve([]);
      }
      if (path === `/v1/person/${PERSON_ID}/top-employers?cycle=2024`) {
        return Promise.resolve([]);
      }
      return Promise.reject(new Error(`unexpected path: ${path}`));
    });

    const loadPromise = load(
      createLoadEvent(requestJson, new URL(`https://example.test/person/${PERSON_ID}?cycle=2024`))
    ) as Promise<EntityDetailPageBundle>;

    try {
      for (let tick = 0; tick < 5; tick += 1) {
        await Promise.resolve();
      }

      expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
        `/v1/person/${PERSON_ID}`,
        `/v1/candidates?person_id=${PERSON_ID}&limit=10&offset=0`,
        `/v1/person/${PERSON_ID}/contribution-insights?cycle=2024`,
        `/v1/person/${PERSON_ID}/top-donors?cycle=2024`,
        `/v1/person/${PERSON_ID}/top-employers?cycle=2024`
      ]);
    } finally {
      contributionInsights.resolve(contributionInsightsPayload);
      await loadPromise;
    }
  });

  it("waits for the SSR headline result while keeping non-headline finance fields deferred", async () => {
    const contributionInsights = createDeferred<unknown>();
    const { requestJson } = createPersonRouteApi();
    const fallbackApi = createPersonRouteApi();
    requestJson.mockImplementation((path: string): Promise<unknown> => {
      if (path === `/v1/person/${PERSON_ID}/contribution-insights`) {
        return contributionInsights.promise;
      }

      return fallbackApi.requestJson(path);
    });
    let loadResolved = false;

    const loadPromise = (load(createLoadEvent(requestJson)) as Promise<EntityDetailPageBundle>).then((data) => {
      loadResolved = true;
      return data;
    });

    try {
      for (let tick = 0; tick < 5; tick += 1) {
        await Promise.resolve();
      }

      expect(loadResolved).toBe(false);
    } finally {
      contributionInsights.resolve({
        person_id: PERSON_ID,
        has_data: true,
        metadata: {
          ...SELECTED_CYCLE_FIELDS,
          cycles_included: [SELECTED_CYCLE_FIELDS.selected_cycle],
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
          itemized_individual_contribution_amount: "0.00",
          itemized_transaction_count: 0,
          unitemized_individual_contribution_amount: "0.00",
          total_individual_contribution_amount: "0.00",
          source: "none"
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
          small_dollar_amount: null,
          total_contribution_amount: null,
          share: null,
          available: false
        }
      });
      const data = await loadPromise;
      expect(data.personMoneyHeadline).toMatchObject({
        kind: "loaded",
        summary: { selected_cycle: 2026 }
      });
      expect(data.personContributionInsights).toBeInstanceOf(Promise);
      expect(data.personTopDonors).toBeInstanceOf(Promise);
      expect(data.personTopEmployers).toBeInstanceOf(Promise);
      expect(data.personFinanceSections).toBeInstanceOf(Promise);
    }
  });

  it("keeps bare person pages renderable with a backend-failure headline state", async () => {
    const contributionInsightsFailure = new ApiResponseError(503, {
      detail: "Contribution insights unavailable."
    });
    const requestJson = vi.fn((path: string): Promise<unknown> => {
      if (path === `/v1/person/${PERSON_ID}`) {
        return Promise.resolve(buildPersonDetail());
      }
      if (path === `/v1/person/${PERSON_ID}/contribution-insights`) {
        return Promise.reject(contributionInsightsFailure);
      }

      return Promise.reject(new Error(`unexpected path: ${path}`));
    });

    const data = (await load(createLoadEvent(requestJson))) as EntityDetailPageBundle;

    expect(data.personMoneyHeadline).toEqual({
      kind: "temporarily_unavailable",
      message: "Selected-cycle money summary is temporarily unavailable.",
      selectedCycle: 2026
    });
    await expect(data.personContributionInsights).resolves.toMatchObject({
      has_data: false,
      metadata: { caveats: ["temporarily_unavailable"] }
    });
    await expect(data.personFinanceSections).resolves.toEqual([]);
    await expect(data.personTopDonors).resolves.toEqual([]);
    await expect(data.personTopEmployers).resolves.toEqual([]);
    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      `/v1/person/${PERSON_ID}`,
      `/v1/person/${PERSON_ID}/contribution-insights`
    ]);
  });

  it("keeps person pages renderable when linked-candidate lookup fails", async () => {
    const { requestJson } = createPersonRouteApi();
    requestJson.mockImplementation((path: string): Promise<unknown> => {
      if (path === `/v1/candidates?person_id=${PERSON_ID}&limit=10&offset=0`) {
        return Promise.reject(new ApiResponseError(503, { detail: "Candidates unavailable." }));
      }

      return createPersonRouteApi().requestJson(path);
    });

    const data = (await load(createLoadEvent(requestJson))) as EntityDetailPageBundle;

    expect(data.personMoneyHeadline).toEqual({
      kind: "temporarily_unavailable",
      message: "Selected-cycle money summary is temporarily unavailable.",
      selectedCycle: 2026
    });
    await expect(data.personFinanceSections).rejects.toMatchObject({
      status: 503,
      body: { detail: "Candidates unavailable." }
    });
    await expect(data.personContributionInsights).resolves.toMatchObject({
      metadata: { selected_cycle: 2026 }
    });
  });

  it("resolves missing-summary as distinct from no-linked-candidacy for SSR", async () => {
    const summaryFailure = new ApiResponseError(404, { detail: "No candidate summary found." });
    const { requestJson } = createPersonRouteApi();
    requestJson.mockImplementation((path: string): Promise<unknown> => {
      if (path === `/v1/candidates/${CANDIDATE_ID}/summary?cycle=2026`) {
        return Promise.reject(summaryFailure);
      }

      return createPersonRouteApi().requestJson(path);
    });

    const data = (await load(createLoadEvent(requestJson))) as EntityDetailPageBundle;

    expect(data.personMoneyHeadline).toEqual({
      kind: "missing_summary",
      message: "Selected-cycle money summary is not available yet.",
      selectedCycle: 2026
    });
    await expect(data.personFinanceSections).resolves.toMatchObject([
      {
        candidate: { id: CANDIDATE_ID }
      }
    ]);
  });

  it("uses the backend-selected maximum supported cycle for bare person routes without redirecting", async () => {
    const { requestJson } = createPersonRouteApi();

    const data = (await load(createLoadEvent(requestJson))) as EntityDetailPageBundle;

    await expect(data.personContributionInsights).resolves.toMatchObject({
      metadata: {
        selected_cycle: 2026,
        available_cycles: [2022, 2024, 2026],
        coverage_start_date: "2025-01-01",
        coverage_end_date: "2026-12-31"
      }
    });
    if (data.personFinanceSections === undefined) {
      throw new Error("Expected person finance sections promise.");
    }
    const financeSections = await data.personFinanceSections;
    await Promise.all(financeSections.map((section) => section.donorVendorTransactions));
    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      `/v1/person/${PERSON_ID}`,
      `/v1/person/${PERSON_ID}/contribution-insights`,
      `/v1/candidates?person_id=${PERSON_ID}&limit=10&offset=0`,
      `/v1/person/${PERSON_ID}/top-donors?cycle=2026`,
      `/v1/person/${PERSON_ID}/top-employers?cycle=2026`,
      `/v1/candidates/${CANDIDATE_ID}`,
      `/v1/candidates/${CANDIDATE_ID}/summary?cycle=2026`,
      `/v1/candidates/${CANDIDATE_ID}/independent-expenditures?cycle=2026`,
      `/v1/candidates/${CANDIDATE_ID}/independent-expenditures/summary?cycle=2026`,
      `/v1/transactions?committee_id=${COMMITTEE_ID}&limit=25&cycle=2026`
    ]);
  });

  it.each([
    ["blank", `https://example.test/person/${PERSON_ID}?cycle=`],
    ["non-numeric", `https://example.test/person/${PERSON_ID}?cycle=abcd`],
    ["decimal", `https://example.test/person/${PERSON_ID}?cycle=2024.5`],
    ["too short", `https://example.test/person/${PERSON_ID}?cycle=24`],
    ["duplicated", `https://example.test/person/${PERSON_ID}?cycle=2024&cycle=2026`]
  ])("rejects malformed cycle query values before fetch: %s", async (_label, href) => {
    const requestJson = vi.fn();

    await expect(load(createLoadEvent(requestJson, new URL(href)))).rejects.toMatchObject({
      status: 400,
      body: INVALID_CYCLE_ERROR
    });
    expect(requestJson).not.toHaveBeenCalled();
  });

  it("surfaces unsupported explicit cycles as backend-owned route errors", async () => {
    const backendCycleError = {
      detail: {
        message: "Unsupported cycle.",
        selected_cycle: 2030,
        available_cycles: [2022, 2024, 2026]
      }
    };
    const requestJson = vi.fn(async (path: string): Promise<unknown> => {
      if (path === `/v1/person/${PERSON_ID}`) {
        return buildPersonDetail();
      }
      if (path === `/v1/candidates?person_id=${PERSON_ID}&limit=10&offset=0`) {
        return { items: [], has_next: false, offset: 0, limit: 10 };
      }
      if (path === `/v1/person/${PERSON_ID}/contribution-insights?cycle=2030`) {
        throw new ApiResponseError(400, backendCycleError);
      }
      if (path === `/v1/person/${PERSON_ID}/top-donors?cycle=2030`) {
        return [];
      }
      if (path === `/v1/person/${PERSON_ID}/top-employers?cycle=2030`) {
        return [];
      }
      throw new Error(`unexpected path: ${path}`);
    });

    await expect(
      load(createLoadEvent(requestJson, new URL(`https://example.test/person/${PERSON_ID}?cycle=2030`)))
    ).rejects.toMatchObject({
      status: 400,
      body: backendCycleError
    });
    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      `/v1/person/${PERSON_ID}`,
      `/v1/candidates?person_id=${PERSON_ID}&limit=10&offset=0`,
      `/v1/person/${PERSON_ID}/contribution-insights?cycle=2030`,
      `/v1/person/${PERSON_ID}/top-donors?cycle=2030`,
      `/v1/person/${PERSON_ID}/top-employers?cycle=2030`
    ]);
  });

  it("preserves backend 404 semantics", async () => {
    const requestJson = vi.fn().mockRejectedValue(new ApiResponseError(404, { detail: "Person not found" }));

    await expect(load(createLoadEvent(requestJson))).rejects.toMatchObject({
      status: 404,
      body: { detail: "Person not found" }
    });
  });

  it("preserves backend plain-text 404 semantics", async () => {
    const requestJson = vi.fn().mockRejectedValue(new ApiResponseError(404, "Person not found"));

    await expect(load(createLoadEvent(requestJson))).rejects.toMatchObject({
      status: 404,
      body: { message: "Person not found" }
    });
  });

  it("preserves backend malformed UUID 422 semantics", async () => {
    const requestJson = vi
      .fn()
      .mockRejectedValue(
        new ApiResponseError(422, { detail: [{ loc: ["path", "person_id"], msg: "Input should be a valid UUID" }] })
      );

    await expect(load(createLoadEvent(requestJson))).rejects.toMatchObject({
      status: 422,
      body: { detail: [{ loc: ["path", "person_id"], msg: "Input should be a valid UUID" }] }
    });
  });
});
