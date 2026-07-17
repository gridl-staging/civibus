import type { ApiClient } from "./client";
import { describe, expect, it, vi } from "vitest";
import { loadPersonMoneyBundle } from "./person-money-bundle";

const PERSON_ID = "11111111-1111-4111-8111-111111111111";
const CANDIDATE_ID = "22222222-2222-4222-8222-222222222222";
const SELECTED_CYCLE = 2026;

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolver) => {
    resolve = resolver;
  });

  return { promise, resolve };
}

function buildContributionInsights(selectedCycle: number) {
  return {
    person_id: PERSON_ID,
    has_data: true,
    metadata: {
      selected_cycle: selectedCycle,
      coverage_start_date: `${selectedCycle - 1}-01-01`,
      coverage_end_date: `${selectedCycle}-12-31`,
      available_cycles: [2024, 2026],
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

function createApi(requestJson: ReturnType<typeof vi.fn>): ApiClient {
  return { requestJson } as unknown as ApiClient;
}

describe("loadPersonMoneyBundle", () => {
  it("derives one selected cycle before loading every remaining money field", async () => {
    const requestJson = vi.fn(async (path: string): Promise<unknown> => {
      if (path === `/v1/person/${PERSON_ID}/contribution-insights`) {
        return buildContributionInsights(SELECTED_CYCLE);
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
          principal_committee_id: null,
          sources: []
        };
      }
      if (path === `/v1/candidates/${CANDIDATE_ID}/summary?cycle=${SELECTED_CYCLE}`) {
        return { committees: [] };
      }
      if (
        path === `/v1/candidates/${CANDIDATE_ID}/independent-expenditures?cycle=${SELECTED_CYCLE}`
      ) {
        return [];
      }
      if (
        path ===
        `/v1/candidates/${CANDIDATE_ID}/independent-expenditures/summary?cycle=${SELECTED_CYCLE}`
      ) {
        return null;
      }
      if (path === `/v1/person/${PERSON_ID}/top-donors?cycle=${SELECTED_CYCLE}`) {
        return [{ name: "Donor", total_amount: "100.00", transaction_count: 1 }];
      }
      if (path === `/v1/person/${PERSON_ID}/top-employers?cycle=${SELECTED_CYCLE}`) {
        return [{ employer: "Employer", total_amount: "100.00", transaction_count: 1 }];
      }

      throw new Error(`Unexpected path: ${path}`);
    });

    const bundle = await loadPersonMoneyBundle(createApi(requestJson), PERSON_ID);
    await Promise.all([
      bundle.personContributionInsights,
      bundle.personFinanceSections,
      bundle.personTopDonors,
      bundle.personTopEmployers
    ]);

    const paths = requestJson.mock.calls.map(([path]) => path);
    expect(paths[0]).toBe(`/v1/person/${PERSON_ID}/contribution-insights`);
    expect(paths).toContain(`/v1/candidates/${CANDIDATE_ID}/summary?cycle=${SELECTED_CYCLE}`);
    expect(paths).toContain(`/v1/person/${PERSON_ID}/top-donors?cycle=${SELECTED_CYCLE}`);
    expect(paths).toContain(`/v1/person/${PERSON_ID}/top-employers?cycle=${SELECTED_CYCLE}`);
  });

  it("eagerly starts explicit-cycle fetches but waits for contribution insights", async () => {
    const contributionInsights = createDeferred<unknown>();
    const requestJson = vi.fn((path: string): Promise<unknown> => {
      if (path === `/v1/person/${PERSON_ID}/contribution-insights?cycle=2024`) {
        return contributionInsights.promise;
      }
      if (path === `/v1/candidates?person_id=${PERSON_ID}&limit=10&offset=0`) {
        return Promise.resolve({ items: [], has_next: false, offset: 0, limit: 10 });
      }
      if (path === `/v1/person/${PERSON_ID}/top-donors?cycle=2024`) {
        return Promise.resolve([]);
      }
      if (path === `/v1/person/${PERSON_ID}/top-employers?cycle=2024`) {
        return Promise.resolve([]);
      }

      return Promise.reject(new Error(`Unexpected path: ${path}`));
    });
    let bundleResolved = false;

    const bundlePromise = loadPersonMoneyBundle(createApi(requestJson), PERSON_ID, 2024).then(
      (bundle) => {
        bundleResolved = true;
        return bundle;
      }
    );

    await Promise.resolve();
    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      `/v1/candidates?person_id=${PERSON_ID}&limit=10&offset=0`,
      `/v1/person/${PERSON_ID}/contribution-insights?cycle=2024`,
      `/v1/person/${PERSON_ID}/top-donors?cycle=2024`,
      `/v1/person/${PERSON_ID}/top-employers?cycle=2024`
    ]);
    expect(bundleResolved).toBe(false);

    contributionInsights.resolve(buildContributionInsights(2024));
    const bundle = await bundlePromise;
    await expect(bundle.personContributionInsights).resolves.toMatchObject({
      metadata: { selected_cycle: 2024 }
    });
  });

  it("rejects backend-selected money streams by default when contribution insights fail", async () => {
    const requestJson = vi.fn((path: string): Promise<unknown> => {
      if (path === `/v1/person/${PERSON_ID}/contribution-insights`) {
        return Promise.reject(new Error("insights unavailable"));
      }

      return Promise.reject(new Error(`Unexpected path: ${path}`));
    });

    const bundle = loadPersonMoneyBundle(createApi(requestJson), PERSON_ID);

    await expect(bundle.personContributionInsights).rejects.toThrow("insights unavailable");
    await expect(bundle.personFinanceSections).rejects.toThrow("insights unavailable");
    await expect(bundle.personTopDonors).rejects.toThrow("insights unavailable");
    await expect(bundle.personTopEmployers).rejects.toThrow("insights unavailable");
    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      `/v1/person/${PERSON_ID}/contribution-insights`
    ]);
  });

  it("resolves empty optional money data when opted into backend-selected fallback", async () => {
    const requestJson = vi.fn((path: string): Promise<unknown> => {
      if (path === `/v1/person/${PERSON_ID}/contribution-insights`) {
        return Promise.reject(new Error("insights unavailable"));
      }

      return Promise.reject(new Error(`Unexpected path: ${path}`));
    });

    const bundle = loadPersonMoneyBundle(createApi(requestJson), PERSON_ID, {
      fallbackWhenBackendSelectedInsightsUnavailable: true
    });

    await expect(bundle.personContributionInsights).resolves.toMatchObject({
      person_id: PERSON_ID,
      has_data: false,
      metadata: {
        selected_cycle: 2026,
        caveats: ["temporarily_unavailable"]
      }
    });
    await expect(bundle.personFinanceSections).resolves.toEqual([]);
    await expect(bundle.personTopDonors).resolves.toEqual([]);
    await expect(bundle.personTopEmployers).resolves.toEqual([]);
    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      `/v1/person/${PERSON_ID}/contribution-insights`
    ]);
  });
});
