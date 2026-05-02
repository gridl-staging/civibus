import { ApiResponseError } from "$lib/server/api/client";
import type { EntityDetailBundle } from "$lib/server/api/entity-detail";
import { describe, expect, it, vi } from "vitest";
import { load } from "./+page.server";

const PERSON_ID = "11111111-1111-4111-8111-111111111111";

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

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolver) => {
    resolve = resolver;
  });
  return { promise, resolve };
}

describe("/person/[id] +page.server load", () => {
  it("loads person civic-history and person-linked finance sections through existing API owners", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === `/v1/person/${PERSON_ID}`) {
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

      if (path === `/v1/er/person/${PERSON_ID}/matches`) {
        return [];
      }

      if (path === `/v1/graph/person/${PERSON_ID}/relationships`) {
        return {
          entity_type: "person",
          entity_id: PERSON_ID,
          neighbors: [
            {
              entity_type: "officeholding",
              entity_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
              name: "Officeholding A",
              relationship_type: "HOLDS",
              direction: "outbound"
            },
            {
              entity_type: "candidacy",
              entity_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
              name: "Candidacy A",
              relationship_type: "CANDIDACY_OF",
              direction: "outbound"
            }
          ],
          total_count: 2
        };
      }

      if (path === "/v1/officeholdings/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa") {
        return {
          id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
          person_id: PERSON_ID,
          person_name: "Jane Doe",
          office_id: "office-1",
          electoral_division_id: null,
          holder_status: "elected",
          valid_period_lower: "2025-01-01",
          valid_period_upper: null,
          date_precision: "day",
          sources: []
        };
      }

      if (path === "/v1/candidacies/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb") {
        return {
          id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
          person_id: PERSON_ID,
          person_name: "Jane Doe",
          contest_id: "contest-1",
          party: "DEM",
          filing_date: "2026-01-10",
          status: "qualified",
          incumbent_challenge: "I",
          candidate_number: "17",
          sources: []
        };
      }

      if (path === `/v1/candidates?person_id=${PERSON_ID}&limit=10&offset=0`) {
        return {
          items: [
            {
              id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
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

      if (path === "/v1/candidates/cccccccc-cccc-4ccc-8ccc-cccccccccccc") {
        return {
          id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
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
          principal_committee_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
          sources: []
        };
      }

      if (path === "/v1/candidates/cccccccc-cccc-4ccc-8ccc-cccccccccccc/summary") {
        return {
          candidate_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
          candidate_name: "Candidate One",
          total_raised: "100.00",
          total_spent: "50.00",
          net: "50.00",
          transaction_count: 2,
          committees: []
        };
      }

      if (path === "/v1/candidates/cccccccc-cccc-4ccc-8ccc-cccccccccccc/independent-expenditures") {
        return [];
      }

      if (path === "/v1/candidates/cccccccc-cccc-4ccc-8ccc-cccccccccccc/independent-expenditures/summary") {
        return {
          candidate_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
          support_total: "0.00",
          oppose_total: "0.00",
          support_count: 0,
          oppose_count: 0,
          top_spenders: []
        };
      }

      if (path === "/v1/transactions?committee_id=dddddddd-dddd-4ddd-8ddd-dddddddddddd&limit=25") {
        return [];
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as EntityDetailBundle & {
      personCivicHistory?: Promise<unknown>;
      personFinanceSections?: Promise<unknown>;
    };

    expect(data.personCivicHistory).toBeInstanceOf(Promise);
    expect(data.personFinanceSections).toBeInstanceOf(Promise);
    await expect(data.personCivicHistory).resolves.toMatchObject({
      officeholdings: [{ id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" }],
      candidacies: [{ id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb" }]
    });
    await expect(data.personFinanceSections).resolves.toMatchObject([
      {
        candidate: { id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc" }
      }
    ]);
  });

  it("returns streaming matches/relationships promises so the detail page can render loading skeletons", async () => {
    const deferredMatches = createDeferred<any[]>();
    const deferredRelationships = createDeferred<any>();

    const requestJson = vi.fn(async (path: string) => {
      if (path === `/v1/person/${PERSON_ID}`) {
        return {
          id: PERSON_ID,
          canonical_name: "Jane Doe",
          name_variants: [],
          first_name: "Jane",
          middle_name: null,
          last_name: "Doe",
          suffix: null,
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
          portrait: {
            status: "active",
            rights_status: "licensed",
            source_image_url: "https://images.example.org/jane-doe.jpg",
            mime_type: "image/jpeg",
            width_px: 640,
            height_px: 480
          },
          sources: []
        };
      }

      if (path === `/v1/er/person/${PERSON_ID}/matches`) {
        return deferredMatches.promise;
      }

      if (path === `/v1/graph/person/${PERSON_ID}/relationships`) {
        return deferredRelationships.promise;
      }

      if (path === `/v1/candidates?person_id=${PERSON_ID}&limit=10&offset=0`) {
        return {
          items: [],
          has_next: false,
          offset: 0,
          limit: 10
        };
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as EntityDetailBundle;

    expect("portrait" in data.detail).toBe(true);
    if (!("portrait" in data.detail)) {
      throw new Error("expected person detail payload");
    }
    expect(data.detail.portrait).toEqual({
      status: "active",
      rights_status: "licensed",
      source_image_url: "https://images.example.org/jane-doe.jpg",
      mime_type: "image/jpeg",
      width_px: 640,
      height_px: 480
    });
    expect(data.matches).toBeInstanceOf(Promise);
    expect(data.relationships).toBeInstanceOf(Promise);
    expect(requestJson).toHaveBeenCalledTimes(4);

    deferredMatches.resolve([]);
    deferredRelationships.resolve({
      entity_type: "person",
      entity_id: PERSON_ID,
      neighbors: [],
      total_count: 0
    });

    await expect(data.matches).resolves.toEqual([]);
    await expect(data.relationships).resolves.toMatchObject({ total_count: 0 });
  });

  it("composes detail + ER + graph through event.locals.api and keeps empty panels successful", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === `/v1/person/${PERSON_ID}`) {
        return {
          id: PERSON_ID,
          canonical_name: "Jane Doe",
          name_variants: [],
          first_name: "Jane",
          middle_name: null,
          last_name: "Doe",
          suffix: null,
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
          sources: []
        };
      }

      if (path === `/v1/er/person/${PERSON_ID}/matches`) {
        return [];
      }

      if (path === `/v1/graph/person/${PERSON_ID}/relationships`) {
        return {
          entity_type: "person",
          entity_id: PERSON_ID,
          neighbors: [],
          total_count: 0
        };
      }

      if (path === `/v1/candidates?person_id=${PERSON_ID}&limit=10&offset=0`) {
        return {
          items: [],
          has_next: false,
          offset: 0,
          limit: 10
        };
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as EntityDetailBundle;
    const matches = await data.matches;
    const relationships = await data.relationships;

    expect(matches).toEqual([]);
    expect(relationships.neighbors).toEqual([]);
    expect(requestJson).toHaveBeenCalledTimes(4);
  });

  it("passes filing neighbors through as successful data for presentation", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === `/v1/person/${PERSON_ID}`) {
        return {
          id: PERSON_ID,
          canonical_name: "Jane Doe",
          name_variants: [],
          first_name: "Jane",
          middle_name: null,
          last_name: "Doe",
          suffix: null,
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
          sources: []
        };
      }

      if (path === `/v1/er/person/${PERSON_ID}/matches`) {
        return [];
      }

      if (path === `/v1/graph/person/${PERSON_ID}/relationships`) {
        return {
          entity_type: "person",
          entity_id: PERSON_ID,
          neighbors: [
            {
              entity_type: "filing",
              entity_id: "33333333-3333-4333-8333-333333333333",
              name: "Q1 Filing",
              relationship_type: "FILED",
              direction: "inbound"
            }
          ],
          total_count: 1
        };
      }

      if (path === `/v1/candidates?person_id=${PERSON_ID}&limit=10&offset=0`) {
        return {
          items: [],
          has_next: false,
          offset: 0,
          limit: 10
        };
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as EntityDetailBundle;
    const relationships = await data.relationships;

    expect(relationships.neighbors).toHaveLength(1);
    expect(relationships.neighbors[0].entity_type).toBe("filing");
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
