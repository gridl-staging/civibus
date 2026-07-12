import { ApiResponseError } from "$lib/server/api/client";
import type { EntityDetailPageBundle } from "$lib/server/api/entity-detail";
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

describe("/org/[id] +page.server load", () => {
  it("loads only canonical organization detail for the public page contract", async () => {
    const organizationDetail = {
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
    const requestJson = vi.fn(async (path: string) => {
      if (path === `/v1/org/${ORG_ID}`) {
        return organizationDetail;
      }
      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as EntityDetailPageBundle;

    expect(data).toEqual({
      entityType: "org",
      detail: organizationDetail
    });
    expect("matches" in data).toBe(false);
    expect("relationships" in data).toBe(false);
    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([`/v1/org/${ORG_ID}`]);
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
