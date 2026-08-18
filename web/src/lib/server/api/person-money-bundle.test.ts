import type { ApiClient } from "./client";
import { ApiResponseError } from "./client";
import { describe, expect, it, vi } from "vitest";
import { loadPersonMoneyBundle } from "./person-money-bundle";

const PERSON_ID = "11111111-1111-4111-8111-111111111111";
const CANDIDATE_ID = "22222222-2222-4222-8222-222222222222";
const SECOND_CANDIDATE_ID = "33333333-3333-4333-8333-333333333333";
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
        return {
          ...buildCandidateSummary(),
          candidate_id: CANDIDATE_ID,
          selected_cycle: SELECTED_CYCLE
        };
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
        return [
          {
            employer: "Employer",
            total_amount: "100.00",
            transaction_count: 1,
            industry: "UNKNOWN_INDUSTRY",
            industry_rollup_eligible: true
          }
        ];
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

  it("builds a resolved finance-rich headline without resolving donor, employer, or IE detail", async () => {
    const ieSummary = createDeferred<unknown>();
    const topDonors = createDeferred<unknown>();
    const topEmployers = createDeferred<unknown>();
    const requestJson = vi.fn((path: string): Promise<unknown> => {
      if (path === `/v1/person/${PERSON_ID}/contribution-insights`) {
        return Promise.resolve(buildContributionInsights(SELECTED_CYCLE));
      }
      if (path === `/v1/candidates?person_id=${PERSON_ID}&limit=10&offset=0`) {
        return Promise.resolve({
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
        });
      }
      if (path === `/v1/candidates/${CANDIDATE_ID}`) {
        return Promise.resolve(buildCandidateDetail());
      }
      if (path === `/v1/candidates/${CANDIDATE_ID}/summary?cycle=${SELECTED_CYCLE}`) {
        return Promise.resolve(buildCandidateSummary());
      }
      if (
        path === `/v1/candidates/${CANDIDATE_ID}/independent-expenditures?cycle=${SELECTED_CYCLE}`
      ) {
        return Promise.resolve([]);
      }
      if (
        path ===
        `/v1/candidates/${CANDIDATE_ID}/independent-expenditures/summary?cycle=${SELECTED_CYCLE}`
      ) {
        return ieSummary.promise;
      }
      if (path === `/v1/person/${PERSON_ID}/top-donors?cycle=${SELECTED_CYCLE}`) {
        return topDonors.promise;
      }
      if (path === `/v1/person/${PERSON_ID}/top-employers?cycle=${SELECTED_CYCLE}`) {
        return topEmployers.promise;
      }

      return Promise.reject(new Error(`Unexpected path: ${path}`));
    });

    const bundle = loadPersonMoneyBundle(createApi(requestJson), PERSON_ID);

    await expect(bundle.personMoneyHeadline).resolves.toMatchObject({
      kind: "loaded",
      summary: {
        selected_cycle: SELECTED_CYCLE,
        total_raised: "1234.56",
        total_spent: "789.10",
        cash_on_hand: "300.00",
        debts_owed_by_committee: "50.00"
      }
    });
    await expect(Promise.race([bundle.personTopDonors, Promise.resolve("still-deferred")])).resolves.toBe(
      "still-deferred"
    );
    await expect(Promise.race([bundle.personTopEmployers, Promise.resolve("still-deferred")])).resolves.toBe(
      "still-deferred"
    );
    const sections = await bundle.personFinanceSections;
    await expect(Promise.race([sections[0]!.ieSummary, Promise.resolve("still-deferred")])).resolves.toBe(
      "still-deferred"
    );

    ieSummary.resolve(null);
    topDonors.resolve([]);
    topEmployers.resolve([]);
    await Promise.all([sections[0]!.ieSummary, bundle.personTopDonors, bundle.personTopEmployers]);
  });

  it("builds a no-linked-candidacy headline when candidate lookup is empty", async () => {
    const requestJson = vi.fn((path: string): Promise<unknown> => {
      if (path === `/v1/person/${PERSON_ID}/contribution-insights`) {
        return Promise.resolve(buildContributionInsights(SELECTED_CYCLE));
      }
      if (path === `/v1/candidates?person_id=${PERSON_ID}&limit=10&offset=0`) {
        return Promise.resolve({ items: [], has_next: false, offset: 0, limit: 10 });
      }
      if (path === `/v1/person/${PERSON_ID}/top-donors?cycle=${SELECTED_CYCLE}`) {
        return Promise.resolve([]);
      }
      if (path === `/v1/person/${PERSON_ID}/top-employers?cycle=${SELECTED_CYCLE}`) {
        return Promise.resolve([]);
      }

      return Promise.reject(new Error(`Unexpected path: ${path}`));
    });

    const bundle = loadPersonMoneyBundle(createApi(requestJson), PERSON_ID);

    await expect(bundle.personMoneyHeadline).resolves.toEqual({
      kind: "no_linked_candidate",
      message: "No campaign-finance candidacies are linked yet."
    });
  });

  it("builds a missing-summary headline when a linked candidate lacks selected-cycle summary", async () => {
    const requestJson = vi.fn((path: string): Promise<unknown> => {
      if (path === `/v1/person/${PERSON_ID}/contribution-insights`) {
        return Promise.resolve(buildContributionInsights(SELECTED_CYCLE));
      }
      if (path === `/v1/candidates?person_id=${PERSON_ID}&limit=10&offset=0`) {
        return Promise.resolve({
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
        });
      }
      if (path === `/v1/candidates/${CANDIDATE_ID}`) {
        return Promise.resolve(buildCandidateDetail());
      }
      if (path === `/v1/candidates/${CANDIDATE_ID}/summary?cycle=${SELECTED_CYCLE}`) {
        return Promise.reject(new ApiResponseError(404, { detail: "No summary found." }));
      }
      if (
        path === `/v1/candidates/${CANDIDATE_ID}/independent-expenditures?cycle=${SELECTED_CYCLE}`
      ) {
        return Promise.resolve([]);
      }
      if (
        path ===
        `/v1/candidates/${CANDIDATE_ID}/independent-expenditures/summary?cycle=${SELECTED_CYCLE}`
      ) {
        return Promise.resolve(null);
      }
      if (path === `/v1/person/${PERSON_ID}/top-donors?cycle=${SELECTED_CYCLE}`) {
        return Promise.resolve([]);
      }
      if (path === `/v1/person/${PERSON_ID}/top-employers?cycle=${SELECTED_CYCLE}`) {
        return Promise.resolve([]);
      }

      return Promise.reject(new Error(`Unexpected path: ${path}`));
    });

    const bundle = loadPersonMoneyBundle(createApi(requestJson), PERSON_ID);

    await expect(bundle.personMoneyHeadline).resolves.toEqual({
      kind: "missing_summary",
      message: "Selected-cycle money summary is not available yet.",
      selectedCycle: SELECTED_CYCLE
    });
  });

  it("builds a not-loaded headline when the linked candidate summary carries not_loaded coverage", async () => {
    // A 200 response with zero-valued money fields is NOT proof of zero money. The
    // backend ships the honest discriminator on `coverage.activity_state`; the person
    // headline must read it instead of treating "0.00" as a loaded fact. See
    // docs/reference/screen_specs/person_detail.md ("Money at a glance").
    const requestJson = vi.fn((path: string): Promise<unknown> => {
      if (path === `/v1/person/${PERSON_ID}/contribution-insights`) {
        return Promise.resolve(buildContributionInsights(SELECTED_CYCLE));
      }
      if (path === `/v1/candidates?person_id=${PERSON_ID}&limit=10&offset=0`) {
        return Promise.resolve({
          items: [buildCandidateListItem(CANDIDATE_ID, "Candidate One")],
          has_next: false,
          offset: 0,
          limit: 10
        });
      }
      if (path === `/v1/candidates/${CANDIDATE_ID}`) {
        return Promise.resolve(buildCandidateDetail());
      }
      if (path === `/v1/candidates/${CANDIDATE_ID}/summary?cycle=${SELECTED_CYCLE}`) {
        return Promise.resolve(buildNotLoadedCandidateSummary());
      }
      if (path.includes("/independent-expenditures")) {
        return Promise.resolve(path.includes("/summary") ? null : []);
      }
      if (path === `/v1/person/${PERSON_ID}/top-donors?cycle=${SELECTED_CYCLE}`) {
        return Promise.resolve([]);
      }
      if (path === `/v1/person/${PERSON_ID}/top-employers?cycle=${SELECTED_CYCLE}`) {
        return Promise.resolve([]);
      }

      return Promise.reject(new Error(`Unexpected path: ${path}`));
    });

    const bundle = loadPersonMoneyBundle(createApi(requestJson), PERSON_ID);

    const headline = await bundle.personMoneyHeadline;

    expect(headline.kind).toBe("not_loaded");
    expect(headline).toMatchObject({
      message:
        "A linked FEC candidate exists for this person, but Civibus has not loaded authoritative selected-cycle fundraising evidence for that candidate.",
      selectedCycle: SELECTED_CYCLE
    });

    // The aggregate summary rides along so the render layer can keep the cycle
    // switcher. It must still carry the honest discriminator, and its money
    // values stay placeholders that no figure may be rendered from.
    if (headline.kind !== "not_loaded") {
      throw new Error("expected the not_loaded arm");
    }
    expect(headline.summary.coverage.activity_state).toBe("not_loaded");
    expect(headline.summary.available_cycles).toContain(SELECTED_CYCLE);
  });

  it("keeps the loaded headline when every linked candidate summary proves loaded-zero coverage", async () => {
    // Guard against over-suppression: `loaded_zero` is authoritative evidence that the
    // candidate genuinely raised and spent nothing in the selected cycle, so the
    // headline must stay `loaded` and keep rendering real zeroes.
    const requestJson = vi.fn((path: string): Promise<unknown> => {
      if (path === `/v1/person/${PERSON_ID}/contribution-insights`) {
        return Promise.resolve(buildContributionInsights(SELECTED_CYCLE));
      }
      if (path === `/v1/candidates?person_id=${PERSON_ID}&limit=10&offset=0`) {
        return Promise.resolve({
          items: [buildCandidateListItem(CANDIDATE_ID, "Candidate One")],
          has_next: false,
          offset: 0,
          limit: 10
        });
      }
      if (path === `/v1/candidates/${CANDIDATE_ID}`) {
        return Promise.resolve(buildCandidateDetail());
      }
      if (path === `/v1/candidates/${CANDIDATE_ID}/summary?cycle=${SELECTED_CYCLE}`) {
        return Promise.resolve(buildLoadedZeroCandidateSummary());
      }
      if (path.includes("/independent-expenditures")) {
        return Promise.resolve(path.includes("/summary") ? null : []);
      }
      if (path === `/v1/person/${PERSON_ID}/top-donors?cycle=${SELECTED_CYCLE}`) {
        return Promise.resolve([]);
      }
      if (path === `/v1/person/${PERSON_ID}/top-employers?cycle=${SELECTED_CYCLE}`) {
        return Promise.resolve([]);
      }

      return Promise.reject(new Error(`Unexpected path: ${path}`));
    });

    const bundle = loadPersonMoneyBundle(createApi(requestJson), PERSON_ID);

    await expect(bundle.personMoneyHeadline).resolves.toMatchObject({
      kind: "loaded",
      summary: {
        selected_cycle: SELECTED_CYCLE,
        total_raised: "0.00",
        total_spent: "0.00",
        coverage: {
          activity_state: "loaded_zero",
          completeness: "complete",
          basis: "authoritative_load_evidence"
        }
      }
    });
  });

  it("prioritizes backend failure over missing summary across linked candidates", async () => {
    const requestJson = vi.fn((path: string): Promise<unknown> => {
      if (path === `/v1/person/${PERSON_ID}/contribution-insights`) {
        return Promise.resolve(buildContributionInsights(SELECTED_CYCLE));
      }
      if (path === `/v1/candidates?person_id=${PERSON_ID}&limit=10&offset=0`) {
        return Promise.resolve({
          items: [
            buildCandidateListItem(CANDIDATE_ID, "Candidate One"),
            buildCandidateListItem(SECOND_CANDIDATE_ID, "Candidate Two")
          ],
          has_next: false,
          offset: 0,
          limit: 10
        });
      }
      if (path === `/v1/candidates/${CANDIDATE_ID}`) {
        return Promise.resolve(buildCandidateDetail());
      }
      if (path === `/v1/candidates/${SECOND_CANDIDATE_ID}`) {
        return Promise.resolve(buildCandidateDetail(SECOND_CANDIDATE_ID, "Candidate Two"));
      }
      if (path === `/v1/candidates/${CANDIDATE_ID}/summary?cycle=${SELECTED_CYCLE}`) {
        return Promise.reject(new ApiResponseError(404, { detail: "No summary found." }));
      }
      if (path === `/v1/candidates/${SECOND_CANDIDATE_ID}/summary?cycle=${SELECTED_CYCLE}`) {
        return Promise.reject(new ApiResponseError(503, { detail: "Summary unavailable." }));
      }
      if (path.includes("/independent-expenditures")) {
        return Promise.resolve(path.includes("/summary") ? null : []);
      }
      if (path === `/v1/person/${PERSON_ID}/top-donors?cycle=${SELECTED_CYCLE}`) {
        return Promise.resolve([]);
      }
      if (path === `/v1/person/${PERSON_ID}/top-employers?cycle=${SELECTED_CYCLE}`) {
        return Promise.resolve([]);
      }

      return Promise.reject(new Error(`Unexpected path: ${path}`));
    });

    const bundle = loadPersonMoneyBundle(createApi(requestJson), PERSON_ID);

    await expect(bundle.personMoneyHeadline).resolves.toEqual({
      kind: "temporarily_unavailable",
      message: "Selected-cycle money summary is temporarily unavailable.",
      selectedCycle: SELECTED_CYCLE
    });
  });

  it("uses the temporary-unavailable headline when linked summaries violate the cycle contract", async () => {
    const requestJson = vi.fn((path: string): Promise<unknown> => {
      if (path === `/v1/person/${PERSON_ID}/contribution-insights`) {
        return Promise.resolve(buildContributionInsights(SELECTED_CYCLE));
      }
      if (path === `/v1/candidates?person_id=${PERSON_ID}&limit=10&offset=0`) {
        return Promise.resolve({
          items: [
            buildCandidateListItem(CANDIDATE_ID, "Candidate One"),
            buildCandidateListItem(SECOND_CANDIDATE_ID, "Candidate Two")
          ],
          has_next: false,
          offset: 0,
          limit: 10
        });
      }
      if (path === `/v1/candidates/${CANDIDATE_ID}`) {
        return Promise.resolve(buildCandidateDetail());
      }
      if (path === `/v1/candidates/${SECOND_CANDIDATE_ID}`) {
        return Promise.resolve(buildCandidateDetail(SECOND_CANDIDATE_ID, "Candidate Two"));
      }
      if (path === `/v1/candidates/${CANDIDATE_ID}/summary?cycle=${SELECTED_CYCLE}`) {
        return Promise.resolve(buildCandidateSummary());
      }
      if (path === `/v1/candidates/${SECOND_CANDIDATE_ID}/summary?cycle=${SELECTED_CYCLE}`) {
        return Promise.resolve({
          ...buildCandidateSummary(),
          candidate_id: SECOND_CANDIDATE_ID,
          candidate_name: "Candidate Two",
          selected_cycle: SELECTED_CYCLE - 2
        });
      }
      if (path.includes("/independent-expenditures")) {
        return Promise.resolve(path.includes("/summary") ? null : []);
      }
      if (path === `/v1/person/${PERSON_ID}/top-donors?cycle=${SELECTED_CYCLE}`) {
        return Promise.resolve([]);
      }
      if (path === `/v1/person/${PERSON_ID}/top-employers?cycle=${SELECTED_CYCLE}`) {
        return Promise.resolve([]);
      }

      return Promise.reject(new Error(`Unexpected path: ${path}`));
    });

    const bundle = loadPersonMoneyBundle(createApi(requestJson), PERSON_ID);

    await expect(bundle.personMoneyHeadline).resolves.toEqual({
      kind: "temporarily_unavailable",
      message: "Selected-cycle money summary is temporarily unavailable.",
      selectedCycle: SELECTED_CYCLE
    });
  });

  it("keeps backend failures distinct from honest absence", async () => {
    const requestJson = vi.fn((path: string): Promise<unknown> => {
      if (path === `/v1/person/${PERSON_ID}/contribution-insights`) {
        return Promise.reject(new Error("insights unavailable"));
      }

      return Promise.reject(new Error(`Unexpected path: ${path}`));
    });

    const bundle = loadPersonMoneyBundle(createApi(requestJson), PERSON_ID, {
      fallbackWhenBackendSelectedInsightsUnavailable: true
    });

    await expect(bundle.personMoneyHeadline).resolves.toEqual({
      kind: "temporarily_unavailable",
      message: "Selected-cycle money summary is temporarily unavailable.",
      selectedCycle: SELECTED_CYCLE
    });
  });

  it("builds a temporary-unavailable headline when candidate lookup fails", async () => {
    const requestJson = vi.fn((path: string): Promise<unknown> => {
      if (path === `/v1/person/${PERSON_ID}/contribution-insights`) {
        return Promise.resolve(buildContributionInsights(SELECTED_CYCLE));
      }
      if (path === `/v1/candidates?person_id=${PERSON_ID}&limit=10&offset=0`) {
        return Promise.reject(new Error("candidate lookup unavailable"));
      }
      if (path === `/v1/person/${PERSON_ID}/top-donors?cycle=${SELECTED_CYCLE}`) {
        return Promise.resolve([]);
      }
      if (path === `/v1/person/${PERSON_ID}/top-employers?cycle=${SELECTED_CYCLE}`) {
        return Promise.resolve([]);
      }

      return Promise.reject(new Error(`Unexpected path: ${path}`));
    });

    const bundle = loadPersonMoneyBundle(createApi(requestJson), PERSON_ID);

    await expect(bundle.personMoneyHeadline).resolves.toEqual({
      kind: "temporarily_unavailable",
      message: "Selected-cycle money summary is temporarily unavailable.",
      selectedCycle: SELECTED_CYCLE
    });
    await expect(bundle.personFinanceSections).rejects.toThrow("candidate lookup unavailable");
  });

  it("builds a temporary-unavailable headline when candidate detail lookup fails", async () => {
    const requestJson = vi.fn((path: string): Promise<unknown> => {
      if (path === `/v1/person/${PERSON_ID}/contribution-insights`) {
        return Promise.resolve(buildContributionInsights(SELECTED_CYCLE));
      }
      if (path === `/v1/candidates?person_id=${PERSON_ID}&limit=10&offset=0`) {
        return Promise.resolve({
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
        });
      }
      if (path === `/v1/candidates/${CANDIDATE_ID}`) {
        return Promise.reject(new Error("candidate detail unavailable"));
      }
      if (path === `/v1/person/${PERSON_ID}/top-donors?cycle=${SELECTED_CYCLE}`) {
        return Promise.resolve([]);
      }
      if (path === `/v1/person/${PERSON_ID}/top-employers?cycle=${SELECTED_CYCLE}`) {
        return Promise.resolve([]);
      }

      return Promise.reject(new Error(`Unexpected path: ${path}`));
    });

    const bundle = loadPersonMoneyBundle(createApi(requestJson), PERSON_ID);

    await expect(bundle.personMoneyHeadline).resolves.toEqual({
      kind: "temporarily_unavailable",
      message: "Selected-cycle money summary is temporarily unavailable.",
      selectedCycle: SELECTED_CYCLE
    });
    await expect(bundle.personFinanceSections).rejects.toThrow("candidate detail unavailable");
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

function buildCandidateListItem(id: string, name: string) {
  return {
    id,
    fec_candidate_id: "H0NC01001",
    name,
    person_id: PERSON_ID,
    party: "DEM",
    office: "H",
    state: "NC",
    district: "01",
    slug: name.toLowerCase().replaceAll(" ", "-"),
    slug_is_unique: true,
    identity_is_safe: true
  };
}

function buildCandidateDetail(id = CANDIDATE_ID, name = "Candidate One") {
  return {
    id,
    fec_candidate_id: "H0NC01001",
    name,
    slug: name.toLowerCase().replaceAll(" ", "-"),
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

/**
 * Mirrors the backend's not-loaded candidate summary payload
 * (`_not_loaded_candidate_money_coverage` in `api/queries/campaign_finance.py`):
 * zero-valued money strings alongside a `not_loaded` discriminator and null
 * optional money. The zeros here are placeholders, not evidence.
 */
function buildNotLoadedCandidateSummary() {
  return {
    ...buildCandidateSummary(),
    total_raised: "0.00",
    total_spent: "0.00",
    net: "0.00",
    transaction_count: 0,
    itemized_transaction_count: 0,
    cash_on_hand: null,
    net_self_funding: null,
    debts_owed_by_committee: null,
    summary_source: "derived" as const,
    receipt_source_composition: [],
    selected_cycle_coverage_complete: false,
    can_render_share: false,
    receipt_source_caveats: ["missing_committee_summary"],
    coverage: {
      activity_state: "not_loaded" as const,
      completeness: "unknown" as const,
      basis: "no_authoritative_load_evidence" as const
    }
  };
}

/**
 * Genuine no-money coverage: the loader ran, produced authoritative evidence, and
 * that evidence says zero. These zeroes are facts and must survive presentation.
 */
function buildLoadedZeroCandidateSummary() {
  return {
    ...buildCandidateSummary(),
    total_raised: "0.00",
    total_spent: "0.00",
    net: "0.00",
    transaction_count: 0,
    itemized_transaction_count: 0,
    cash_on_hand: "0.00",
    net_self_funding: null,
    debts_owed_by_committee: "0.00",
    receipt_source_composition: [],
    coverage: {
      activity_state: "loaded_zero" as const,
      completeness: "complete" as const,
      basis: "authoritative_load_evidence" as const
    }
  };
}

function buildCandidateSummary() {
  return {
    selected_cycle: SELECTED_CYCLE,
    coverage_start_date: "2025-01-01",
    coverage_end_date: "2026-12-31",
    available_cycles: [2024, 2026],
    candidate_id: CANDIDATE_ID,
    candidate_name: "Candidate One",
    total_raised: "1234.56",
    total_spent: "789.10",
    net: "445.46",
    transaction_count: 3,
    itemized_transaction_count: 3,
    cash_on_hand: "300.00",
    net_self_funding: null,
    debts_owed_by_committee: "50.00",
    summary_source: "fec_weball" as const,
    receipt_source_composition: [
      {
        label: "Gross individual contributions",
        total_amount: "1234.56",
        source: "fec_committee_summary" as const
      }
    ],
    selected_cycle_coverage_complete: true,
    can_render_share: true,
    receipt_source_caveats: [],
    committees: [],
    coverage: {
      activity_state: "populated" as const,
      completeness: "complete" as const,
      basis: "fec_official_candidate_summary" as const
    }
  };
}
