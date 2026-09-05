import type { CivicGeometryLevel, MapLayerVisibility, MapPageLevel } from "$lib/config/app";
import { ApiResponseError } from "$lib/server/api/client";
import type { CivicGeometryFeatureCollection } from "$lib/server/api/civic-geometry";
import { describe, expect, it, vi } from "vitest";
import { load } from "./+page.server";
import type { RegionalNavigationNode } from "$lib/server/api/state-pages-contract";
import {
  buildUnavailableStateNode,
  buildWashingtonNode,
  WAKE_NODE
} from "$lib/regional-navigation/test-fixtures";

type StatePageData = {
  stateCode: string;
  pageLevel: MapPageLevel;
  geometryByLevel: Record<CivicGeometryLevel, CivicGeometryFeatureCollection>;
  layerVisibilityDefaults: MapLayerVisibility;
  geometry: { type: "FeatureCollection"; features: unknown[] };
  navigationNode: RegionalNavigationNode;
  featureLinks: Record<string, { href: string; label: string }>;
};

function createLoadEvent(requestJson: ReturnType<typeof vi.fn>, code = "NC") {
  return {
    params: { code },
    url: new URL(`https://civibus.test/state/${code}`),
    locals: {
      api: { requestJson }
    }
  } as unknown as Parameters<typeof load>[0];
}

function stateNode(stateCode: string, stateName: string): RegionalNavigationNode {
  return buildUnavailableStateNode(stateCode, stateName);
}

function washingtonNode(): RegionalNavigationNode {
  return buildWashingtonNode();
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

  it("renders an unavailable state without calling retired campaign-finance endpoints", async () => {
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
      if (path === "/v1/regional-navigation/resolve?kind=state&state_code=NC") {
        return stateNode("NC", "North Carolina");
      }
      if (path === "/v1/regional-navigation/children?state_code=NC&kind=county") {
        return {
          items: [WAKE_NODE],
          incomplete_node_kinds: ["county"],
          has_unsafe_omissions: true
        };
      }
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
    expect(data.navigationNode.name).toBe("North Carolina");
    expect(data.featureLinks).toEqual({
      "county-id": { href: "/state/NC/county/wake", label: "Wake County" }
    });

    const calledPaths = requestJson.mock.calls.map(([path]) => String(path));
    expect(calledPaths).toEqual([
      "/v1/regional-navigation/resolve?kind=state&state_code=NC",
      "/v1/geometry?level=country",
      "/v1/civics/geometry?level=state&state=NC",
      "/v1/civics/geometry?level=county&state=NC",
      "/v1/civics/geometry?level=congressional_district&state=NC",
      "/v1/regional-navigation/children?state_code=NC&kind=county"
    ]);
    expect(calledPaths.every((path) => !path.startsWith("/v1/campaign-finance/states/"))).toBe(true);
    expect(calledPaths.every((path) => !path.startsWith("/v1/graph/"))).toBe(true);
    expect(calledPaths.every((path) => !path.startsWith("/v1/er/"))).toBe(true);
  });

  it("keeps state detail pages working when drilldown geometry is not available for that state", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === "/v1/regional-navigation/resolve?kind=state&state_code=AR") {
        return stateNode("AR", "Arkansas");
      }
      if (path === "/v1/regional-navigation/children?state_code=AR&kind=county") {
        return {
          items: [],
          incomplete_node_kinds: ["county"],
          has_unsafe_omissions: true
        };
      }
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

  it("loads the complete Washington projection through regional owners without a retired finance request", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === "/v1/regional-navigation/resolve?kind=state&state_code=WA") {
        return washingtonNode();
      }
      if (path === "/v1/regional-navigation/children?state_code=WA&kind=county") {
        return {
          items: [],
          incomplete_node_kinds: ["county"],
          has_unsafe_omissions: true
        };
      }
      if (path === "/v1/geometry?level=country") {
        return { type: "FeatureCollection", features: [] };
      }
      if (path.startsWith("/v1/civics/geometry?")) {
        throw new ApiResponseError(404, { detail: "Civic geometry not found" });
      }
      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson, "WA"))) as StatePageData;

    expect(data.navigationNode.finance.status).toBe("available");
    expect(data.navigationNode.finance_detail?.money[0]).toMatchObject({
      key: "contributions",
      amount: "125.50",
      transaction_count: 1
    });
    expect(data.navigationNode.finance_detail?.candidates[0]?.person_name).toBe("Alex Washington");
    expect(data.navigationNode.finance_detail?.committees[0]?.name).toBe(
      "Washington Future Committee"
    );
    const calledPaths = requestJson.mock.calls.map(([path]) => String(path));
    expect(calledPaths).toContain("/v1/regional-navigation/resolve?kind=state&state_code=WA");
    expect(calledPaths.every((path) => !path.startsWith("/v1/campaign-finance/states/"))).toBe(true);
  });

  it("redirects a resolver-proven lowercase state alias and preserves its query", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === "/v1/regional-navigation/resolve?kind=state&state_code=WA") {
        return washingtonNode();
      }
      throw new Error(`unexpected path: ${path}`);
    });
    const event = createLoadEvent(requestJson, "wa");
    event.url = new URL("https://civibus.test/state/wa?view=map");

    await expect(load(event)).rejects.toMatchObject({
      status: 308,
      location: "/state/WA?view=map"
    });
    expect(requestJson).toHaveBeenCalledTimes(1);
  });
});
