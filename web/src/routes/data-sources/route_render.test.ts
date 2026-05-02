import { describe, expect, it, vi } from "vitest";
import { render } from "svelte/server";
import DataSourcesPage from "./+page.svelte";

let currentPageUrl = new URL("https://civibus.test/data-sources");

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

describe("/data-sources route rendering", () => {
  it("renders data-source rows", () => {
    const rendered = render(DataSourcesPage, {
      props: {
        data: {
          dataSources: [
            {
              data_source_id: "11111111-1111-4111-8111-111111111111",
              domain: "campaign_finance",
              jurisdiction: "state/nc",
              name: "NC Disclosure",
              source_url: "https://example.org/source",
              update_frequency: "daily",
              last_pull_at: "2026-04-29T12:00:00Z",
              last_pull_status: "success",
              record_count: 10,
              latest_source_record_id: "22222222-2222-4222-8222-222222222222",
              latest_source_record_key: "record-1",
              latest_source_record_url: "https://example.org/record-1",
              latest_source_pull_date: "2026-04-28T12:00:00Z"
            }
          ]
        }
      }
    });

    expect(rendered.body).toContain("Data sources");
    expect(rendered.body).toContain("NC Disclosure");
    expect(rendered.body).toContain("campaign_finance");
    expect(rendered.body).toContain("state/nc");
    expect(rendered.body).toContain("daily");
    expect(rendered.body).toContain("record-1");
    expect(rendered.body).toContain("https://example.org/record-1");
    expect(rendered.body).toContain("2026-04-29T12:00:00Z");
    expect(rendered.body).toContain("2026-04-28T12:00:00Z");
  });

  it("renders empty-state copy when no rows are present", () => {
    const rendered = render(DataSourcesPage, {
      props: {
        data: { dataSources: [] }
      }
    });

    expect(rendered.body).toContain("Data sources");
    expect(rendered.body).toContain("No runtime data-source rows are available right now.");
  });

  it("does not render clickable latest source record links for non-http and malformed URLs", () => {
    const rendered = render(DataSourcesPage, {
      props: {
        data: {
          dataSources: [
            {
              data_source_id: "11111111-1111-4111-8111-111111111111",
              domain: "campaign_finance",
              jurisdiction: "state/nc",
              name: "NC Disclosure",
              source_url: "https://example.org/source",
              update_frequency: "daily",
              last_pull_at: "2026-04-29T12:00:00Z",
              last_pull_status: "success",
              record_count: 10,
              latest_source_record_id: "22222222-2222-4222-8222-222222222222",
              latest_source_record_key: "record-unsafe",
              latest_source_record_url: "javascript:alert(1)",
              latest_source_pull_date: "2026-04-28T12:00:00Z"
            },
            {
              data_source_id: "33333333-3333-4333-8333-333333333333",
              domain: "campaign_finance",
              jurisdiction: "state/ny",
              name: "NY Disclosure",
              source_url: "https://example.org/ny-source",
              update_frequency: "daily",
              last_pull_at: "2026-04-29T13:00:00Z",
              last_pull_status: "success",
              record_count: 12,
              latest_source_record_id: "44444444-4444-4444-8444-444444444444",
              latest_source_record_key: "record-malformed",
              latest_source_record_url: "not a url",
              latest_source_pull_date: "2026-04-29T11:00:00Z"
            }
          ]
        }
      }
    });

    expect(rendered.body).toContain("record-unsafe");
    expect(rendered.body).toContain("record-malformed");
    expect(rendered.body).not.toContain('href="javascript:alert(1)"');
    expect(rendered.body).not.toContain('href="not a url"');
    expect(rendered.body).not.toMatch(/<a[^>]*>\s*record-unsafe\s*<\/a>/);
    expect(rendered.body).not.toMatch(/<a[^>]*>\s*record-malformed\s*<\/a>/);
    expect(rendered.body).toMatch(/<td>(?:(?!<a).)*record-unsafe(?:(?!<a).)*<\/td>/s);
    expect(rendered.body).toMatch(/<td>(?:(?!<a).)*record-malformed(?:(?!<a).)*<\/td>/s);
  });

  it("does not render clickable source URL links for non-http and malformed URLs", () => {
    const rendered = render(DataSourcesPage, {
      props: {
        data: {
          dataSources: [
            {
              data_source_id: "55555555-5555-4555-8555-555555555555",
              domain: "campaign_finance",
              jurisdiction: "state/nc",
              name: "Unsafe JS Source",
              source_url: "javascript:alert(1)",
              update_frequency: "daily",
              last_pull_at: "2026-04-29T14:00:00Z",
              last_pull_status: "success",
              record_count: 14,
              latest_source_record_id: "66666666-6666-4666-8666-666666666666",
              latest_source_record_key: "record-safe",
              latest_source_record_url: "https://example.org/record-safe",
              latest_source_pull_date: "2026-04-29T13:00:00Z"
            },
            {
              data_source_id: "77777777-7777-4777-8777-777777777777",
              domain: "campaign_finance",
              jurisdiction: "state/ny",
              name: "Malformed Source",
              source_url: "not a url",
              update_frequency: "daily",
              last_pull_at: "2026-04-29T15:00:00Z",
              last_pull_status: "success",
              record_count: 16,
              latest_source_record_id: "88888888-8888-4888-8888-888888888888",
              latest_source_record_key: "record-safe-2",
              latest_source_record_url: "https://example.org/record-safe-2",
              latest_source_pull_date: "2026-04-29T14:00:00Z"
            }
          ]
        }
      }
    });

    expect(rendered.body).toContain("Unsafe JS Source");
    expect(rendered.body).toContain("Malformed Source");
    expect(rendered.body).not.toContain('href="javascript:alert(1)"');
    expect(rendered.body).not.toContain('href="not a url"');
    expect(rendered.body).not.toMatch(/<a[^>]*>\s*Unsafe JS Source\s*<\/a>/);
    expect(rendered.body).not.toMatch(/<a[^>]*>\s*Malformed Source\s*<\/a>/);
    expect(rendered.body).toMatch(/<td>(?:(?!<a).)*Unsafe JS Source(?:(?!<a).)*<\/td>/s);
    expect(rendered.body).toMatch(/<td>(?:(?!<a).)*Malformed Source(?:(?!<a).)*<\/td>/s);
  });

  it("does not render source links that would expose embedded credentials", () => {
    const rendered = render(DataSourcesPage, {
      props: {
        data: {
          dataSources: [
            {
              data_source_id: "99999999-9999-4999-8999-999999999999",
              domain: "campaign_finance",
              jurisdiction: "state/nc",
              name: "Credentialed Source",
              source_url: "https://alice:secret@example.org/source",
              update_frequency: "daily",
              last_pull_at: "2026-04-29T16:00:00Z",
              last_pull_status: "success",
              record_count: 18,
              latest_source_record_id: "aaaaaaaa-9999-4999-8999-aaaaaaaaaaaa",
              latest_source_record_key: "credentialed-record",
              latest_source_record_url: "https://example.org/record-safe",
              latest_source_pull_date: "2026-04-29T15:00:00Z"
            }
          ]
        }
      }
    });

    expect(rendered.body).toContain("Credentialed Source");
    expect(rendered.body).not.toContain("alice:secret@example.org");
    expect(rendered.body).not.toMatch(/<a[^>]*>\s*Credentialed Source\s*<\/a>/);
    expect(rendered.body).toMatch(/<td>(?:(?!<a).)*Credentialed Source(?:(?!<a).)*<\/td>/s);
  });
});
