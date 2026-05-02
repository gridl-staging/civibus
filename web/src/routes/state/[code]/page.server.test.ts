import type { CivicGeometryLevel, MapLayerVisibility, MapPageLevel } from "$lib/config/app";
import type { CivicGeometryFeatureCollection } from "$lib/server/api/civic-geometry";
import { ApiResponseError } from "$lib/server/api/client";
import type {
  StateDetailResponse,
  StateSummaryItem
} from "$lib/server/api/state-pages-contract";
import { describe, expect, it, vi } from "vitest";
import { load } from "./+page.server";

type StatePageData = {
  stateCode: string;
  pageLevel: MapPageLevel;
  geometryByLevel: Record<CivicGeometryLevel, CivicGeometryFeatureCollection>;
  layerVisibilityDefaults: MapLayerVisibility;
  stateDetail: StateDetailResponse;
  geometry: { type: "FeatureCollection"; features: unknown[] };
  stateSummaries: StateSummaryItem[];
};

function createLoadEvent(requestJson: ReturnType<typeof vi.fn>, code = "NC") {
  return {
    params: { code },
    locals: {
      api: { requestJson }
    }
  } as unknown as Parameters<typeof load>[0];
}

describe("/state/[code] +page.server load", () => {
  it("returns combined state detail, coverage map, and drilldown geometry from backend owners", async () => {
    const detail: StateDetailResponse = {
      state_code: "NC",
      total_raised: "390.00",
      total_spent: "130.00",
      net: "260.00",
      committee_count: 2,
      transaction_count: 6,
      federal_candidate_count: 2,
      ie_support_total: "20.00",
      ie_oppose_total: "80.00",
      ie_support_count: 1,
      ie_oppose_count: 1,
      coverage_tier: "launch-support candidate",
      support_status: "supported",
      supported: true,
      warning_text: null,
      data_through: "2026-03-26T12:00:00Z",
      sources: [],
      top_candidates: [
        {
          candidate_id: "11111111-1111-4111-8111-111111111111",
          candidate_name: "Pat Candidate",
          total_raised: "250.00"
        }
      ],
      top_committees: [
        {
          committee_id: "22222222-2222-4222-8222-222222222222",
          committee_name: "Citizens for Civibus",
          total_raised: "125.00"
        }
      ],
      top_ie_spenders: [
        {
          committee_id: "33333333-3333-4333-8333-333333333333",
          committee_name: "Super PAC Alpha",
          total_amount: "15000.00"
        }
      ]
    };

    const geometry = { type: "FeatureCollection", features: [] as unknown[] };
    const stateSummaries: StateSummaryItem[] = [detail];

    const requestJson = vi.fn(async (path: string) => {
      if (path === "/v1/campaign-finance/states/NC") return detail;
      if (path === "/v1/geometry?level=country") return geometry;
      if (path === "/v1/campaign-finance/states/summary") return stateSummaries;
      if (path === "/v1/civics/geometry?level=state&state=NC") {
        return {
          type: "FeatureCollection",
          features: [
            {
              type: "Feature",
              geometry: { type: "Polygon", coordinates: [] },
              properties: {
                id: "state-id",
                name: "North Carolina",
                division_type: "statewide",
                state: "NC",
                district_number: null,
                boundary_year: 2024
              }
            }
          ]
        };
      }
      if (path === "/v1/civics/geometry?level=county&state=NC") {
        return {
          type: "FeatureCollection",
          features: [
            {
              type: "Feature",
              geometry: { type: "Polygon", coordinates: [] },
              properties: {
                id: "county-id",
                name: "nc_county_wake",
                division_type: "county",
                state: "NC",
                district_number: null,
                boundary_year: 2024
              }
            }
          ]
        };
      }
      if (path === "/v1/civics/geometry?level=congressional_district&state=NC") {
        return {
          type: "FeatureCollection",
          features: [
            {
              type: "Feature",
              geometry: { type: "Polygon", coordinates: [] },
              properties: {
                id: "district-id",
                name: "nc_cd_01",
                division_type: "congressional_district",
                state: "NC",
                district_number: "01",
                boundary_year: 2024
              }
            }
          ]
        };
      }
      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as StatePageData;

    expect(data.stateCode).toBe("NC");
    expect(data.pageLevel).toBe("state");
    expect(data.layerVisibilityDefaults).toEqual({
      nc_statewide_boundary: true,
      nc_county_boundaries: true,
      nc_congressional_districts: false
    });
    expect(data.stateDetail).toEqual(detail);
    expect(data.geometry).toEqual(geometry);
    expect(data.stateSummaries).toEqual(stateSummaries);
    expect(data.geometryByLevel.state.features[0]?.properties.name).toBe("North Carolina");
    expect(data.geometryByLevel.county.features[0]?.properties.name).toBe("nc_county_wake");
    expect(data.geometryByLevel.congressional_district.features[0]?.properties.name).toBe("nc_cd_01");
    expect(data.stateDetail.top_candidates[0]?.candidate_name).toBe("Pat Candidate");
    expect(data.stateDetail.top_committees[0]?.committee_name).toBe("Citizens for Civibus");
    expect(data.stateDetail.top_ie_spenders[0]?.committee_name).toBe("Super PAC Alpha");

    const calledPaths = requestJson.mock.calls.map(([path]) => String(path));
    expect(calledPaths).toEqual([
      "/v1/campaign-finance/states/NC",
      "/v1/geometry?level=country",
      "/v1/campaign-finance/states/summary",
      "/v1/civics/geometry?level=state&state=NC",
      "/v1/civics/geometry?level=county&state=NC",
      "/v1/civics/geometry?level=congressional_district&state=NC"
    ]);
    expect(calledPaths.every((path) => !path.startsWith("/v1/graph/"))).toBe(true);
    expect(calledPaths.every((path) => !path.startsWith("/v1/er/"))).toBe(true);
    expect(calledPaths.every((path) => !path.includes("slug"))).toBe(true);
  });

  it("preserves backend-owned 404 State not found semantics", async () => {
    const requestJson = vi.fn(async (path: string) => {
      expect(path).toBe("/v1/campaign-finance/states/ZZ");
      throw new ApiResponseError(404, { detail: "State not found" });
    });

    await expect(load(createLoadEvent(requestJson, "ZZ"))).rejects.toMatchObject({
      status: 404,
      body: { detail: "State not found" }
    });

    expect(requestJson).toHaveBeenCalledTimes(1);
  });

  it("preserves backend malformed state code 422 semantics", async () => {
    const requestJson = vi.fn(async (path: string) => {
      expect(path).toBe("/v1/campaign-finance/states/N@");
      throw new ApiResponseError(422, {
        detail: [{ loc: ["path", "state_code"], msg: "String should match pattern '^[A-Z]{2}$'" }]
      });
    });

    await expect(load(createLoadEvent(requestJson, "N@"))).rejects.toMatchObject({
      status: 422,
      body: {
        detail: [{ loc: ["path", "state_code"], msg: "String should match pattern '^[A-Z]{2}$'" }]
      }
    });

    expect(requestJson).toHaveBeenCalledTimes(1);
  });

  it("keeps state detail pages working when drilldown geometry is not available for that state", async () => {
    const detail: StateDetailResponse = {
      state_code: "AR",
      total_raised: "0.00",
      total_spent: "0.00",
      net: "0.00",
      committee_count: 0,
      transaction_count: 0,
      federal_candidate_count: 0,
      ie_support_total: null,
      ie_oppose_total: null,
      ie_support_count: null,
      ie_oppose_count: null,
      coverage_tier: "deferred/blocked",
      support_status: "unsupported",
      supported: false,
      warning_text: null,
      data_through: null,
      sources: [],
      top_candidates: [],
      top_committees: [],
      top_ie_spenders: []
    };

    const requestJson = vi.fn(async (path: string) => {
      if (path === "/v1/campaign-finance/states/AR") return detail;
      if (path === "/v1/geometry?level=country") return { type: "FeatureCollection", features: [] };
      if (path === "/v1/campaign-finance/states/summary") return [detail];
      if (path.startsWith("/v1/civics/geometry?")) {
        throw new ApiResponseError(404, { detail: "Civic geometry not found" });
      }
      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson, "AR"))) as StatePageData;

    expect(data.stateDetail).toEqual(detail);
    expect(data.geometryByLevel.state.features).toEqual([]);
    expect(data.geometryByLevel.county.features).toEqual([]);
    expect(data.geometryByLevel.congressional_district.features).toEqual([]);
  });
});
