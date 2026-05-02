import { ApiResponseError } from "$lib/server/api/client";
import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "./client";
import {
  createGeometryByLevelRecord,
  fetchCivicGeometry,
  fetchOptionalCivicGeometry,
  toCivicGeometryLevel
} from "./civic-geometry";

describe("fetchCivicGeometry", () => {
  it("makes one request to /v1/civics/geometry?level=<level>&state=<STATE>", async () => {
    const requestJson = vi.fn(async (path: string) => {
      expect(path).toBe("/v1/civics/geometry?level=county&state=NC");

      return {
        type: "FeatureCollection",
        features: []
      };
    });

    await fetchCivicGeometry(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { level: "county", state: "nc" }
    );

    expect(requestJson).toHaveBeenCalledTimes(1);
    expect(requestJson).toHaveBeenCalledWith("/v1/civics/geometry?level=county&state=NC");
  });

  it("preserves backend validation errors", async () => {
    const requestJson = vi
      .fn()
      .mockRejectedValue(
        new ApiResponseError(422, { detail: [{ loc: ["query", "level"], msg: "Invalid level" }] })
      );

    await expect(
      fetchCivicGeometry(
        { requestJson: requestJson as ApiClient["requestJson"] },
        { level: "county", state: "NC" }
      )
    ).rejects.toMatchObject({
      status: 422,
      body: { detail: [{ loc: ["query", "level"], msg: "Invalid level" }] }
    });
    expect(requestJson).toHaveBeenCalledTimes(1);
  });

  it("preserves backend 404 responses for deterministic optional handling upstream", async () => {
    const requestJson = vi
      .fn()
      .mockRejectedValue(new ApiResponseError(404, { detail: "Geometry not found for state NC" }));

    await expect(
      fetchCivicGeometry(
        { requestJson: requestJson as ApiClient["requestJson"] },
        { level: "county", state: "NC" }
      )
    ).rejects.toMatchObject({
      status: 404,
      body: { detail: "Geometry not found for state NC" }
    });
    expect(requestJson).toHaveBeenCalledTimes(1);
  });
});

describe("fetchOptionalCivicGeometry", () => {
  it("returns an explicit empty feature collection for backend-owned 404 responses", async () => {
    const requestJson = vi
      .fn()
      .mockRejectedValue(new ApiResponseError(404, { detail: "Geometry not found for state NC" }));

    await expect(
      fetchOptionalCivicGeometry(
        { requestJson: requestJson as ApiClient["requestJson"] },
        { level: "county", state: "NC" }
      )
    ).resolves.toEqual({
      type: "FeatureCollection",
      features: []
    });
    expect(requestJson).toHaveBeenCalledTimes(1);
  });

  it("rethrows non-404 backend failures so callers can preserve error semantics", async () => {
    const requestJson = vi
      .fn()
      .mockRejectedValue(
        new ApiResponseError(422, { detail: [{ loc: ["query", "state"], msg: "Invalid state" }] })
      );

    await expect(
      fetchOptionalCivicGeometry(
        { requestJson: requestJson as ApiClient["requestJson"] },
        { level: "county", state: "NC" }
      )
    ).rejects.toMatchObject({
      status: 422,
      body: { detail: [{ loc: ["query", "state"], msg: "Invalid state" }] }
    });
  });
});

describe("shared civic geometry helper exports", () => {
  it("maps backend division types to supported civic geometry levels", () => {
    expect(toCivicGeometryLevel("statewide")).toBe("state");
    expect(toCivicGeometryLevel("county")).toBe("county");
    expect(toCivicGeometryLevel("congressional_district")).toBe("congressional_district");
    expect(toCivicGeometryLevel("municipal_ward")).toBeNull();
    expect(toCivicGeometryLevel(null)).toBeNull();
    expect(toCivicGeometryLevel(undefined)).toBeNull();
  });

  it("creates deterministic empty geometry-by-level fallback records", () => {
    expect(createGeometryByLevelRecord()).toEqual({
      state: { type: "FeatureCollection", features: [] },
      county: { type: "FeatureCollection", features: [] },
      congressional_district: { type: "FeatureCollection", features: [] }
    });
  });
});
