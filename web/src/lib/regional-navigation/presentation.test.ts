import { describe, expect, it } from "vitest";
import type { CivicGeometryFeatureCollection } from "$lib/server/api/civic-geometry";
import type { RegionalNavigationNode } from "$lib/server/api/state-pages-contract";
import { buildWashingtonNode, WAKE_NODE } from "$lib/regional-navigation/test-fixtures";
import {
  buildRegionalAliasRedirect,
  buildRegionalBreadcrumbs,
  buildRegionalFeatureLinks,
  buildRegionalRouteMetadata,
  buildRegionalSearchCards,
  buildRegionalStateFinancePresentation
} from "./presentation";

const WA_NODE = buildWashingtonNode();

describe("regional navigation presentation", () => {
  it("builds one crumb array for state and county routes", () => {
    expect(buildRegionalBreadcrumbs(WA_NODE)).toEqual([
      { label: "Home", href: "/" },
      { label: "Washington" }
    ]);
    expect(buildRegionalBreadcrumbs(WAKE_NODE)).toEqual([
      { label: "Home", href: "/" },
      { label: "North Carolina", href: "/state/NC" },
      { label: "Wake County · County" }
    ]);
  });

  it("keeps regional pages noindex while building truthful metadata", () => {
    expect(buildRegionalRouteMetadata(WA_NODE)).toEqual({
      title: "Washington | State | Civibus",
      description: "Regional navigation for Washington. Campaign-finance data is available.",
      robots: "noindex,follow"
    });
  });

  it("preserves query parameters only after a resolver-proven alias", () => {
    expect(buildRegionalAliasRedirect(WA_NODE, new URL("https://civibus.test/state/wa?view=map"))).toBe(
      "/state/WA?view=map"
    );
    expect(buildRegionalAliasRedirect(WA_NODE, new URL("https://civibus.test/state/WA?view=map"))).toBeNull();
  });

  it("links geometry only through an exact typed owner reference", () => {
    const geometry: CivicGeometryFeatureCollection = {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          geometry: { type: "Polygon", coordinates: [] },
          properties: {
            id: "wake-id",
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
            id: "lookalike-id",
            name: "Wake County",
            division_type: "county",
            state: "NC",
            district_number: null,
            boundary_year: 2024
          }
        }
      ]
    };

    expect(buildRegionalFeatureLinks([WAKE_NODE], geometry)).toEqual({
      "wake-id": { href: "/state/NC/county/wake", label: "Wake County" }
    });
  });

  it("refuses ambiguous exact geometry matches", () => {
    const duplicateGeometry: CivicGeometryFeatureCollection = {
      type: "FeatureCollection",
      features: ["one", "two"].map((id) => ({
        type: "Feature" as const,
        geometry: { type: "Polygon" as const, coordinates: [] },
        properties: {
          id,
          name: "nc_county_wake",
          division_type: "county",
          state: "NC",
          district_number: null,
          boundary_year: 2024
        }
      }))
    };

    expect(buildRegionalFeatureLinks([WAKE_NODE], duplicateGeometry)).toEqual({});
  });

  it("refuses one geometry feature claimed by two distinct canonical nodes", () => {
    const geometry: CivicGeometryFeatureCollection = {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          geometry: { type: "Polygon", coordinates: [] },
          properties: {
            id: "wake-id",
            name: "nc_county_wake",
            division_type: "county",
            state: "NC",
            district_number: null,
            boundary_year: 2024
          }
        }
      ]
    };
    const aliasNode: RegionalNavigationNode = {
      ...WAKE_NODE,
      name: "Wake County Alias",
      slug: "wake-county",
      canonical_path: "/state/NC/county/wake-county"
    };

    expect(buildRegionalFeatureLinks([WAKE_NODE, aliasNode], geometry)).toEqual({});
    expect(buildRegionalFeatureLinks([aliasNode, WAKE_NODE], geometry)).toEqual({});
  });

  it("builds typed regional search cards", () => {
    expect(buildRegionalSearchCards([WA_NODE, WAKE_NODE])).toEqual([
      {
        key: "state:/state/WA",
        name: "Washington",
        routeLabel: "State",
        contextLine: "Finance available · authority translation refused",
        href: "/state/WA"
      },
      {
        key: "county:/state/NC/county/wake",
        name: "Wake County",
        routeLabel: "County",
        contextLine: "Finance unavailable · authority translation refused",
        href: "/state/NC/county/wake"
      }
    ]);
  });

  it("builds exact money, civic links, and distinct provenance clocks", () => {
    const presentation = buildRegionalStateFinancePresentation(WA_NODE);

    expect(presentation?.subject).toEqual({
      kind: "state",
      code: "WA",
      name: "Washington"
    });
    expect(presentation?.authorityContext).toMatchObject({
      relation: "unresolved",
      translationStatus: "refused",
      publicRoute: "/state/WA",
      acquisitionScope: "state/WA",
      provenanceScope: null,
      aggregationDisposition: "refuse",
      authorities: []
    });
    expect(presentation?.authorityHealth[0]).toMatchObject({
      authorityCode: "WA",
      freshnessStatus: "available",
      recurrenceStatus: "qualified",
      revisionParity: "unknown",
      promotionEligible: false
    });
    expect(presentation?.windowLabel).toBe("2025-01-01 through 2026-08-28");
    expect(presentation?.money.map((row) => [row.key, row.amountLabel, row.transactionLabel])).toEqual([
      ["contributions", "$125.50", "1 transaction"],
      ["expenditures", "$80.25", "1 transaction"],
      ["independent_expenditures", "$45.75", "1 transaction"],
      ["loans", "$20.00", "1 transaction"]
    ]);
    expect(presentation?.sources[0]).toMatchObject({
      classKey: "contributions",
      status: "available",
      lastSuccessfulPull: { datetime: "2026-08-28T16:00:00Z", label: "2026-08-28" },
      latestRefreshCompletedAt: { datetime: "2026-08-28T16:00:00Z", label: "2026-08-28" },
      latestRefreshStatus: "success",
      latestRefreshExecutionOrigin: "scheduled",
      recurrenceStatus: "qualified"
    });
    expect(presentation?.candidates[0]).toMatchObject({
      personHref: "/person/53000000-0000-4000-8000-000000000001",
      candidacyHref: "/candidacy/53000000-0000-4000-8000-000000000005",
      contestHref: "/contest/53000000-0000-4000-8000-000000000004",
      officeHref: "/office/00000000-0000-4000-8000-000000000204",
      currentOfficeholdingHref: "/officeholding/53000000-0000-4000-8000-000000000006",
      moneyLabel: "$271.50",
      connectionLabel: "Connected by unique WA native filer ID"
    });
    expect(presentation?.committees[0]).toMatchObject({
      href: "/committee/53000000-0000-4000-8000-000000000003",
      activityLabel: "$271.50"
    });
  });

  it("presents unavailable classes as unavailable rather than zero", () => {
    const unavailable = buildRegionalStateFinancePresentation(buildWashingtonNode("unavailable"));

    expect(unavailable?.money.every((row) => row.amountLabel === "Unavailable")).toBe(true);
    expect(unavailable?.money.every((row) => row.transactionLabel === "0 transactions")).toBe(true);
    expect(unavailable?.candidates).toEqual([]);
    expect(unavailable?.committees).toEqual([]);
  });
});
