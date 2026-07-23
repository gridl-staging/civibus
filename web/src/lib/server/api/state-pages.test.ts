import { describe, expect, it, vi } from "vitest";
import { ApiResponseError } from "./client";
import {
  COUNTRY_GEOMETRY_PATH,
  STATE_COVERAGE_TIER_VALUES,
  STATE_SUPPORT_STATUS_VALUES
} from "./state-pages-contract";
import { fetchCountryGeometry } from "./state-pages";

describe("fetchCountryGeometry", () => {
  it("requests the shared country-geometry endpoint", async () => {
    const requestJson = vi
      .fn()
      .mockResolvedValue({ type: "FeatureCollection", features: [] });

    const result = await fetchCountryGeometry({ requestJson });

    expect(requestJson).toHaveBeenCalledWith(COUNTRY_GEOMETRY_PATH);
    expect(result).toEqual({ type: "FeatureCollection", features: [] });
  });

  it("propagates ApiResponseError unchanged", async () => {
    const cause = new ApiResponseError(500, { detail: "boom" });
    const requestJson = vi.fn().mockRejectedValue(cause);

    await expect(fetchCountryGeometry({ requestJson })).rejects.toBe(cause);
  });
});

describe("state-pages backend enum contract", () => {
  it("keeps support_status literals aligned with the backend response model", () => {
    expect(STATE_SUPPORT_STATUS_VALUES).toEqual([
      "supported",
      "warning",
      "unsupported"
    ]);
  });

  it("keeps coverage_tier literals aligned with the backend response model", () => {
    expect(STATE_COVERAGE_TIER_VALUES).toEqual([
      "launch-support candidate",
      "implemented but unproven",
      "freshness-limited",
      "deferred/blocked"
    ]);
  });
});
