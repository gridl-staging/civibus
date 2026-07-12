import { expect, test } from "playwright/test";
import { SMOKE_CANDIDATE_NAME, SMOKE_CANDIDATE_SLUG } from "./fixtures";

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

test.describe("launch hygiene", () => {
  test("GET /sitemap.xml returns XML sitemap envelope with core URLs", async ({ page }: { page: any }) => {
    const response = (await page.goto("/sitemap.xml"))!;

    expect(response.status()).toBe(200);
    expect(response.headers()["content-type"]).toContain("xml");

    const xml = await response.text();

    expect(xml).toContain('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">');
    expect(xml).toMatch(/<loc>[^<]+<\/loc>/);

    const responseOrigin = new URL(response.url()).origin;
    expect(xml).toContain(`<loc>${responseOrigin}/candidates</loc>`);
    expect(xml).toContain(`<loc>${responseOrigin}/committees</loc>`);
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
