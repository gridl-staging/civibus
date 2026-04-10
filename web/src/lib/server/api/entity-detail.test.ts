import { ApiResponseError } from "$lib/server/api/client";
import { describe, expect, it, vi } from "vitest";
import { fetchEntityDetailBundle } from "./entity-detail";
import type { ApiClient } from "./client";

const PERSON_ID = "11111111-1111-4111-8111-111111111111";
const ORG_ID = "22222222-2222-4222-8222-222222222222";

const PERSON_DETAIL = {
  id: PERSON_ID,
  canonical_name: "Jane Doe",
  name_variants: ["J. Doe"],
  first_name: "Jane",
  middle_name: null,
  last_name: "Doe",
  suffix: null,
  date_of_birth: null,
  year_of_birth: 1980,
  identifiers: { fec_candidate_id: "H0NC01001" },
  primary_address_id: null,
  er_cluster_id: null,
  er_confidence: null,
  sources: [
    {
      domain: "campaign_finance",
      jurisdiction: "federal/fec",
      data_source_name: "FEC",
      data_source_url: "https://www.fec.gov",
      source_record_key: "person-1",
      record_url: "https://example.org/person-1",
      pull_date: "2026-03-19T00:00:00Z"
    }
  ]
};

const ORG_DETAIL = {
  id: ORG_ID,
  canonical_name: "Civibus Action Org",
  name_variants: [],
  org_type: "pac",
  identifiers: { fec_committee_id: "C12345678" },
  registered_state: "NC",
  formation_date: "2014-05-01",
  dissolution_date: null,
  primary_address_id: null,
  er_cluster_id: null,
  er_confidence: 0.91,
  sources: [
    {
      domain: "campaign_finance",
      jurisdiction: "federal/fec",
      data_source_name: "FEC",
      data_source_url: "https://www.fec.gov",
      source_record_key: "org-1",
      record_url: "https://example.org/org-1",
      pull_date: "2026-03-19T00:00:00Z"
    }
  ]
};

describe("fetchEntityDetailBundle", () => {
  it("starts detail, ER, and graph requests concurrently before awaiting detail", async () => {
    let resolveDetail: (value: typeof PERSON_DETAIL) => void = () => {};
    const detailPromise = new Promise<typeof PERSON_DETAIL>((resolve) => {
      resolveDetail = resolve;
    });
    const requestJson = vi.fn((path: string) => {
      if (path === `/v1/person/${PERSON_ID}`) {
        return detailPromise;
      }

      if (path === `/v1/er/person/${PERSON_ID}/matches`) {
        return Promise.resolve([]);
      }

      if (path === `/v1/graph/person/${PERSON_ID}/relationships`) {
        return Promise.resolve({
          entity_type: "person",
          entity_id: PERSON_ID,
          neighbors: [],
          total_count: 0
        });
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const bundlePromise = fetchEntityDetailBundle(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { entityType: "person", id: PERSON_ID }
    );

    expect(requestJson).toHaveBeenCalledTimes(3);

    resolveDetail(PERSON_DETAIL);
    await bundlePromise;
  });

  it("composes person detail + ER + graph from shared Stage 4 paths", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === `/v1/person/${PERSON_ID}`) {
        return PERSON_DETAIL;
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

    const bundle = await fetchEntityDetailBundle(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { entityType: "person", id: PERSON_ID }
    );

    expect(bundle.detail.sources).toBe(PERSON_DETAIL.sources);
    expect(bundle.matches).toBeInstanceOf(Promise);
    expect(bundle.relationships).toBeInstanceOf(Promise);
    await expect(bundle.matches).resolves.toEqual([]);
    await expect(bundle.relationships).resolves.toMatchObject({
      neighbors: []
    });
    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      `/v1/person/${PERSON_ID}`,
      `/v1/er/person/${PERSON_ID}/matches`,
      `/v1/graph/person/${PERSON_ID}/relationships`
    ]);
  });

  it("composes org detail + organization ER + org graph path mismatch", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === `/v1/org/${ORG_ID}`) {
        return ORG_DETAIL;
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

    const bundle = await fetchEntityDetailBundle(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { entityType: "org", id: ORG_ID }
    );

    await expect(bundle.matches).resolves.toEqual([]);
    await expect(bundle.relationships).resolves.toMatchObject({
      neighbors: []
    });
    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      `/v1/org/${ORG_ID}`,
      `/v1/er/organization/${ORG_ID}/matches`,
      `/v1/graph/org/${ORG_ID}/relationships`
    ]);
  });

  it("preserves backend error semantics (e.g. malformed UUID 422)", async () => {
    const requestJson = vi
      .fn()
      .mockRejectedValue(
        new ApiResponseError(422, { detail: [{ loc: ["path", "person_id"], msg: "Input should be a valid UUID" }] })
      );

    await expect(
      fetchEntityDetailBundle(
        { requestJson: requestJson as ApiClient["requestJson"] },
        { entityType: "person", id: "not-a-uuid" }
      )
    ).rejects.toMatchObject({ status: 422 });
  });

  it("does not emit unhandled rejections when ER fails before detail resolves", async () => {
    const earlyMatchFailure = new Error("ER matches request failed");
    let resolveDetail: (value: typeof PERSON_DETAIL) => void = () => {};
    const detailPromise = new Promise<typeof PERSON_DETAIL>((resolve) => {
      resolveDetail = resolve;
    });
    const requestJson = vi.fn((path: string) => {
      if (path === `/v1/person/${PERSON_ID}`) {
        return detailPromise;
      }

      if (path === `/v1/er/person/${PERSON_ID}/matches`) {
        return Promise.reject(earlyMatchFailure);
      }

      if (path === `/v1/graph/person/${PERSON_ID}/relationships`) {
        return Promise.resolve({
          entity_type: "person",
          entity_id: PERSON_ID,
          neighbors: [],
          total_count: 0
        });
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const unhandled: unknown[] = [];
    const handleUnhandledRejection = (reason: unknown) => {
      unhandled.push(reason);
    };
    process.on("unhandledRejection", handleUnhandledRejection);

    try {
      const bundlePromise = fetchEntityDetailBundle(
        { requestJson: requestJson as ApiClient["requestJson"] },
        { entityType: "person", id: PERSON_ID }
      );

      await Promise.resolve();
      await new Promise<void>((resolve) => {
        setTimeout(resolve, 0);
      });

      expect(unhandled).toEqual([]);

      resolveDetail(PERSON_DETAIL);
      const bundle = await bundlePromise;
      await expect(bundle.matches).rejects.toThrow("ER matches request failed");
      await expect(bundle.relationships).resolves.toMatchObject({ total_count: 0 });
      expect(unhandled).toEqual([]);
    } finally {
      process.off("unhandledRejection", handleUnhandledRejection);
    }
  });
});
