// @vitest-environment jsdom
import "$lib/client_test_environment";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mount, unmount } from "svelte";
import CoveragePage from "./+page.svelte";

const currentPageUrl = new URL("https://civibus.test/coverage");
let mountedComponents: Record<string, unknown>[] = [];

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

afterEach(async () => {
  for (const component of mountedComponents) {
    await unmount(component);
  }
  mountedComponents = [];
  document.body.innerHTML = "";
});

describe("/coverage client row identity", () => {
  it("renders contract-distinct coverage row identities in backend order", () => {
    const target = document.createElement("div");
    document.body.append(target);
    const component = mount(CoveragePage, {
      target,
      props: {
        data: {
          coverageRows: [
            {
              domain: "campaign_finance",
              jurisdiction: null,
              data_source_count: 17,
              latest_data_source_pull_at: null,
              latest_source_pull_date: null
            },
            {
              domain: "campaign_finance",
              jurisdiction: "null",
              data_source_count: 29,
              latest_data_source_pull_at: "2026-08-27T12:00:00Z",
              latest_source_pull_date: "2026-08-26T12:00:00Z"
            }
          ]
        }
      }
    });
    mountedComponents.push(component as Record<string, unknown>);

    const table = target.querySelector("table");
    const headers = Array.from(table?.querySelectorAll("th") ?? []);
    const rows = Array.from(table?.querySelectorAll("tbody tr") ?? []);

    expect(target.querySelector("section")?.getAttribute("aria-label")).toBe("Coverage registry");
    expect(target.querySelector("h2")?.textContent).toBe("Coverage registry");
    expect(headers.map((header) => [header.textContent, header.getAttribute("scope")])).toEqual([
      ["Domain", "col"],
      ["Jurisdiction", "col"],
      ["Data sources", "col"],
      ["Latest source pull date", "col"],
      ["Latest data-source pull at", "col"]
    ]);
    expect(rows.map((row) => Array.from(row.querySelectorAll("td"), (cell) => cell.textContent))).toEqual([
      ["campaign_finance", "(none)", "17", "unknown", "unknown"],
      [
        "campaign_finance",
        "null",
        "29",
        "2026-08-26T12:00:00Z",
        "2026-08-27T12:00:00Z"
      ]
    ]);
  });
});
