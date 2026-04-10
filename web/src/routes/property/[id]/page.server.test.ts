import { ApiResponseError } from "$lib/server/api/client";
import type { ParcelDetailResponse } from "$lib/property-detail/contract";
import { describe, expect, it, vi } from "vitest";
import { load } from "./+page.server";

const PARCEL_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

function createLoadEvent(requestJson: ReturnType<typeof vi.fn>, id = PARCEL_ID) {
  return {
    params: { id },
    locals: {
      api: { requestJson }
    }
  } as unknown as Parameters<typeof load>[0];
}

describe("/property/[id] +page.server load", () => {
  it("returns parcel detail from /v1/parcels/{id} with no graph/ER/slug side lookups", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === `/v1/parcels/${PARCEL_ID}`) {
        return {
          id: PARCEL_ID,
          reid: "200000001",
          pin: "0999999999",
          site_address: "123 MAIN ST",
          property_description: "Single family home",
          city: "Durham",
          zoning_class: "R-20",
          land_class: "Residential",
          acreage: "1.2500",
          neighborhood: "Northside",
          fire_district: "Durham",
          is_pending: false,
          deed_date: "2024-01-15",
          deed_book: "1234",
          deed_page: "567",
          jurisdiction_id: null,
          sources: [],
          assessments: [],
          ownership: []
        } satisfies ParcelDetailResponse;
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as ParcelDetailResponse;

    expect(data.id).toBe(PARCEL_ID);
    const calledPaths = requestJson.mock.calls.map(([path]) => path);
    expect(calledPaths).toEqual([`/v1/parcels/${PARCEL_ID}`]);
    expect(calledPaths.every((path) => !String(path).startsWith("/v1/graph/"))).toBe(true);
    expect(calledPaths.every((path) => !String(path).startsWith("/v1/er/"))).toBe(true);
    expect(calledPaths.every((path) => !String(path).includes("slug"))).toBe(true);
    expect(calledPaths.every((path) => !String(path).includes("jurisdiction"))).toBe(true);
  });

  it("preserves backend-owned 404 Parcel not found semantics", async () => {
    const requestJson = vi.fn(async (path: string) => {
      expect(path).toBe(`/v1/parcels/${PARCEL_ID}`);
      throw new ApiResponseError(404, { detail: "Parcel not found" });
    });

    await expect(load(createLoadEvent(requestJson))).rejects.toMatchObject({
      status: 404,
      body: { detail: "Parcel not found" }
    });

    expect(requestJson).toHaveBeenCalledTimes(1);
  });

  it("preserves backend malformed UUID 422 semantics", async () => {
    const malformedId = "not-a-uuid";
    const requestJson = vi.fn(async (path: string) => {
      expect(path).toBe(`/v1/parcels/${malformedId}`);
      throw new ApiResponseError(422, { detail: [{ loc: ["path", "parcel_id"], msg: "Input should be a valid UUID" }] });
    });

    await expect(load(createLoadEvent(requestJson, malformedId))).rejects.toMatchObject({
      status: 422,
      body: { detail: [{ loc: ["path", "parcel_id"], msg: "Input should be a valid UUID" }] }
    });

    expect(requestJson).toHaveBeenCalledTimes(1);
  });
});
