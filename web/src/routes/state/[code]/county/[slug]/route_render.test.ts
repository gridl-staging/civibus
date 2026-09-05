import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "svelte/server";
import {
  buildMapLayerVisibilityDefaults,
  type CivicGeometryLevel,
} from "$lib/config/app";
import type { CivicGeometryFeatureCollection } from "$lib/server/api/civic-geometry";
import CountyPage from "./+page.svelte";
import { WAKE_NODE } from "$lib/regional-navigation/test-fixtures";

let currentPageUrl = new URL("https://civibus.test/state/NC/county/wake");

vi.mock("$env/dynamic/public", () => ({
  env: { PUBLIC_ORIGIN: "https://civibus.test" },
}));
vi.mock("$app/stores", () => ({
  page: {
    subscribe(run: (value: { url: URL }) => void): () => void {
      run({ url: currentPageUrl });
      return () => {};
    },
  },
}));

function emptyFeatureCollection(): CivicGeometryFeatureCollection {
  return { type: "FeatureCollection", features: [] };
}

function countyPageData() {
  const geometryByLevel: Record<
    CivicGeometryLevel,
    CivicGeometryFeatureCollection
  > = {
    state: emptyFeatureCollection(),
    county: emptyFeatureCollection(),
    congressional_district: emptyFeatureCollection(),
  };

  return {
    stateCode: "NC",
    countySlug: "wake",
    countyName: "Wake County",
    hasCountyGeometry: false,
    pageLevel: "county" as const,
    geometryByLevel,
    layerVisibilityDefaults: buildMapLayerVisibilityDefaults("county"),
    navigationNode: WAKE_NODE,
    proxySummary: null,
  };
}

describe("/state/[code]/county/[slug] route rendering", () => {
  beforeEach(() => {
    currentPageUrl = new URL("https://civibus.test/state/NC/county/wake");
  });

  it("separates unavailable county finance from the narrower, not-combined proxy control", () => {
    const rendered = render(CountyPage, {
      props: { data: countyPageData() } as never,
    });

    expect(rendered.body).toContain("Campaign finance unavailable");
    expect(rendered.body).toContain(
      "County boundary geometry is unavailable; this does not change the explicit finance refusal.",
    );
    expect(rendered.body).toContain("Ordinary-locality proxy control");
    expect(rendered.body).toContain("Committee-city proxy");
    expect(rendered.body).toContain("Mapped committee-city disbursements");
    expect(rendered.body).toContain("Raleigh and Wake Forest committees");
    expect(rendered.body).toContain(
      "not combined with state or county-wide totals",
    );
    expect(rendered.body).toContain(
      "No aggregate-complete, source-record-backed proxy result is available.",
    );
    expect(rendered.body).not.toContain("Donor total");
    expect(rendered.body).not.toMatch(/\$[0-9]/);
  });

  it("uses the same county crumbs for accessible UI and JSON-LD and stays noindex", () => {
    const rendered = render(CountyPage, {
      props: { data: countyPageData() } as never,
    });

    expect(rendered.body).toContain('nav aria-label="Breadcrumb"');
    expect(rendered.body).toContain("Wake County · County");
    expect(rendered.head).toContain('"@type":"BreadcrumbList"');
    expect(rendered.head).toContain('"name":"Wake County · County"');
    expect(rendered.head).toContain(
      '<meta name="robots" content="noindex,follow"',
    );
    expect(rendered.head).toContain(
      '<link rel="canonical" href="https://civibus.test/state/NC/county/wake"',
    );
  });
});
