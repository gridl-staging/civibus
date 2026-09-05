import type {
  CivicGeometryLevel,
  MapLayerVisibility,
  MapPageLevel,
} from "$lib/config/app";
import type { CivicGeometryFeatureCollection } from "$lib/server/api/civic-geometry";
import { ApiResponseError } from "$lib/server/api/client";
import { describe, expect, it, vi } from "vitest";
import { load } from "./+page.server";
import type { RegionalNavigationNode } from "$lib/server/api/state-pages-contract";
import { WAKE_NODE } from "$lib/regional-navigation/test-fixtures";

type CountyPageData = {
  stateCode: string;
  countySlug: string;
  countyName: string;
  hasCountyGeometry: boolean;
  pageLevel: MapPageLevel;
  geometryByLevel: Record<CivicGeometryLevel, CivicGeometryFeatureCollection>;
  layerVisibilityDefaults: MapLayerVisibility;
  navigationNode: RegionalNavigationNode;
  proxySummary: null;
};

function createLoadEvent(
  requestJson: ReturnType<typeof vi.fn<(path: string) => unknown>>,
  code = "NC",
  slug = "wake",
) {
  const navigationAwareRequest = vi.fn(async (path: string) => {
    if (
      path ===
      `/v1/regional-navigation/resolve?kind=county&state_code=${code.toUpperCase()}&slug=${slug}`
    ) {
      return WAKE_NODE;
    }
    return requestJson(path);
  });
  return {
    params: { code, slug },
    url: new URL(`https://civibus.test/state/${code}/county/${slug}`),
    locals: {
      api: { requestJson: navigationAwareRequest },
    },
  } as unknown as Parameters<typeof load>[0];
}

function createWakeCountyGeometry(): CivicGeometryFeatureCollection {
  return {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        geometry: { type: "Polygon", coordinates: [] },
        properties: {
          id: "county-wake",
          name: "nc_county_wake",
          division_type: "county",
          state: "NC",
          district_number: null,
          boundary_year: 2024,
        },
      },
    ],
  };
}

