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
          identifiers: {},
          primary_address_id: null,
          er_cluster_id: null,
          er_confidence: null,
          sources: []
        };
      }

      if (path === `/v1/er/person/${PERSON_ID}/matches`) {
        return deferredMatches.promise;
      }

      if (path === `/v1/graph/person/${PERSON_ID}/relationships`) {
        return deferredRelationships.promise;
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as EntityDetailBundle;

    expect(data.matches).toBeInstanceOf(Promise);
    expect(data.relationships).toBeInstanceOf(Promise);
    expect(requestJson).toHaveBeenCalledTimes(3);

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

      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as EntityDetailBundle;
    const matches = await data.matches;
    const relationships = await data.relationships;

    expect(matches).toEqual([]);
    expect(relationships.neighbors).toEqual([]);
    expect(requestJson).toHaveBeenCalledTimes(3);
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
