import { ApiResponseError } from "$lib/server/api/client";
import type { OfficeholdingDetailResponse } from "$lib/civic-detail/contract";
import { describe, expect, it, vi } from "vitest";
import { load } from "./+page.server";

const OFFICEHOLDING_ID = "44444444-4444-4444-8444-444444444444";
const OFFICE_ID = "33333333-3333-4333-8333-333333333333";
const PERSON_ID = "11111111-1111-4111-8111-111111111111";
const ELECTORAL_DIVISION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

function createLoadEvent(requestJson: ReturnType<typeof vi.fn>, id = OFFICEHOLDING_ID) {
  return {
    params: { id },
    locals: {
      api: { requestJson }
    }
  } as unknown as Parameters<typeof load>[0];
}

describe("/officeholding/[id] +page.server load", () => {
  it("returns officeholding detail from /v1/officeholdings/{id} with no graph/ER/slug side lookups", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === `/v1/officeholdings/${OFFICEHOLDING_ID}`) {
        return {
          id: OFFICEHOLDING_ID,
          person_id: PERSON_ID,
          person_name: "Jane Officeholder",
          office_id: OFFICE_ID,
          electoral_division_id: ELECTORAL_DIVISION_ID,
          holder_status: "elected",
          valid_period_lower: "2025-01-01",
          valid_period_upper: null,
          date_precision: "day",
          sources: []
        } satisfies OfficeholdingDetailResponse;
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as OfficeholdingDetailResponse;

    expect(data.id).toBe(OFFICEHOLDING_ID);
    const calledPaths = requestJson.mock.calls.map(([path]) => String(path));
    expect(calledPaths).toEqual([`/v1/officeholdings/${OFFICEHOLDING_ID}`]);
    expect(calledPaths.every((path) => !path.startsWith("/v1/graph/"))).toBe(true);
    expect(calledPaths.every((path) => !path.startsWith("/v1/er/"))).toBe(true);
    expect(calledPaths.every((path) => !path.includes("slug"))).toBe(true);
  });

  it("preserves backend-owned 404 Officeholding not found semantics", async () => {
    const requestJson = vi.fn(async (path: string) => {
      expect(path).toBe(`/v1/officeholdings/${OFFICEHOLDING_ID}`);
      throw new ApiResponseError(404, { detail: "Officeholding not found" });
    });

    await expect(load(createLoadEvent(requestJson))).rejects.toMatchObject({
      status: 404,
      body: { detail: "Officeholding not found" }
    });

    expect(requestJson).toHaveBeenCalledTimes(1);
  });

  it("preserves backend malformed UUID 422 semantics", async () => {
    const malformedId = "not-a-uuid";
    const requestJson = vi.fn(async (path: string) => {
      expect(path).toBe(`/v1/officeholdings/${malformedId}`);
      throw new ApiResponseError(422, {
        detail: [{ loc: ["path", "officeholding_id"], msg: "Input should be a valid UUID" }]
      });
    });

    await expect(load(createLoadEvent(requestJson, malformedId))).rejects.toMatchObject({
      status: 422,
      body: { detail: [{ loc: ["path", "officeholding_id"], msg: "Input should be a valid UUID" }] }
    });

    expect(requestJson).toHaveBeenCalledTimes(1);
  });
});
