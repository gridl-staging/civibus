import { ApiResponseError } from "$lib/server/api/client";
import type { OfficeDetailResponse } from "$lib/civic-detail/contract";
import { describe, expect, it, vi } from "vitest";
import { load } from "./+page.server";

const OFFICE_ID = "33333333-3333-4333-8333-333333333333";

function createLoadEvent(requestJson: ReturnType<typeof vi.fn>, id = OFFICE_ID) {
  return {
    params: { id },
    locals: {
      api: { requestJson }
    }
  } as unknown as Parameters<typeof load>[0];
}

describe("/office/[id] +page.server load", () => {
  it("returns office detail from /v1/offices/{id} with no graph/ER/slug side lookups", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === `/v1/offices/${OFFICE_ID}`) {
        return {
          id: OFFICE_ID,
          name: "North Carolina Governor",
          office_level: "state",
          title: "Governor",
          jurisdiction_id: null,
          state: "NC",
          is_elected: true,
          number_of_seats: 1,
          current_officeholders: [],
          incomplete_data_states: ["no_officeholder"],
          sources: []
        } satisfies OfficeDetailResponse;
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as OfficeDetailResponse;

    expect(data.id).toBe(OFFICE_ID);
    const calledPaths = requestJson.mock.calls.map(([path]) => String(path));
    expect(calledPaths).toEqual([`/v1/offices/${OFFICE_ID}`]);
    expect(calledPaths.every((path) => !path.startsWith("/v1/graph/"))).toBe(true);
    expect(calledPaths.every((path) => !path.startsWith("/v1/er/"))).toBe(true);
    expect(calledPaths.every((path) => !path.includes("slug"))).toBe(true);
  });

  it("preserves backend-owned 404 Office not found semantics", async () => {
    const requestJson = vi.fn(async (path: string) => {
      expect(path).toBe(`/v1/offices/${OFFICE_ID}`);
      throw new ApiResponseError(404, { detail: "Office not found" });
    });

    await expect(load(createLoadEvent(requestJson))).rejects.toMatchObject({
      status: 404,
      body: { detail: "Office not found" }
    });

    expect(requestJson).toHaveBeenCalledTimes(1);
  });

  it("preserves backend malformed UUID 422 semantics", async () => {
    const malformedId = "not-a-uuid";
    const requestJson = vi.fn(async (path: string) => {
      expect(path).toBe(`/v1/offices/${malformedId}`);
      throw new ApiResponseError(422, { detail: [{ loc: ["path", "office_id"], msg: "Input should be a valid UUID" }] });
    });

    await expect(load(createLoadEvent(requestJson, malformedId))).rejects.toMatchObject({
      status: 422,
      body: { detail: [{ loc: ["path", "office_id"], msg: "Input should be a valid UUID" }] }
    });

    expect(requestJson).toHaveBeenCalledTimes(1);
  });
});
