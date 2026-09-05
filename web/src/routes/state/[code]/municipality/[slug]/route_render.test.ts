import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "svelte/server";
import { NYC_NODE, SEATTLE_NODE } from "$lib/regional-navigation/test-fixtures";
import MunicipalityPage from "./+page.svelte";

let currentPageUrl = new URL("https://civibus.test/state/WA/municipality/seattle");

vi.mock("$env/dynamic/public", () => ({ env: { PUBLIC_ORIGIN: "https://civibus.test" } }));
vi.mock("$app/stores", () => ({
  page: {
    subscribe(run: (value: { url: URL }) => void): () => void {
      run({ url: currentPageUrl });
      return () => {};
    }
  }
}));

describe("municipality authority rendering", () => {
  beforeEach(() => {
    currentPageUrl = new URL("https://civibus.test/state/WA/municipality/seattle");
  });

  it("names every Seattle overlap authority while refusing a combined total", () => {
    const rendered = render(MunicipalityPage, {
      props: {
        data: { navigationNode: SEATTLE_NODE, stateCode: "WA", municipalityName: "Seattle" }
      } as never
    });

    expect(rendered.body).toContain("Seattle");
    expect(rendered.body).toContain("partitioned_overlapping");
    expect(rendered.body).toContain("refuse_combination");
    expect(rendered.body).toContain("Seattle City Clerk");
    expect(rendered.body).toContain("Seattle Ethics and Elections Commission");
    expect(rendered.body).toContain("WA_SEATTLE_CITY_CLERK");
    expect(rendered.body).toContain("WA_SEEC");
    expect(rendered.body).toContain("Authority health and promotion refusal");
    expect(rendered.body).toContain("No state, parent, child, or direct-target amount is guessed or combined");
    expect(rendered.body).not.toMatch(/\$[0-9]/);
  });

  it("keeps New York City and New York State partitioned without a combined total", () => {
    currentPageUrl = new URL("https://civibus.test/state/NY/municipality/new-york-city");
    const rendered = render(MunicipalityPage, {
      props: {
        data: { navigationNode: NYC_NODE, stateCode: "NY", municipalityName: "New York City" }
      } as never
    });

    expect(rendered.body).toContain("partitioned_overlapping");
    expect(rendered.body).toContain("refuse_combination");
    expect(rendered.body).toContain("state/NY");
    expect(rendered.body).toContain("municipality/NY_NEW_YORK");
    expect(rendered.body).toContain("No New York State or combined total is shown");
    expect(rendered.body).not.toMatch(/\$[0-9]/);
  });
});
