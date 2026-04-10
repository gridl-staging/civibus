import { ApiResponseError } from "$lib/server/api/client";
import type { ContestDetailResponse } from "$lib/civic-detail/contract";
import { describe, expect, it, vi } from "vitest";
import { load } from "./+page.server";

const CONTEST_ID = "77777777-7777-4777-8777-777777777777";
const OFFICE_ID = "33333333-3333-4333-8333-333333333333";
const ELECTORAL_DIVISION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

function createLoadEvent(requestJson: ReturnType<typeof vi.fn>, id = CONTEST_ID) {
  return {
    params: { id },
    locals: {
      api: { requestJson }
    }
  } as unknown as Parameters<typeof load>[0];
}

describe("/contest/[id] +page.server load", () => {
  it("returns contest detail from /v1/contests/{id} with no graph/ER/slug side lookups", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === `/v1/contests/${CONTEST_ID}`) {
        return {
          id: CONTEST_ID,
          name: "Governor 2026 General Election",
          election_date: "2026-11-03",
          election_type: "general",
          office_id: OFFICE_ID,
          electoral_division_id: ELECTORAL_DIVISION_ID,
          number_of_seats: 1,
          filing_deadline: "2026-09-01",
          is_partisan: true,
          candidate_list_incomplete: false,
          candidacies: [],
          sources: []
        } satisfies ContestDetailResponse;
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as ContestDetailResponse;

    expect(data.id).toBe(CONTEST_ID);
    const calledPaths = requestJson.mock.calls.map(([path]) => String(path));
    expect(calledPaths).toEqual([`/v1/contests/${CONTEST_ID}`]);
    expect(calledPaths.every((path) => !path.startsWith("/v1/graph/"))).toBe(true);
    expect(calledPaths.every((path) => !path.startsWith("/v1/er/"))).toBe(true);
    expect(calledPaths.every((path) => !path.includes("slug"))).toBe(true);
  });

  it("preserves backend-owned 404 Contest not found semantics", async () => {
    const requestJson = vi.fn(async (path: string) => {
      expect(path).toBe(`/v1/contests/${CONTEST_ID}`);
      throw new ApiResponseError(404, { detail: "Contest not found" });
    });

    await expect(load(createLoadEvent(requestJson))).rejects.toMatchObject({
      status: 404,
      body: { detail: "Contest not found" }
    });

    expect(requestJson).toHaveBeenCalledTimes(1);
  });

  it("preserves backend malformed UUID 422 semantics", async () => {
    const malformedId = "not-a-uuid";
    const requestJson = vi.fn(async (path: string) => {
      expect(path).toBe(`/v1/contests/${malformedId}`);
      throw new ApiResponseError(422, {
        detail: [{ loc: ["path", "contest_id"], msg: "Input should be a valid UUID" }]
      });
    });

    await expect(load(createLoadEvent(requestJson, malformedId))).rejects.toMatchObject({
      status: 422,
      body: { detail: [{ loc: ["path", "contest_id"], msg: "Input should be a valid UUID" }] }
    });

    expect(requestJson).toHaveBeenCalledTimes(1);
  });
});
