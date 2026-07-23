import type { CivicGeometryLevel, MapLayerVisibility, MapPageLevel } from "$lib/config/app";
import { ApiResponseError } from "$lib/server/api/client";
import type { CivicGeometryFeatureCollection } from "$lib/server/api/civic-geometry";
import { describe, expect, it, vi } from "vitest";
import { load } from "./+page.server";

type StatePageData = {
  stateCode: string;
  pageLevel: MapPageLevel;
  geometryByLevel: Record<CivicGeometryLevel, CivicGeometryFeatureCollection>;
  layerVisibilityDefaults: MapLayerVisibility;
  geometry: { type: "FeatureCollection"; features: unknown[] };
  retirement: {
    heading: string;
    message: string;
  };
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
  it("rejects non-state codes before requesting geometry", async () => {
    const requestJson = vi.fn();

    await expect(load(createLoadEvent(requestJson, "ZZ"))).rejects.toMatchObject({
      status: 404
    });
    expect(requestJson).not.toHaveBeenCalled();
  });

  it("rejects malformed state codes before requesting geometry", async () => {
    const requestJson = vi.fn();

    await expect(load(createLoadEvent(requestJson, "N@"))).rejects.toMatchObject({
      status: 404
    });
    expect(requestJson).not.toHaveBeenCalled();
  });

  it("renders the v1 retired state page without calling retired campaign-finance endpoints", async () => {
    const geometry = {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          geometry: { type: "Polygon", coordinates: [] },
          properties: {
            state: "NC",
            name: "North Carolina",
            division_type: "state",
            boundary_year: 2024
          }
        }
      ]
    };

    const requestJson = vi.fn(async (path: string) => {
      if (path === "/v1/geometry?level=country") return geometry;
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
    expect(data.geometry).toEqual(geometry);
    expect(data.geometryByLevel.state.features[0]?.properties.name).toBe("North Carolina");
    expect(data.geometryByLevel.county.features[0]?.properties.name).toBe("nc_county_wake");
    expect(data.geometryByLevel.congressional_district.features[0]?.properties.name).toBe("nc_cd_01");
    expect(data.retirement.heading).toBe("State campaign finance is outside federal-first v1");
    expect(data.retirement.message).toContain("federal officials, candidates, committees, and independent expenditures");

    const calledPaths = requestJson.mock.calls.map(([path]) => String(path));
    expect(calledPaths).toEqual([
      "/v1/geometry?level=country",
      "/v1/civics/geometry?level=state&state=NC",
      "/v1/civics/geometry?level=county&state=NC",
      "/v1/civics/geometry?level=congressional_district&state=NC"
    ]);
    expect(calledPaths.every((path) => !path.startsWith("/v1/campaign-finance/states/"))).toBe(true);
    expect(calledPaths.every((path) => !path.startsWith("/v1/graph/"))).toBe(true);
    expect(calledPaths.every((path) => !path.startsWith("/v1/er/"))).toBe(true);
  });

  it("keeps state detail pages working when drilldown geometry is not available for that state", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === "/v1/geometry?level=country") return { type: "FeatureCollection", features: [] };
      if (path.startsWith("/v1/civics/geometry?")) {
        throw new ApiResponseError(404, { detail: "Civic geometry not found" });
      }
      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson, "AR"))) as StatePageData;

    expect(data.stateCode).toBe("AR");
    expect(data.geometryByLevel.state.features).toEqual([]);
    expect(data.geometryByLevel.county.features).toEqual([]);
    expect(data.geometryByLevel.congressional_district.features).toEqual([]);
  });
});
