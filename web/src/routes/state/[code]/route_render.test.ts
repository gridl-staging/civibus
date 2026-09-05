import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "svelte/server";
import { buildMapLayerVisibilityDefaults } from "$lib/config/app";
import { buildWashingtonNode } from "$lib/regional-navigation/test-fixtures";
import type { PageData } from "./$types";
import StatePage from "./+page.svelte";

let currentPageUrl = new URL("https://civibus.test/state/WA");

vi.mock("$env/dynamic/public", () => ({ env: { PUBLIC_ORIGIN: "https://civibus.test" } }));
vi.mock("$app/stores", () => ({
  page: {
    subscribe(run: (value: { url: URL }) => void): () => void {
      run({ url: currentPageUrl });
      return () => {};
    }
  }
}));

function statePageData(status: "available" | "degraded" | "stale" | "unavailable" = "available"): PageData {
  return {
    stateCode: "WA",
    pageLevel: "state" as const,
    geometryByLevel: {
      state: { type: "FeatureCollection" as const, features: [] },
      county: { type: "FeatureCollection" as const, features: [] },
      congressional_district: { type: "FeatureCollection" as const, features: [] }
    },
    layerVisibilityDefaults: buildMapLayerVisibilityDefaults("state"),
    geometry: { type: "FeatureCollection" as const, features: [] },
    featureLinks: {},
    navigationNode: buildWashingtonNode(status)
  };
}

describe("/state/[code] regional rendering", () => {
  beforeEach(() => {
    currentPageUrl = new URL("https://civibus.test/state/WA");
  });

  it("renders one accessible breadcrumb model in UI and JSON-LD", () => {
    const rendered = render(StatePage, { props: { data: statePageData() } as never });

    expect(rendered.body).toContain('nav aria-label="Breadcrumb"');
    expect(rendered.body).toContain("Washington");
    expect(rendered.head).toContain('"@type":"BreadcrumbList"');
    expect(rendered.head).toContain('"name":"Washington"');
  });

  it("renders exact real-money classes, civic connections, committees, and trust evidence", () => {
    const rendered = render(StatePage, { props: { data: statePageData() } as never });

    expect(rendered.head).toContain('<meta name="robots" content="noindex,follow"');
    expect(rendered.head).toContain('<link rel="canonical" href="https://civibus.test/state/WA"');
    expect(rendered.body).toContain("Campaign finance available");
    expect(rendered.body).toContain("Filing-authority relation");
    expect(rendered.body).toContain("unresolved");
    expect(rendered.body).toContain("Authority-scoped reporting window");
    expect(rendered.body).toContain("$125.50");
    expect(rendered.body).toContain("$80.25");
    expect(rendered.body).toContain("$45.75");
    expect(rendered.body).toContain("$20.00");
    expect(rendered.body).toContain("Candidate-targeted independent expenditures");
    expect(rendered.body).toContain('href="/person/53000000-0000-4000-8000-000000000001"');
    expect(rendered.body).toContain('href="/candidacy/53000000-0000-4000-8000-000000000005"');
    expect(rendered.body).toContain('href="/contest/53000000-0000-4000-8000-000000000004"');
    expect(rendered.body).toContain('href="/office/00000000-0000-4000-8000-000000000204"');
    expect(rendered.body).toContain('href="/committee/53000000-0000-4000-8000-000000000003"');
    expect(rendered.body).toContain("Connected by unique WA native filer ID");
    expect(rendered.body).toContain("Coverage boundary");
    expect(rendered.body).toContain("No authority amount is combined with county, municipality");
    expect(rendered.body).toContain("Authority health and promotion gate");
    expect(rendered.body).toContain("Revision parity: unknown");
    expect(rendered.body).toContain("Promotion eligible: no");
    expect(rendered.body).toContain("Last successful source pull");
    expect(rendered.body).toContain("Latest refresh run");
    expect(rendered.body).toContain("Transaction data through");
    expect(rendered.body).toContain("Registry evidence date");
    expect(rendered.body).toContain("Lifecycle observation date");
    expect(rendered.body).toContain("Named gaps and limitations");
    expect(rendered.body.match(/role="status"/g)).toHaveLength(1);
  });

  it("shows unavailable source classes without fabricating zero or hiding limitations", () => {
    const rendered = render(StatePage, { props: { data: statePageData("unavailable") } as never });

    expect(rendered.body).toContain("Campaign finance unavailable");
    expect(rendered.body).toContain("Unavailable");
    expect(rendered.body).toContain("0 transactions");
    expect(rendered.body).toContain("No current-window candidacy connection is available");
    expect(rendered.body).toContain("The exact configured runtime source is absent.");
    expect(rendered.body).not.toMatch(/\$0\.00/);
    expect(rendered.body).not.toContain("Reopening state coverage");
    expect(rendered.body.match(/role="status"/g)).toHaveLength(1);
  });
});
