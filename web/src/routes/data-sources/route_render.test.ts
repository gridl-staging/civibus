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

const FEC_NOTICE_MARKER = 'data-testid="fec-contributor-data-use-notice"';

const FEC_NOTICE_COPY = [
  "Individual contributor information in FEC reports is public",
  "may not be sold or used to solicit contributions or for commercial purposes",
  "summarizes FEC source restrictions and is not legal advice"
] as const;

const FEC_NOTICE_LINK_HREFS = [
  "https://www.fec.gov/updates/sale-or-use-contributor-information/",
  "https://www.fec.gov/introduction-campaign-finance/how-to-research-public-records/individual-contributions/",
  "https://www.fec.gov/data/browse-data/"
] as const;

/** The static FEC notice must render exactly once and precede the registry content. */
function expectFecContributorDataUseNotice(body: string, followingContentMarker: string): void {
  expect(body.match(new RegExp(FEC_NOTICE_MARKER, "g"))).toHaveLength(1);

  const missingCopy = FEC_NOTICE_COPY.filter((copy) => !body.includes(copy));
  expect(missingCopy).toEqual([]);

  const missingLinks = FEC_NOTICE_LINK_HREFS.filter(
    (href) => !body.includes(`href="${href}" target="_blank" rel="noopener nofollow"`)
  );
  expect(missingLinks).toEqual([]);

  const followingContentIndex = body.indexOf(followingContentMarker);
  expect(followingContentIndex).toBeGreaterThan(-1);
  expect(body.indexOf(FEC_NOTICE_MARKER)).toBeLessThan(followingContentIndex);
}

describe("/data-sources route rendering", () => {
  it("renders only registry-owned data-source metadata", () => {
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
              last_pull_status: "failed",
              record_count: 10,
              latest_source_record_id: null,
              latest_source_record_key: null,
              latest_source_record_url: null,
              latest_source_pull_date: "2026-04-29T12:00:00Z"
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
    expect(rendered.body).toContain("failed");
    expect(rendered.body).toContain("2026-04-29T12:00:00Z");
    expect(rendered.body.match(/2026-04-29T12:00:00Z/g)).toHaveLength(1);
    expect(rendered.body).not.toContain("Latest source pull");
    expect(rendered.body).not.toContain("Latest source record");
    expect(rendered.body.match(/<th scope="col">/g)).toHaveLength(7);
    expectFecContributorDataUseNotice(rendered.body, "<table");
    expect(rendered.body).toContain('href="https://example.org/source" target="_blank" rel="noopener nofollow"');
    expect(rendered.body).not.toContain("noopener noreferrer");
  });

  it("renders malformed last-pull timestamps as unknown provenance", () => {
    const rendered = render(DataSourcesPage, {
      props: {
        data: {
          dataSources: [
            {
              data_source_id: "22222222-2222-4222-8222-222222222222",
              domain: "campaign_finance",
              jurisdiction: "state/pa",
              name: "PA Disclosure",
              source_url: "https://example.org/pa-source",
              update_frequency: "daily",
              last_pull_at: "not-a-timestamp",
              last_pull_status: "success",
              record_count: 12,
              latest_source_record_id: null,
              latest_source_record_key: null,
              latest_source_record_url: null,
              latest_source_pull_date: null
            }
          ]
        }
      }
    });

    expect(rendered.body).toContain("PA Disclosure");
    expect(rendered.body).not.toContain("not-a-timestamp");
    expect(rendered.body.match(/<td>unknown<\/td>/g)).toHaveLength(1);
  });

  it("renders impossible-calendar last-pull timestamps as unknown provenance", () => {
    const rendered = render(DataSourcesPage, {
      props: {
        data: {
          dataSources: [
            {
              data_source_id: "44444444-4444-4444-8444-444444444444",
              domain: "campaign_finance",
              jurisdiction: "state/mi",
              name: "MI Disclosure",
              source_url: "https://example.org/mi-source",
              update_frequency: "daily",
              last_pull_at: "2026-02-30T12:00:00Z",
              last_pull_status: "success",
              record_count: 15,
              latest_source_record_id: null,
              latest_source_record_key: null,
              latest_source_record_url: null,
              latest_source_pull_date: null
            }
          ]
        }
      }
    });

    expect(rendered.body).toContain("MI Disclosure");
    expect(rendered.body).not.toContain("2026-02-30T12:00:00Z");
    expect(rendered.body.match(/<td>unknown<\/td>/g)).toHaveLength(1);
  });

  it("renders future last-pull timestamps as unknown provenance", () => {
    const rendered = render(DataSourcesPage, {
      props: {
        data: {
          dataSources: [
            {
              data_source_id: "33333333-3333-4333-8333-333333333333",
              domain: "campaign_finance",
              jurisdiction: "state/ga",
              name: "GA Disclosure",
              source_url: "https://example.org/ga-source",
              update_frequency: "daily",
              last_pull_at: "9999-12-31T23:59:59Z",
              last_pull_status: "success",
              record_count: 13,
              latest_source_record_id: null,
              latest_source_record_key: null,
              latest_source_record_url: null,
              latest_source_pull_date: null
            }
          ]
        }
      }
    });

    expect(rendered.body).toContain("GA Disclosure");
    expect(rendered.body).not.toContain("9999-12-31T23:59:59Z");
    expect(rendered.body.match(/<td>unknown<\/td>/g)).toHaveLength(1);
  });

  it("renders empty-state copy when no rows are present", () => {
    const rendered = render(DataSourcesPage, {
      props: {
        data: { dataSources: [] }
      }
    });

    expect(rendered.body).toContain("Data sources");
    expect(rendered.body).toContain("No runtime data-source rows are available right now.");
    expectFecContributorDataUseNotice(
      rendered.body,
      "No runtime data-source rows are available right now."
    );
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
