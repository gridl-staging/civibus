import { describe, expect, it, vi } from "vitest";
import { ApiResponseError } from "$lib/server/api/client";
import { load } from "./+page.server";

function createLoadEvent(requestJson: ReturnType<typeof vi.fn>) {
  return {
    url: new URL("https://web.civibus.local/"),
    locals: {
      api: {
        requestJson
      }
    }
  } as unknown as Parameters<typeof load>[0];
}

describe("/ +page.server load", () => {
  it("returns geometry and stateSummaries from the shared backend helpers", async () => {
    const geometry = {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          geometry: { type: "Polygon", coordinates: [[[-100, 30], [-95, 30], [-95, 35], [-100, 35]]] },
          properties: {
            state: "CA",
            name: "California",
            division_type: "state",
            boundary_year: 2020
          }
        }
      ]
    };
    const stateSummaries = [
      {
        state_code: "CA",
        total_raised: "0",
        total_spent: "0",
        net: "0",
        committee_count: 0,
        transaction_count: 0,
        federal_candidate_count: 0,
        ie_support_total: null,
        ie_oppose_total: null,
        ie_support_count: null,
        ie_oppose_count: null,
        coverage_tier: null,
        support_status: "supported",
        supported: true,
        warning_text: null,
        data_through: null
      }
    ];

    const requestJson = vi.fn(async (path: string) => {
      if (path === "/v1/geometry?level=country") return geometry;
      if (path === "/v1/campaign-finance/states/summary") return stateSummaries;
      throw new Error(`unexpected path: ${path}`);
    });

    const data = await load(createLoadEvent(requestJson));

    expect(data).toEqual({ geometry, stateSummaries });
    expect(requestJson).toHaveBeenCalledWith("/v1/geometry?level=country");
    expect(requestJson).toHaveBeenCalledWith("/v1/campaign-finance/states/summary");
  });

  it("issues both backend requests in parallel", async () => {
    let resolveGeometry: (value: unknown) => void = () => {};
    let resolveSummaries: (value: unknown) => void = () => {};

    const geometryPromise = new Promise((resolve) => {
      resolveGeometry = resolve;
    });
    const summariesPromise = new Promise((resolve) => {
      resolveSummaries = resolve;
    });

    const requestJson = vi.fn((path: string) => {
      if (path === "/v1/geometry?level=country") return geometryPromise;
      if (path === "/v1/campaign-finance/states/summary") return summariesPromise;
      return Promise.reject(new Error(`unexpected path: ${path}`));
    });

    const loadPromise = load(createLoadEvent(requestJson));

    expect(requestJson).toHaveBeenCalledTimes(2);

    resolveGeometry({ type: "FeatureCollection", features: [] });
    resolveSummaries([]);

    await loadPromise;
  });

  it("rethrows backend ApiResponseError through the shared route error mapper", async () => {
    const requestJson = vi
      .fn()
      .mockRejectedValue(new ApiResponseError(503, "Backend unavailable"));

    await expect(load(createLoadEvent(requestJson))).rejects.toMatchObject({
      status: 503,
      body: { message: "Backend unavailable" }
    });
  });

  it("preserves backend structured error payloads on failure", async () => {
    const requestJson = vi
      .fn()
      .mockRejectedValue(
        new ApiResponseError(500, { detail: [{ loc: ["server"], msg: "boom" }] })
      );

    await expect(load(createLoadEvent(requestJson))).rejects.toMatchObject({
      status: 500,
      body: { detail: [{ loc: ["server"], msg: "boom" }] }
    });
  });
});
