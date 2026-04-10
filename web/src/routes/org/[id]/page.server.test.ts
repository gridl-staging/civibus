import { ApiResponseError } from "$lib/server/api/client";
import type { EntityDetailBundle } from "$lib/server/api/entity-detail";
import { describe, expect, it, vi } from "vitest";
import { load } from "./+page.server";

const ORG_ID = "22222222-2222-4222-8222-222222222222";

function createLoadEvent(requestJson: ReturnType<typeof vi.fn>) {
  return {
    params: { id: ORG_ID },
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

describe("/org/[id] +page.server load", () => {
  it("returns streaming matches/relationships promises so the detail page can render loading skeletons", async () => {
    const deferredMatches = createDeferred<any[]>();
    const deferredRelationships = createDeferred<any>();

    const requestJson = vi.fn(async (path: string) => {
      if (path === `/v1/org/${ORG_ID}`) {
        return {
          id: ORG_ID,
          canonical_name: "Civibus Action Org",
          name_variants: [],
          org_type: "pac",
          identifiers: {},
          registered_state: "NC",
          formation_date: null,
          dissolution_date: null,
          primary_address_id: null,
          er_cluster_id: null,
          er_confidence: null,
          sources: []
        };
      }

      if (path === `/v1/er/organization/${ORG_ID}/matches`) {
        return deferredMatches.promise;
      }

      if (path === `/v1/graph/org/${ORG_ID}/relationships`) {
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
      entity_type: "org",
      entity_id: ORG_ID,
      neighbors: [],
      total_count: 0
    });

    await expect(data.matches).resolves.toEqual([]);
    await expect(data.relationships).resolves.toMatchObject({ total_count: 0 });
  });

  it("uses /org detail + /organization ER + /org graph route mapping", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === `/v1/org/${ORG_ID}`) {
        return {
          id: ORG_ID,
          canonical_name: "Civibus Action Org",
          name_variants: [],
          org_type: "pac",
          identifiers: {},
          registered_state: "NC",
          formation_date: null,
          dissolution_date: null,
          primary_address_id: null,
          er_cluster_id: null,
          er_confidence: null,
          sources: []
        };
      }

      if (path === `/v1/er/organization/${ORG_ID}/matches`) {
        return [];
      }

      if (path === `/v1/graph/org/${ORG_ID}/relationships`) {
        return {
          entity_type: "org",
          entity_id: ORG_ID,
          neighbors: [],
          total_count: 0
        };
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as EntityDetailBundle;
    const matches = await data.matches;

    expect(data.detail.canonical_name).toBe("Civibus Action Org");
    expect(matches).toEqual([]);
    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      `/v1/org/${ORG_ID}`,
      `/v1/er/organization/${ORG_ID}/matches`,
      `/v1/graph/org/${ORG_ID}/relationships`
    ]);
  });

  it("keeps graph payloads with filing neighbors as successful page data", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === `/v1/org/${ORG_ID}`) {
        return {
          id: ORG_ID,
          canonical_name: "Civibus Action Org",
          name_variants: [],
          org_type: "pac",
          identifiers: {},
          registered_state: "NC",
          formation_date: null,
          dissolution_date: null,
          primary_address_id: null,
          er_cluster_id: null,
          er_confidence: null,
          sources: []
        };
      }

      if (path === `/v1/er/organization/${ORG_ID}/matches`) {
        return [];
      }

      if (path === `/v1/graph/org/${ORG_ID}/relationships`) {
        return {
          entity_type: "org",
          entity_id: ORG_ID,
          neighbors: [
            {
              entity_type: "filing",
              entity_id: "33333333-3333-4333-8333-333333333333",
              name: "Q1 Filing",
              relationship_type: "FILED",
              direction: "outbound"
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
    const requestJson = vi.fn().mockRejectedValue(new ApiResponseError(404, { detail: "Organization not found" }));

    await expect(load(createLoadEvent(requestJson))).rejects.toMatchObject({
      status: 404,
      body: { detail: "Organization not found" }
    });
  });

  it("preserves backend plain-text 404 semantics", async () => {
    const requestJson = vi.fn().mockRejectedValue(new ApiResponseError(404, "Organization not found"));

    await expect(load(createLoadEvent(requestJson))).rejects.toMatchObject({
      status: 404,
      body: { message: "Organization not found" }
    });
  });

  it("preserves backend malformed UUID 422 semantics", async () => {
    const requestJson = vi
      .fn()
      .mockRejectedValue(
        new ApiResponseError(422, {
          detail: [{ loc: ["path", "organization_id"], msg: "Input should be a valid UUID" }]
        })
      );

    await expect(load(createLoadEvent(requestJson))).rejects.toMatchObject({
      status: 422,
      body: { detail: [{ loc: ["path", "organization_id"], msg: "Input should be a valid UUID" }] }
    });
  });
});
