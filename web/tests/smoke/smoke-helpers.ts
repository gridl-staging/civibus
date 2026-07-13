/** Shared browser-smoke assertions for SEO, navigation, and provenance UI. */
import { expect } from "playwright/test";

/**
 * Shared SEO head-tag assertions. Verifies Open Graph + Twitter + canonical
 * tags and the expected JSON-LD script count against route fixture metadata.
 */
export async function assertSeoHead(
  page: any,
  opts: { title: string; description: string; ogType: string; jsonLdCount?: number }
) {
  const ogTitle = page.locator('meta[property="og:title"]');
  const ogDescription = page.locator('meta[property="og:description"]');
  const ogType = page.locator('meta[property="og:type"]');
  const ogUrl = page.locator('meta[property="og:url"]');
  const ogImage = page.locator('meta[property="og:image"]');
  const canonical = page.locator('link[rel="canonical"]');
  const ogSiteName = page.locator('meta[property="og:site_name"]');
  const twitterCard = page.locator('meta[name="twitter:card"]');
  const twitterTitle = page.locator('meta[name="twitter:title"]');
  const twitterDescription = page.locator('meta[name="twitter:description"]');
  const twitterImage = page.locator('meta[name="twitter:image"]');
  const jsonLd = page.locator('script[type="application/ld+json"]');

  await expect(ogTitle).toHaveCount(1);
  await expect(ogTitle).toHaveAttribute("content", opts.title);

  await expect(ogDescription).toHaveCount(1);
  await expect(ogDescription).toHaveAttribute(
    "content",
    opts.description
  );

  await expect(ogType).toHaveCount(1);
  await expect(ogType).toHaveAttribute("content", opts.ogType);

  const currentUrl = page.url();
  const expectedSocialImageUrl = new URL("/og-default.png", currentUrl).href;
  await expect(ogUrl).toHaveCount(1);
  await expect(ogUrl).toHaveAttribute("content", currentUrl);
  await expect(ogImage).toHaveCount(1);
  await expect(ogImage).toHaveAttribute("content", expectedSocialImageUrl);

  await expect(canonical).toHaveCount(1);
  await expect(canonical).toHaveAttribute("href", currentUrl);

  await expect(twitterCard).toHaveCount(1);
  await expect(twitterCard).toHaveAttribute("content", "summary_large_image");
  await expect(twitterTitle).toHaveCount(1);
  await expect(twitterTitle).toHaveAttribute("content", opts.title);
  await expect(twitterDescription).toHaveCount(1);
  await expect(twitterDescription).toHaveAttribute("content", opts.description);
  await expect(twitterImage).toHaveCount(1);
  await expect(twitterImage).toHaveAttribute("content", expectedSocialImageUrl);

  await expect(jsonLd).toHaveCount(opts.jsonLdCount ?? 1);
  if ((opts.jsonLdCount ?? 1) > 0) {
    const jsonLdContent = await jsonLd.first().textContent();
    expect(jsonLdContent).toContain('"@context":"https://schema.org"');
  }

  // og:site_name lives in app.html — assert it on every visited page
  await expect(ogSiteName).toHaveCount(1);
  await expect(ogSiteName).toHaveAttribute("content", "Civibus");
}

/** Asserts the intentionally minimal head tags for the `/search` route. */
export async function assertSearchHead(page: any, opts: { title: string; description: string }) {
  await expect(page).toHaveTitle(opts.title);
  await expect(page.locator('meta[name="description"]')).toHaveCount(1);
  await expect(page.locator('meta[name="description"]')).toHaveAttribute("content", opts.description);

  await expect(page.locator('meta[property="og:title"]')).toHaveCount(0);
  await expect(page.locator('meta[property="og:description"]')).toHaveCount(0);
  await expect(page.locator('meta[property="og:type"]')).toHaveCount(0);
  await expect(page.locator('meta[property="og:url"]')).toHaveCount(0);
  await expect(page.locator('meta[property="og:image"]')).toHaveCount(0);
  await expect(page.locator('meta[name="twitter:card"]')).toHaveCount(0);
  await expect(page.locator('meta[name="twitter:title"]')).toHaveCount(0);
  await expect(page.locator('meta[name="twitter:description"]')).toHaveCount(0);
  await expect(page.locator('meta[name="twitter:image"]')).toHaveCount(0);
  await expect(page.locator('link[rel="canonical"]')).toHaveCount(0);
  await expect(page.locator('script[type="application/ld+json"]')).toHaveCount(0);

  await expect(page.locator('meta[property="og:site_name"]')).toHaveCount(1);
  await expect(page.locator('meta[property="og:site_name"]')).toHaveAttribute("content", "Civibus");
}

export async function assertBreadcrumbNav(page: any) {
  const breadcrumbNav = page.getByRole("navigation", { name: "Breadcrumb" });
  await expect(breadcrumbNav).toBeVisible();
  await expect(breadcrumbNav.getByRole("link", { name: "Home" })).toHaveAttribute("href", "/");
}

export async function assertBreadcrumbJsonLd(page: any) {
  const jsonLdEl = page.locator('script[type="application/ld+json"]');
  const jsonLdContent = await jsonLdEl.first().textContent();
  expect(jsonLdContent).toContain('"BreadcrumbList"');
}

export async function assertSourceRecordLink(page: any, href: string) {
  await expect(page.getByRole("link", { name: "View source record" })).toHaveAttribute("href", href);
}

export async function assertPrimaryNavLink(page: any, label: string) {
  await expect(page.getByLabel("Primary").getByRole("link", { name: label, exact: true })).toBeVisible();
}

export async function assertPrimaryNavTapTargetMinHeight(page: any, label: string) {
  const link = page.getByLabel("Primary").getByRole("link", { name: label, exact: true });
  await expect(link).toBeVisible();
  await expect(link).toHaveCSS("min-height", "44px");
}

/**
 */
export function capturePageLoadErrors(page: any) {
  const errors: string[] = [];

  page.on("pageerror", (error: Error) => {
    errors.push(`pageerror: ${error.message}`);
  });
  page.on("console", (message: any) => {
    if (message.type() === "error") {
      errors.push(`console.error: ${message.text()}`);
    }
  });

  return {
    async assertNoErrors() {
      await expect(errors).toEqual([]);
    }
  };
}
