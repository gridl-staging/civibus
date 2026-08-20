import { expect, test } from "playwright/test";
import {
  SMOKE_CALENDAR_ROUTE_PATH,
  SMOKE_CANDIDATE_NAME,
  SMOKE_CANDIDATE_SLUG,
  SMOKE_COVERAGE_ROUTE_PATH,
  SMOKE_DATA_SOURCES_ROUTE_PATH,
  SMOKE_ELECTION_ROUTE_PATH
} from "./fixtures";

function escapeRegex(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function expectHtmlMetaContent(
  html: string,
  attr: "name" | "property",
  name: string,
  contentPattern: string
) {
  const metaPattern = new RegExp(
    `<meta(?=[^>]*${attr}="${escapeRegex(name)}")(?=[^>]*content="${contentPattern}")[^>]*>`,
    "i"
  );

  expect(html).toMatch(metaPattern);
}

function extractLocs(xml: string): string[] {
  return [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((match) => match[1]!);
}

function locPaths(xml: string): string[] {
  return extractLocs(xml).map((loc) => new URL(loc).pathname);
}

test.describe("launch hygiene", () => {
  test("GET /sitemap.xml returns XML sitemap index with a core static shard", async ({
    page
  }: {
    page: any;
  }) => {
    const response = (await page.goto("/sitemap.xml"))!;

    expect(response.status()).toBe(200);
    expect(response.headers()["content-type"]).toContain("xml");
    expect(response.headers()["cache-control"]).toBe("public, max-age=900");

    const xml = await response.text();

    expect(xml).toContain('<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">');
    expect(xml).toMatch(/<loc>[^<]+<\/loc>/);

    const responseOrigin = new URL(response.url()).origin;
    const shardLocs = extractLocs(xml);
    expect(shardLocs).toContain(`${responseOrigin}/sitemap-static.xml`);

    const staticResponse = await page.request.get("/sitemap-static.xml");
    expect(staticResponse.status()).toBe(200);
    expect(staticResponse.headers()["content-type"]).toContain("xml");
    expect(staticResponse.headers()["cache-control"]).toBe("public, max-age=900");
    const staticXml = await staticResponse.text();
    expect(staticXml).toContain('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">');
    // Exact set, deliberately: the sitemap is what search engines are told
    // exists, so an omission and an addition are both defects. The literals
    // mirror STATIC_PATHS in web/src/lib/server/sitemap.ts, which cannot be
    // imported here (it resolves $lib and $env aliases that the Node ESM spec
    // process does not). web/src/routes/sitemap.xml/server.test.ts pins the same
    // list at unit level; this assertion is the one that proves the served HTTP
    // route emits it. The trust pages below were added to STATIC_PATHS by
    // 4a1e9a278 and this expectation was not updated with them, which is the
    // staleness an exact set is supposed to catch.
    expect(new Set(locPaths(staticXml))).toEqual(
      new Set([
        "/",
        "/congress",
        "/candidates",
        "/committees",
        SMOKE_COVERAGE_ROUTE_PATH,
        SMOKE_CALENDAR_ROUTE_PATH,
        SMOKE_DATA_SOURCES_ROUTE_PATH,
        "/about",
        "/contact",
        "/privacy",
        SMOKE_ELECTION_ROUTE_PATH
      ])
    );
  });

  test("candidate detail emits non-empty OG/Twitter meta with fixture-linked values", async ({
    page
  }: {
    page: any;
  }) => {
    const response = (await page.goto(`/candidate/${SMOKE_CANDIDATE_SLUG}`))!;

    expect(response.status()).toBe(200);
    // Assert against the main document HTML so this test proves SSR output,
    // not only head tags that exist after client-side hydration finishes.
    const html = await response.text();

    expectHtmlMetaContent(
      html,
      "property",
      "og:title",
      `[^"]*${escapeRegex(SMOKE_CANDIDATE_NAME)}[^"]*`
    );
    expectHtmlMetaContent(html, "property", "og:image", `[^"]*\\S[^"]*`);
    expectHtmlMetaContent(
      html,
      "property",
      "og:url",
      `[^"]*${escapeRegex(SMOKE_CANDIDATE_SLUG)}[^"]*`
    );
    expectHtmlMetaContent(html, "name", "twitter:card", escapeRegex("summary_large_image"));
    expectHtmlMetaContent(html, "name", "twitter:image", `[^"]*\\S[^"]*`);
  });
});
