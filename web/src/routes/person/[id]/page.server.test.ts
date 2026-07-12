import { ApiResponseError } from "$lib/server/api/client";
import type { EntityDetailPageBundle } from "$lib/server/api/entity-detail";
import { describe, expect, it, vi } from "vitest";
import { load } from "./+page.server";

const PERSON_ID = "11111111-1111-4111-8111-111111111111";
const CANDIDATE_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const COMMITTEE_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";

function createLoadEvent(requestJson: ReturnType<typeof vi.fn>) {
  return {
    params: { id: PERSON_ID },
    locals: {
      api: {
        requestJson
      }
    }
  } as unknown as Parameters<typeof load>[0];
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

function createPersonRouteApi() {
  const personDetail = buildPersonDetail();

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

    if (path === `/v1/candidates/${CANDIDATE_ID}/summary`) {
      return {
        candidate_id: CANDIDATE_ID,
        candidate_name: "Candidate One",
        total_raised: "100.00",
        total_spent: "50.00",
        net: "50.00",
        transaction_count: 2,
        committees: []
      };
    }

    if (path === `/v1/candidates/${CANDIDATE_ID}/independent-expenditures`) {
      return [];
    }

    if (path === `/v1/candidates/${CANDIDATE_ID}/independent-expenditures/summary`) {
      return {
        candidate_id: CANDIDATE_ID,
        support_total: "0.00",
        oppose_total: "0.00",
        support_count: 0,
        oppose_count: 0,
        top_spenders: [],
        excluded_outlier_count: 0
      };
    }

    if (path === `/v1/person/${PERSON_ID}/contribution-insights`) {
      return {
        person_id: PERSON_ID,
        has_data: true,
        metadata: {
          coverage_start_date: "2022-01-01",
          coverage_end_date: null,
          cycles_included: [2022, 2024, 2026],
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

    if (path === `/v1/person/${PERSON_ID}/top-donors`) {
      return [{ name: "Top Donor", total_amount: "100.00", transaction_count: 1 }];
    }

    if (path === `/v1/person/${PERSON_ID}/top-employers`) {
      return [{ employer: "ACME CORP", total_amount: "100.00", transaction_count: 1 }];
    }

    if (path === `/v1/transactions?committee_id=${COMMITTEE_ID}&limit=25`) {
      return [];
    }

    throw new Error(`unexpected path: ${path}`);
  });

  return { personDetail, requestJson };
}

describe("/person/[id] +page.server load", () => {
  it("loads canonical person detail and person-linked finance without ER, graph, or civic-history fields", async () => {
    const { personDetail, requestJson } = createPersonRouteApi();

    const data = (await load(createLoadEvent(requestJson))) as EntityDetailPageBundle;

    expect(data.entityType).toBe("person");
    expect(data.detail).toBe(personDetail);
    expect("matches" in data).toBe(false);
    expect("relationships" in data).toBe(false);
    expect("personCivicHistory" in data).toBe(false);
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

  it("streams person contribution insights when the person has no linked candidates", async () => {
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
            coverage_start_date: "2022-01-01",
            coverage_end_date: null,
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

      if (path === `/v1/person/${PERSON_ID}/top-donors`) {
        return [];
      }

      if (path === `/v1/person/${PERSON_ID}/top-employers`) {
        return [];
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as EntityDetailPageBundle;

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
      `/v1/person/${PERSON_ID}/top-donors`
    );
    expect(requestJson.mock.calls.map(([path]) => path)).toContain(
      `/v1/person/${PERSON_ID}/top-employers`
    );
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
