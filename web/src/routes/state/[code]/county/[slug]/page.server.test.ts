import type { CivicGeometryLevel, MapLayerVisibility, MapPageLevel } from "$lib/config/app";
import type { TrustSectionViewModel } from "$lib/detail-trust/presentation";
import type { CivicGeometryFeatureCollection } from "$lib/server/api/civic-geometry";
import { ApiResponseError } from "$lib/server/api/client";
import { describe, expect, it, vi } from "vitest";
import { load } from "./+page.server";

type CountyPageData = {
  stateCode: string;
  countySlug: string;
  countyName: string;
  pageLevel: MapPageLevel;
  geometryByLevel: Record<CivicGeometryLevel, CivicGeometryFeatureCollection>;
  layerVisibilityDefaults: MapLayerVisibility;
  donor_total_cents: number;
  transaction_count: number;
  top_recipient_committees: Array<{
    committee_id: string;
    committee_name: string;
    donor_total_cents: number;
    transaction_count: number;
  }>;
  top_linked_candidates: Array<{
    candidate_id: string;
    candidate_name: string;
    donor_total_cents: number;
    transaction_count: number;
  }>;
  trustSection: TrustSectionViewModel;
};

function createLoadEvent(requestJson: ReturnType<typeof vi.fn>, code = "nc", slug = "wake") {
  return {
    params: { code, slug },
    locals: {
      api: { requestJson }
    }
  } as unknown as Parameters<typeof load>[0];
}

describe("/state/[code]/county/[slug] +page.server load", () => {
  it("loads county geometry, district overlay, and county campaign-finance summary for the slug", async () => {
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
                boundary_year: 2024
              }
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
                id: "district-01",
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
              transaction_count: 2
            }
          ],
          top_linked_candidates: [
            {
              candidate_id: "22222222-2222-4222-8222-222222222222",
              candidate_name: "Candidate B",
              donor_total_cents: 12000,
              transaction_count: 2
            }
          ],
          sources: [
            {
              domain: "campaign_finance",
              jurisdiction: "state/nc",
              data_source_name: "NC Board",
              data_source_url: "https://example.org/source",
              source_record_key: "wake-summary-001",
              record_url: "https://example.org/record/001",
              pull_date: "2026-04-20T12:00:00Z"
            }
          ]
        };
      }

      throw new Error(`unexpected path: ${path}`);
    });

    const data = (await load(createLoadEvent(requestJson))) as CountyPageData;

    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([
      "/v1/civics/geometry?level=county&state=NC",
      "/v1/civics/geometry?level=congressional_district&state=NC",
      "/v1/counties/nc/wake/campaign-finance-summary"
    ]);

    expect(data.stateCode).toBe("NC");
    expect(data.countySlug).toBe("wake");
    expect(data.countyName).toBe("Wake");
    expect(data.pageLevel).toBe("county");
    expect(data.geometryByLevel.county.features).toHaveLength(1);
    expect(data.geometryByLevel.county.features[0]?.properties.name).toBe("nc_county_wake");
    expect(data.geometryByLevel.congressional_district.features[0]?.properties.name).toBe("nc_cd_01");
    expect(data.layerVisibilityDefaults).toEqual({
      nc_statewide_boundary: false,
      nc_county_boundaries: true,
      nc_congressional_districts: false
    });

    expect(data.donor_total_cents).toBe(12345);
    expect(data.top_recipient_committees[0]?.committee_name).toBe("Committee A");
    expect(data.top_linked_candidates[0]?.candidate_name).toBe("Candidate B");
    expect(data.trustSection.rows).toHaveLength(1);
    expect(data.trustSection.rows[0]?.sourceRecordKey).toBe("wake-summary-001");
  });

  it("returns 404 when county slug does not match any county geometry row", async () => {
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
                boundary_year: 2024
              }
            }
          ]
        };
      }

      if (path === "/v1/civics/geometry?level=congressional_district&state=NC") {
        return { type: "FeatureCollection", features: [] };
      }

      if (path === "/v1/counties/nc/wake/campaign-finance-summary") {
        throw new Error("county summary should not be requested for an unknown county geometry slug");
      }

      throw new Error(`unexpected path: ${path}`);
    });

    await expect(load(createLoadEvent(requestJson))).rejects.toMatchObject({
      status: 404,
      body: { detail: "County geometry not found" }
    });
  });

  it("preserves backend 404 payloads from the county summary endpoint", async () => {
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
                boundary_year: 2024
              }
            }
          ]
        };
      }

      if (path === "/v1/civics/geometry?level=congressional_district&state=NC") {
        return { type: "FeatureCollection", features: [] };
      }

      if (path === "/v1/counties/nc/wake/campaign-finance-summary") {
        throw new ApiResponseError(404, { detail: "Unknown county slug for state: nc/wake" });
      }

      throw new Error(`unexpected path: ${path}`);
    });

    await expect(load(createLoadEvent(requestJson))).rejects.toMatchObject({
      status: 404,
      body: { detail: "Unknown county slug for state: nc/wake" }
    });
  });
});
