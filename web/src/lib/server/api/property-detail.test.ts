import { ApiResponseError } from "$lib/server/api/client";
import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "./client";
import { fetchParcelDetail } from "./property-detail";

const PARCEL_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

describe("fetchParcelDetail", () => {
  it("makes one request to /v1/parcels/{id} and no ER/graph/transactions side calls", async () => {
    const requestJson = vi.fn(async (path: string) => {
      expect(path).toBe(`/v1/parcels/${PARCEL_ID}`);

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
      };
    });

    await fetchParcelDetail(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { id: PARCEL_ID }
    );

    expect(requestJson).toHaveBeenCalledTimes(1);
    expect(requestJson).toHaveBeenCalledWith(`/v1/parcels/${PARCEL_ID}`);
    const calledPaths = requestJson.mock.calls.map((call) => String(call[0]));
    expect(calledPaths.every((path) => !path.startsWith("/v1/er/"))).toBe(true);
    expect(calledPaths.every((path) => !path.startsWith("/v1/graph/"))).toBe(true);
    expect(calledPaths.every((path) => !path.startsWith("/v1/transactions"))).toBe(true);
  });

  it("preserves backend malformed UUID 422 semantics", async () => {
    const requestJson = vi
      .fn()
      .mockRejectedValue(
        new ApiResponseError(422, { detail: [{ loc: ["path", "parcel_id"], msg: "Input should be a valid UUID" }] })
      );

    await expect(
      fetchParcelDetail(
        { requestJson: requestJson as ApiClient["requestJson"] },
        { id: "not-a-uuid" }
      )
    ).rejects.toMatchObject({
      status: 422,
      body: { detail: [{ loc: ["path", "parcel_id"], msg: "Input should be a valid UUID" }] }
    });
  });
});
