import { describe, expect, it, vi } from "vitest";
import { render } from "svelte/server";
import CoveragePage from "./+page.svelte";

let currentPageUrl = new URL("https://civibus.test/coverage");

vi.mock("$env/dynamic/public", () => ({
  env: {
    PUBLIC_ORIGIN: "https://civibus.test"
  }
}));

vi.mock("$app/stores", () => ({
  page: {
    subscribe(run: (value: { url: URL }) => void): () => void {
      run({ url: currentPageUrl });
      return () => {};
    }
  }
}));

describe("/coverage route rendering", () => {
  it("renders coverage summary rows", () => {
    const rendered = render(CoveragePage, {
      props: {
        data: {
          coverageRows: [
            {
              domain: "campaign_finance",
              jurisdiction: "state/nc",
              data_source_count: 2,
              latest_data_source_pull_at: "2026-04-29T12:00:00Z",
              latest_source_pull_date: "2026-04-28T12:00:00Z"
            }
          ]
        }
      }
    });

    expect(rendered.body).toContain("Coverage registry");
    expect(rendered.body).toContain("campaign_finance");
    expect(rendered.body).toContain("state/nc");
    expect(rendered.body).toContain("2");
  });

  it("renders empty-state copy when no rows are present", () => {
    const rendered = render(CoveragePage, {
      props: {
        data: { coverageRows: [] }
      }
    });

    expect(rendered.body).toContain("Coverage registry");
    expect(rendered.body).toContain("No runtime coverage rows are available right now.");
  });
});