describe("/state/[code]/county/[slug] +page.server load", () => {
  it("redirects a resolver-proven state-code alias and preserves its query", async () => {
    const event = createLoadEvent(vi.fn(), "nc");
    event.url = new URL("https://civibus.test/state/nc/county/wake?view=map");

    await expect(load(event)).rejects.toMatchObject({
      status: 308,
      location: "/state/NC/county/wake?view=map",
    });
  });

  it("loads county geometry and keeps the unproven proxy aggregate closed", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === "/v1/civics/geometry?level=county&state=NC") {
        return {
          type: "FeatureCollection",
          features: [
            {
              type: "Feature",
              geometry: { type: "Polygon", coordinates: [] },
              properties: {
                id: "county-wake",
                name: "nc_county_wake",
                division_type: "county",
                state: "NC",
                district_number: null,
                boundary_year: 2024,
              },
            },
            {
              type: "Feature",
              geometry: { type: "Polygon", coordinates: [] },
              properties: {
                id: "county-durham",
                name: "nc_county_durham",
                division_type: "county",
                state: "NC",
                district_number: null,
                boundary_year: 2024,
              },
            },
          ],
        };
      }

      if (
        path === "/v1/civics/geometry?level=congressional_district&state=NC"
      ) {
        return {
          type: "FeatureCollection",
          features: [
            {
              type: "Feature",
              geometry: { type: "Polygon", coordinates: [] },
              properties: {
                id: "district-01",
                name: "nc_cd_01",
                division_type: "congressional_district",
                state: "NC",
                district_number: "01",
                boundary_year: 2024,
              },
            },
          ],
        };
      }

      if (path === "/v1/counties/nc/wake/campaign-finance-summary") {
        return {
          state: "nc",
          county_slug: "wake",
          donor_total_cents: 12345,
          transaction_count: 2,
          top_recipient_committees: [
            {
              committee_id: "11111111-1111-4111-8111-111111111111",
              committee_name: "Committee A",
              donor_total_cents: 12000,
              transaction_count: 2,
            },
          ],
          top_linked_candidates: [
            {
              candidate_id: "22222222-2222-4222-8222-222222222222",
              candidate_name: "Candidate B",
              donor_total_cents: 12000,
              transaction_count: 2,
              identity_is_safe: true,
            },
          ],
          sources: [
            {
              domain: "campaign_finance",
              jurisdiction: "state/nc",
              data_source_name: "NC Board",
              data_source_url: "https://example.org/source",
              source_record_key: "wake-summary-001",
              record_url: "https://example.org/record/001",
              pull_date: "2026-04-20T12:00:00Z",
            },
          ],
        };
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as CountyPageData;

    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      "/v1/civics/geometry?level=county&state=NC",
      "/v1/civics/geometry?level=congressional_district&state=NC",
    ]);

    expect(data.stateCode).toBe("NC");
    expect(data.countySlug).toBe("wake");
    expect(data.countyName).toBe("Wake County");
    expect(data.hasCountyGeometry).toBe(true);
    expect(data.pageLevel).toBe("county");
    expect(data.geometryByLevel.county.features).toHaveLength(1);
    expect(data.geometryByLevel.county.features[0]?.properties.name).toBe(
      "nc_county_wake",
    );
    expect(
      data.geometryByLevel.congressional_district.features[0]?.properties.name,
    ).toBe("nc_cd_01");
    expect(data.layerVisibilityDefaults).toEqual({
      nc_statewide_boundary: false,
      nc_county_boundaries: true,
      nc_congressional_districts: false,
    });

    expect(data.navigationNode.finance.status).toBe("unavailable");
    expect(data.proxySummary).toBeNull();
  });

  it("keeps a valid county page when only the optional district overlay is unavailable", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === "/v1/civics/geometry?level=county&state=NC") {
        return createWakeCountyGeometry();
      }

      if (
        path === "/v1/civics/geometry?level=congressional_district&state=NC"
      ) {
        throw new ApiResponseError(404, {
          detail: "Geometry not found for congressional_district in state NC",
        });
      }

      if (path === "/v1/counties/nc/wake/campaign-finance-summary") {
        return {
          state: "nc",
          county_slug: "wake",
          donor_total_cents: 12345,
          transaction_count: 2,
          top_recipient_committees: [],
          top_linked_candidates: [],
          sources: [
            {
              domain: "campaign_finance",
              jurisdiction: "state/nc",
              data_source_name: "NC Board",
              data_source_url: "https://example.org/source",
              source_record_key: "wake-summary-optional-overlay-404",
              record_url: "https://example.org/record/optional-overlay-404",
              pull_date: "2026-04-20T12:00:00Z",
            },
          ],
        };
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as CountyPageData;

    expect(data.geometryByLevel.county.features[0]?.properties.name).toBe(
      "nc_county_wake",
    );
    expect(data.geometryByLevel.congressional_district).toEqual({
      type: "FeatureCollection",
      features: [],
    });
    expect(data.proxySummary).toBeNull();
  });

  it("keeps a resolver-known county truthful when its boundary geometry is absent", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === "/v1/civics/geometry?level=county&state=NC") {
        return {
          type: "FeatureCollection",
          features: [
            {
              type: "Feature",
              geometry: { type: "Polygon", coordinates: [] },
              properties: {
                id: "county-durham",
                name: "nc_county_durham",
                division_type: "county",
                state: "NC",
                district_number: null,
                boundary_year: 2024,
              },
            },
          ],
        };
      }

      if (
        path === "/v1/civics/geometry?level=congressional_district&state=NC"
      ) {
        return { type: "FeatureCollection", features: [] };
      }

      if (path === "/v1/counties/nc/wake/campaign-finance-summary") {
        throw new Error(
          "county summary should not be requested for an unknown county geometry slug",
        );
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as CountyPageData;

    expect(data.hasCountyGeometry).toBe(false);
    expect(data.geometryByLevel.county.features).toEqual([]);
    expect(data.navigationNode.finance.status).toBe("unavailable");
  });

  it("keeps canonical county geography at 200 when the narrower proxy is unavailable", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === "/v1/civics/geometry?level=county&state=NC") {
        return {
          type: "FeatureCollection",
          features: [
            {
              type: "Feature",
              geometry: { type: "Polygon", coordinates: [] },
              properties: {
                id: "county-wake",
                name: "nc_county_wake",
                division_type: "county",
                state: "NC",
                district_number: null,
                boundary_year: 2024,
              },
            },
          ],
        };
      }

      if (
        path === "/v1/civics/geometry?level=congressional_district&state=NC"
      ) {
        return { type: "FeatureCollection", features: [] };
      }

      if (path === "/v1/counties/nc/wake/campaign-finance-summary") {
        throw new ApiResponseError(404, {
          detail: "Unknown county slug for state: nc/wake",
        });
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as CountyPageData;

    expect(data.navigationNode.finance.status).toBe("unavailable");
    expect(data.proxySummary).toBeNull();
  });

  it.each([0, 12345])(
    "suppresses a %i-cent proxy result when exact source-record provenance is absent",
    async (donorTotalCents) => {
      const requestJson = vi.fn(async (path: string) => {
        if (path === "/v1/civics/geometry?level=county&state=NC")
          return createWakeCountyGeometry();
        if (
          path === "/v1/civics/geometry?level=congressional_district&state=NC"
        ) {
          return { type: "FeatureCollection", features: [] };
        }
        if (path === "/v1/counties/nc/wake/campaign-finance-summary") {
          return {
            state: "nc",
            county_slug: "wake",
            donor_total_cents: donorTotalCents,
            transaction_count: donorTotalCents === 0 ? 0 : 2,
            top_recipient_committees: [],
            top_linked_candidates: [],
            sources: [],
          };
        }
        throw new Error(`unexpected path: ${path}`);
      });

      const data = (await load(createLoadEvent(requestJson))) as CountyPageData;

      expect(data.proxySummary).toBeNull();
    },
  );
});
