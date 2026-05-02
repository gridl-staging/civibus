import { ApiResponseError } from "$lib/server/api/client";
import type { OfficeDetailResponse } from "$lib/civic-detail/contract";
import { describe, expect, it, vi } from "vitest";
import { load } from "./+page.server";

const OFFICE_ID = "33333333-3333-4333-8333-333333333333";
const CONTEST_ID = "77777777-7777-4777-8777-777777777777";
const ELECTORAL_DIVISION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const GEOMETRY_PATH = "/v1/civics/geometry?level=county&state=NC";

function createLoadEvent(requestJson: ReturnType<typeof vi.fn>, id = OFFICE_ID) {
  return {
    params: { id },
    locals: {
      api: { requestJson }
    }
  } as unknown as Parameters<typeof load>[0];
}

describe("/office/[id] +page.server load", () => {
  it("returns office detail and deterministic geometry context with no graph/ER/slug side lookups", async () => {
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
          current_holder_card: null,
          officeholding_timeline: [],
          recent_contests: [
            {
              contest_id: CONTEST_ID,
              contest_name: "Governor 2026 General Election",
              election_date: "2026-11-03",
              election_type: "general",
              filing_deadline: "2026-09-01",
              electoral_division_id: ELECTORAL_DIVISION_ID,
              electoral_division_type: "county",
              electoral_division_state: "NC",
              is_partisan: true,
              candidate_list_incomplete: false
            }
          ],
          selected_electoral_division_id: ELECTORAL_DIVISION_ID,
          selected_electoral_division_type: "county",
          selected_electoral_division_state: "NC",
          incomplete_data_states: ["no_officeholder"],
          sources: []
        } satisfies OfficeDetailResponse;
      }
      if (path === GEOMETRY_PATH) {
        return {
          type: "FeatureCollection",
          features: []
        };
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as {
      office: OfficeDetailResponse;
      geometryByLevel: Record<string, { type: string; features: unknown[] }>;
    };

    expect(data.office.id).toBe(OFFICE_ID);
    expect(data.geometryByLevel.county.features).toEqual([]);
    const calledPaths = requestJson.mock.calls.map(([path]) => String(path));
    expect(calledPaths).toEqual([`/v1/offices/${OFFICE_ID}`, GEOMETRY_PATH]);
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

  it("falls back to empty geometry when civic geometry returns backend-owned 404", async () => {
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
          current_holder_card: null,
          officeholding_timeline: [],
          recent_contests: [],
          selected_electoral_division_id: ELECTORAL_DIVISION_ID,
          selected_electoral_division_type: "county",
          selected_electoral_division_state: "NC",
          incomplete_data_states: [],
          sources: []
        } satisfies OfficeDetailResponse;
      }
      if (path === GEOMETRY_PATH) {
        throw new ApiResponseError(404, { detail: "Geometry not found for state NC" });
      }
      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as {
      geometryByLevel: Record<string, { type: string; features: unknown[] }>;
    };

    expect(data.geometryByLevel.county.features).toEqual([]);
  });

  it("keeps explicit empty-geometry fallback when office map context is unsupported", async () => {
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
          current_holder_card: null,
          officeholding_timeline: [],
          recent_contests: [],
          selected_electoral_division_id: ELECTORAL_DIVISION_ID,
          selected_electoral_division_type: "municipal_ward",
          selected_electoral_division_state: "NC",
          incomplete_data_states: [],
          sources: []
        } satisfies OfficeDetailResponse;
      }
      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as {
      geometryByLevel: Record<string, { type: string; features: unknown[] }>;
    };

    expect(data.geometryByLevel.state.features).toEqual([]);
    expect(data.geometryByLevel.county.features).toEqual([]);
    expect(data.geometryByLevel.congressional_district.features).toEqual([]);
    const calledPaths = requestJson.mock.calls.map(([path]) => String(path));
    expect(calledPaths).toEqual([`/v1/offices/${OFFICE_ID}`]);
  });
});
