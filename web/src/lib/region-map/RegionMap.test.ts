import { describe, expect, it } from "vitest";
import { render } from "svelte/server";
import RegionMap from "./RegionMap.svelte";
import type {
  GeometryFeatureCollection,
  StateSummaryItem
} from "$lib/server/api/state-pages-contract";

function buildSummary(
  overrides: Partial<StateSummaryItem> & Pick<StateSummaryItem, "state_code">
): StateSummaryItem {
  return {
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
    data_through: null,
    ...overrides
  };
}

function buildFeature(state: string, name: string): GeometryFeatureCollection["features"][number] {
  return {
    type: "Feature",
    geometry: {
      type: "Polygon",
      coordinates: [
        [
          [-100, 30],
          [-95, 30],
          [-95, 35],
          [-100, 35]
        ]
      ]
    },
    properties: {
      state,
      name,
      division_type: "state",
      boundary_year: 2020
    }
  };
}

function buildGeometry(): GeometryFeatureCollection {
  return {
    type: "FeatureCollection",
    features: [
      buildFeature("CA", "California"),
      buildFeature("TX", "Texas"),
      buildFeature("NC", "North Carolina")
    ]
  };
}

describe("RegionMap", () => {
  it("renders supported states as enabled /state/{CODE} links", () => {
    const geometry = buildGeometry();
    const stateSummaries: StateSummaryItem[] = [
      buildSummary({ state_code: "CA", supported: true, support_status: "supported" }),
      buildSummary({ state_code: "TX", supported: false, support_status: "unsupported" }),
      buildSummary({ state_code: "NC", supported: true, support_status: "supported" })
    ];

    const rendered = render(RegionMap, { props: { geometry, stateSummaries } });

    expect(rendered.body).toContain('href="/state/CA"');
    expect(rendered.body).toContain("California");
    expect(rendered.body).toContain('href="/state/NC"');
    expect(rendered.body).not.toContain('href="/state/TX"');
  });

  it("renders unsupported states with aria-disabled and the unavailable copy", () => {
    const geometry = buildGeometry();
    const stateSummaries: StateSummaryItem[] = [
      buildSummary({ state_code: "TX", supported: false, support_status: "unsupported" }),
      buildSummary({ state_code: "CA", supported: true })
    ];

    const rendered = render(RegionMap, { props: { geometry, stateSummaries } });

    expect(rendered.body).toContain('aria-disabled="true"');
    expect(rendered.body).toContain("Coverage not yet available");
    expect(rendered.body).toContain("Texas");
  });

  it("keeps warning states disabled and surfaces warning_text as visible text", () => {
    const geometry: GeometryFeatureCollection = {
      type: "FeatureCollection",
      features: [buildFeature("MN", "Minnesota")]
    };
    const stateSummaries: StateSummaryItem[] = [
      buildSummary({
        state_code: "MN",
        supported: false,
        support_status: "warning",
        warning_text: "Quarterly bulk only — last refresh 90 days ago"
      })
    ];

    const rendered = render(RegionMap, { props: { geometry, stateSummaries } });

    expect(rendered.body).toContain("Quarterly bulk only — last refresh 90 days ago");
    expect(rendered.body).toContain('aria-disabled="true"');
    expect(rendered.body).toContain("Minnesota — Coverage incomplete");
    expect(rendered.body).not.toContain("Minnesota — Coverage not yet available");
    expect(rendered.body).not.toContain('href="/state/MN"');
  });

  it("treats states without a matching summary as unsupported", () => {
    const geometry: GeometryFeatureCollection = {
      type: "FeatureCollection",
      features: [buildFeature("WY", "Wyoming")]
    };

    const rendered = render(RegionMap, {
      props: { geometry, stateSummaries: [] }
    });

    expect(rendered.body).toContain('aria-disabled="true"');
    expect(rendered.body).toContain("Coverage not yet available");
    expect(rendered.body).not.toContain('href="/state/WY"');
  });

  it("applies a single disabled CSS class instead of inline styles", () => {
    const geometry: GeometryFeatureCollection = {
      type: "FeatureCollection",
      features: [buildFeature("TX", "Texas")]
    };
    const stateSummaries: StateSummaryItem[] = [
      buildSummary({ state_code: "TX", supported: false, support_status: "unsupported" })
    ];

    const rendered = render(RegionMap, { props: { geometry, stateSummaries } });

    expect(rendered.body).toMatch(/class="[^"]*region-map__region--disabled[^"]*"/);
    expect(rendered.body).not.toMatch(/<path[^>]*style=/);
  });

  it("renders GeoJSON features for always-on and visible layers", () => {
    const rendered = render(RegionMap, {
      props: {
        pageLevel: "state",
        layerVisibility: {
          nc_statewide_boundary: true,
          nc_county_boundaries: true,
          nc_congressional_districts: false
        },
        geometryByLevel: {
          state: {
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
                  boundary_year: 2020
                }
              }
            ]
          },
          county: {
            type: "FeatureCollection",
            features: [
              {
                type: "Feature",
                geometry: { type: "Polygon", coordinates: [] },
                properties: {
                  id: "county-id",
                  name: "Wake County",
                  division_type: "county",
                  state: "NC",
                  district_number: null,
                  boundary_year: 2024
                }
              }
            ]
          },
          congressional_district: {
            type: "FeatureCollection",
            features: [
              {
                type: "Feature",
                geometry: { type: "Polygon", coordinates: [] },
                properties: {
                  id: "district-id",
                  name: "Congressional District 01",
                  division_type: "congressional_district",
                  state: "NC",
                  district_number: "01",
                  boundary_year: 2024
                }
              }
            ]
          }
        }
      }
    });

    expect(rendered.body).toContain("North Carolina");
    expect(rendered.body).toContain("Wake County");
    expect(rendered.body).toContain('data-layer-id="nc_statewide_boundary"');
    expect(rendered.body).toContain('data-layer-id="nc_county_boundaries"');
    expect(rendered.body).not.toContain("Congressional District 01");
  });

  it("renders county features as drilldown links when the state code is provided", () => {
    const rendered = render(RegionMap, {
      props: {
        pageLevel: "state",
        stateCode: "NC",
        layerVisibility: {
          nc_statewide_boundary: true,
          nc_county_boundaries: true,
          nc_congressional_districts: false
        },
        geometryByLevel: {
          state: {
            type: "FeatureCollection",
            features: []
          },
          county: {
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
          },
          congressional_district: {
            type: "FeatureCollection",
            features: []
          }
        }
      }
    });

    expect(rendered.body).toContain('href="/state/NC/county/wake"');
  });

  it("highlights only the matching feature id while preserving visible non-highlighted layers", () => {
    const rendered = render(RegionMap, {
      props: {
        pageLevel: "state",
        stateCode: "NC",
        highlightedFeatureId: "county-id-2",
        layerVisibility: {
          nc_statewide_boundary: true,
          nc_county_boundaries: true,
          nc_congressional_districts: false
        },
        geometryByLevel: {
          state: {
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
                  boundary_year: 2020
                }
              }
            ]
          },
          county: {
            type: "FeatureCollection",
            features: [
              {
                type: "Feature",
                geometry: { type: "Polygon", coordinates: [] },
                properties: {
                  id: "county-id-1",
                  name: "nc_county_mecklenburg",
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
                  id: "county-id-2",
                  name: "nc_county_wake",
                  division_type: "county",
                  state: "NC",
                  district_number: null,
                  boundary_year: 2024
                }
              }
            ]
          },
          congressional_district: {
            type: "FeatureCollection",
            features: []
          }
        }
      }
    });

    expect(rendered.body).toContain('data-feature-id="county-id-1"');
    expect(rendered.body).toContain('data-feature-id="county-id-2"');
    expect(rendered.body).toContain("North Carolina");
    expect(rendered.body).toMatch(/class="[^"]*region-map__feature--highlighted[^"]*"/);
    expect(rendered.body).toMatch(/class="[^"]*region-map__feature--deemphasized[^"]*"/);
  });

  it("falls back cleanly when a highlight id is provided but no feature matches", () => {
    const rendered = render(RegionMap, {
      props: {
        pageLevel: "state",
        highlightedFeatureId: "missing-feature-id",
        layerVisibility: {
          nc_statewide_boundary: true,
          nc_county_boundaries: true,
          nc_congressional_districts: false
        },
        geometryByLevel: {
          state: {
            type: "FeatureCollection",
            features: []
          },
          county: {
            type: "FeatureCollection",
            features: []
          },
          congressional_district: {
            type: "FeatureCollection",
            features: []
          }
        }
      }
    });

    expect(rendered.body).toContain("State boundary:");
    expect(rendered.body).toContain("No geometry available.");
    expect(rendered.body).not.toContain("region-map__feature--highlighted");
  });
});
