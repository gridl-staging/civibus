/** Shared browser-smoke assertions for SEO, navigation, and provenance UI. */
import { expect } from "playwright/test";
import type { Locator, Page } from "playwright";

const NEAR_BLACK_RGB_CHANNEL_MAX = 24;
const OPAQUE_ALPHA_MIN = 0.95;

export const LINE_SERIES_MARK_SELECTOR = "svg path.lc-path";
export const BAR_SERIES_MARK_SELECTOR = "svg rect";

// Repo-wide copy convention for a panel whose backend call FAILED, as opposed to a panel
// whose data is legitimately absent. Rendered inline by the {:catch} arms of
// src/lib/entity-detail/DetailPage.svelte and src/lib/campaign-finance-detail/DetailPage.svelte
// ("Contribution insights are temporarily unavailable.", "Candidate metrics are temporarily
// unavailable.", …), and by the temporarily_unavailable empty-state message that
// person-money-bundle.ts's fallback produces when a money call rejects.
//
// Matched as a family pattern rather than an imported constant because the copy is authored
// inline per panel; this mirrors how production_finance_visuals.spec.ts already pins its
// TRUTHFUL_NO_DATA / CHART_FRAME_STATE_COPY families.
//
// Why this exists: these states are deliberately calm so real users see graceful
// degradation instead of a stack trace. The cost is that a total backend outage looks
// almost exactly like an honest "no data yet" page — and TRUTHFUL_NO_DATA in
// production_finance_visuals.spec.ts matches the word "unavailable", so the production gate
// scores an outage as a PASS. A live deployment must never show this family: it always means
// the API failed, never that the data is merely absent.
export const BACKEND_FAILURE_STATE_COPY = /temporarily unavailable/i;

/**
 * Assert no panel on the current page is showing a backend-failure state.
 *
 * Only meaningful when the caller has already proven the page rendered (e.g. asserted a
 * heading is visible). On its own, absence of the copy would also be satisfied by a page
 * that failed to render at all.
 */
export async function expectNoBackendFailureStates(page: Page): Promise<void> {
  // Settle first. The money panels stream in via {#await}, and a negative assertion never
  // waits for content to arrive — so asserting the copy's absence straight away passes
  // while the panels are still pending. Verified the hard way: without this line, a person
  // page whose contribution-insights call returns 503 scored a PASS.
  //
  // SkeletonPanel marks each pending panel aria-busy, so zero busy panels means every
  // {#await} has resolved to either data or its {:catch}. toHaveCount auto-retries, which
  // is what makes this a wait rather than a sample.
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0, { timeout: 20_000 });
  await expect(page.getByText(BACKEND_FAILURE_STATE_COPY)).toHaveCount(0);
}

// National party committees (the four Hill committees + RNC/DNC). Their receipts
// are party money, not a candidate's own, and must never appear in a member's
// "Linked committees" table. Summing a party committee's receipts into a
// member's total inflated the /congress money-sorted #1 entry ~23x (a senator
// shown at ~$150M against a real ~$6.5M, because the NRSC's ~$142M was counted
// as his). Matched by name family (like BACKEND_FAILURE_STATE_COPY) rather than
// an imported constant, since committee names are authored upstream at FEC.
export const PARTY_COMMITTEE_NAME_PATTERN =
  /\bNRSC\b|\bDSCC\b|\bNRCC\b|\bDCCC\b|\bRNC\b|\bDNC\b|NATIONAL REPUBLICAN SENATORIAL|DEMOCRATIC SENATORIAL CAMPAIGN|NATIONAL REPUBLICAN CONGRESSIONAL|DEMOCRATIC CONGRESSIONAL CAMPAIGN|REPUBLICAN NATIONAL COMMITTEE|DEMOCRATIC NATIONAL COMMITTEE/i;

/**
 * Money-correctness guard: the linked-committees table on a member's person page
 * must list only the member's own committees, never a national party committee.
 *
 * Deterministic value correctness across all three candidate-money query owners
 * is owned by the api known-answer test
 * `test_candidate_money_excludes_party_and_jfc_committees`; this is a live-prod
 * spot check on the flagship #1 surface, robust to fundraising magnitude (a real
 * presidential principal committee can rival a party committee's size, so a
 * value ceiling cannot tell them apart — the committee identity can). The table
 * only renders when the member has authorized committees (empty/unavailable
 * states show a banner instead), so this is a no-op when absent; pair it with a
 * prior `expectNoBackendFailureStates` so an outage cannot make it pass vacuously.
 */
export async function expectNoPartyCommitteeInLinkedCommittees(page: Page): Promise<void> {
  // Scope to the linked-committees table and assert no cell names a party
  // committee. getByText auto-waits (so a streamed row can't slip past), and
  // toHaveCount(0) is a no-op when the table is absent -- a member with no
  // authorized committees shows a banner instead of the table -- so pair this
  // with a prior expectNoBackendFailureStates to rule out an outage hiding it.
  const partyCommitteeCells = page
    .getByTestId("person-linked-committees")
    .getByText(PARTY_COMMITTEE_NAME_PATTERN);
  await expect(partyCommitteeCells).toHaveCount(0);
}

type SvgPaintSample = {
  tagName: string;
  fill: string;
  fillOpacity: string;
  stroke: string;
  strokeOpacity: string;
  opacity: string;
  boundingBox: { width: number; height: number } | null;
};

export function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function parseRgbChannels(color: string): [number, number, number] | null {
  const match = color.match(/^rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([0-9.]+))?\)$/);
  if (!match) {
    return null;
  }

  return [Number(match[1]), Number(match[2]), Number(match[3])];
}

function parseCssAlpha(value: string): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 1;
}

function parseAlpha(color: string): number {
  const colorAlpha = color.match(/^rgba?\(\d+,\s*\d+,\s*\d+,\s*([0-9.]+)\)$/);
  return Number(colorAlpha?.[1] ?? 1);
}

/**
 */
function samplePaint(sample: SvgPaintSample): {
  color: string;
  alpha: number;
} {
  if (sample.fill !== "none" && sample.fill !== "rgba(0, 0, 0, 0)") {
    return {
      color: sample.fill,
      alpha: parseAlpha(sample.fill) * parseCssAlpha(sample.fillOpacity) * parseCssAlpha(sample.opacity)
    };
  }

  return {
    color: sample.stroke,
    alpha: parseAlpha(sample.stroke) * parseCssAlpha(sample.strokeOpacity) * parseCssAlpha(sample.opacity)
  };
}

function isOpaqueNearBlack(sample: SvgPaintSample): boolean {
  const paint = samplePaint(sample);
  const channels = parseRgbChannels(paint.color);
  if (!channels) {
    return false;
  }

  const [red, green, blue] = channels;
  return (
    red <= NEAR_BLACK_RGB_CHANNEL_MAX &&
    green <= NEAR_BLACK_RGB_CHANNEL_MAX &&
    blue <= NEAR_BLACK_RGB_CHANNEL_MAX &&
    paint.alpha >= OPAQUE_ALPHA_MIN
  );
}

export async function chartRegion(page: Page, label: string | RegExp): Promise<Locator> {
  if (label instanceof RegExp) {
    return page.getByLabel(label).first();
  }

  return page.getByLabel(new RegExp(`^${escapeRegExp(label)}(?: for .*)?$`, "i")).first();
}

/**
 */
async function sampleVisibleSvgPaints(region: Locator, selector: string): Promise<SvgPaintSample[]> {
  // eslint-disable-next-line playwright/no-raw-locators -- the oracle must inspect package-rendered SVG paint internals.
  return (await region.locator(selector).evaluateAll((elements: Element[]) =>
    elements
      .map((element) => {
        const styles = window.getComputedStyle(element);
        const clientBox = element.getBoundingClientRect();
        const svgBox =
          "getBBox" in element
            ? (element as SVGGraphicsElement).getBBox()
            : { width: 0, height: 0 };
        const box =
          clientBox.width * clientBox.height > 0
            ? clientBox
            : svgBox.width * svgBox.height > 0
              ? svgBox
              : null;
        return {
          tagName: element.tagName.toLowerCase(),
          fill: styles.fill,
          fillOpacity: styles.fillOpacity,
          stroke: styles.stroke,
          strokeOpacity: styles.strokeOpacity,
          opacity: styles.opacity,
          boundingBox: box === null ? null : { width: box.width, height: box.height }
        };
      })
      .filter(
        (sample) =>
          sample.tagName === "path" ||
          (sample.boundingBox?.width ?? 0) * (sample.boundingBox?.height ?? 0) > 0
      )
  )) as SvgPaintSample[];
}

/** Returns visible SVG series paint samples so smoke tests can reject fallback-black chart fills. */
export async function sampleVisibleRectPaints(region: Locator): Promise<SvgPaintSample[]> {
  return [
    ...(await sampleVisibleSvgPaints(region, "svg rect")),
    ...(await sampleVisibleSvgPaints(region, "svg path.lc-path"))
  ];
}

export async function expectRealChartRender(region: Locator, markSelector: string): Promise<void> {
  // eslint-disable-next-line playwright/no-raw-locators -- the oracle must prove the chart package rendered an SVG.
  expect(await region.locator("svg").count()).toBeGreaterThan(0);
  expect(await region.locator(markSelector).count()).toBeGreaterThan(0);
}

export async function expectNoOpaqueNearBlackPaints(regions: Locator | Locator[]): Promise<void> {
  const regionList = Array.isArray(regions) ? regions : [regions];
  const samples = (
    await Promise.all(regionList.map((region) => sampleVisibleRectPaints(region)))
  ).flat();
  expect(samples.length).toBeGreaterThan(0);
  expect(samples.filter(isOpaqueNearBlack)).toEqual([]);
}

export async function expectNonZeroChartBox(region: Locator, markSelector: string): Promise<void> {
  const box = await region.locator(markSelector).first().boundingBox();
  expect(box?.width ?? 0).toBeGreaterThan(0);
  expect(box?.height ?? 0).toBeGreaterThan(0);
}

export async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => {
    const root = document.documentElement;
    return Math.ceil(root.scrollWidth - root.clientWidth);
  });
  expect(overflow).toBeLessThanOrEqual(1);
}

/** Asserts no chart frame or chart body scrolls beyond its own box in either axis. */
export async function expectNoChartFrameOverflow(regions: Locator[]): Promise<void> {
  for (const region of regions) {
    const overflowing = await region.evaluate((element: HTMLElement) =>
      Array.from(element.querySelectorAll(".finance-chart, .chart-wrapper__body"))
        .map((child) => ({
          scrollWidth: child.scrollWidth,
          clientWidth: child.clientWidth,
          scrollHeight: child.scrollHeight,
          clientHeight: child.clientHeight
        }))
        .filter(
          (box) =>
            Math.ceil(box.scrollWidth - box.clientWidth) > 0 ||
            Math.ceil(box.scrollHeight - box.clientHeight) > 0
        )
    );
    expect(overflowing).toEqual([]);
  }
}

/**
 * Asserts every rendered numeric axis tick stays short enough to read (never a
 * truncated/overflowing money label). Requires at least one numeric tick.
 */
export async function expectBoundedNumericTickLabels(regions: Locator[]): Promise<void> {
  for (const region of regions) {
    const numericTickLabels = await region.evaluate((element: HTMLElement) =>
      Array.from(element.querySelectorAll("svg text"))
        .map((text) => text.textContent?.trim() ?? "")
        .filter((label) => /^[−-]?\$?\d[\d,.]*(?:\.\d+)?$/.test(label))
    );
    expect(numericTickLabels.length).toBeGreaterThan(0);
    expect(numericTickLabels.every((label) => label.length <= 12)).toBe(true);
  }
}

/**
 * Fails when a fixed/sticky/absolute near-black element covers a material share
 * (>=25%) of the viewport — the signature of a broken overlay that hides content.
 */
export async function expectNoMaterialNearBlackOverlay(page: Page): Promise<void> {
  const overlays = await page.evaluate(() => {
    const nearBlack = (color: string): boolean => {
      const match = /^rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([0-9.]+))?\)$/.exec(color);
      if (match === null) {
        return false;
      }
      const alpha = Number(match[4] ?? 1);
      return Number(match[1]) <= 24 && Number(match[2]) <= 24 && Number(match[3]) <= 24 && alpha >= 0.8;
    };
    const viewportArea = window.innerWidth * window.innerHeight;
    return Array.from(document.querySelectorAll<HTMLElement>("body *"))
      .map((element) => {
        const style = window.getComputedStyle(element);
        const box = element.getBoundingClientRect();
        return {
          position: style.position,
          backgroundColor: style.backgroundColor,
          area: box.width * box.height,
          visible: box.width > 0 && box.height > 0 && style.visibility !== "hidden" && style.display !== "none"
        };
      })
      .filter(
        (sample) =>
          sample.visible &&
          ["fixed", "sticky", "absolute"].includes(sample.position) &&
          sample.area >= viewportArea * 0.25 &&
          nearBlack(sample.backgroundColor)
      );
  });
  expect(overlays).toEqual([]);
}

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
export function formatCapturedBrowserValue(value: unknown): string {
  if (value instanceof Error) {
    return value.message;
  }

  if (typeof value === "string") {
    return value;
  }

  try {
    const serialized = JSON.stringify(value);
    return serialized === undefined ? String(value) : serialized;
  } catch {
    return String(value);
  }
}

/**
 */
async function formatConsoleMessage(message: any): Promise<string> {
  const args = message.args();
  if (args.length === 0) {
    return message.text();
  }

  const values = await Promise.all(
    args.map(async (arg: any) => {
      try {
        return formatCapturedBrowserValue(await arg.jsonValue());
      } catch {
        return message.text();
      }
    })
  );
  return values.join(" ");
}

/**
 */
export function capturePageLoadErrors(page: any) {
  const errors: string[] = [];
  const pendingConsoleErrors: Promise<void>[] = [];

  page.on("pageerror", (error: unknown) => {
    errors.push(`pageerror: ${formatCapturedBrowserValue(error)}`);
  });
  page.on("console", (message: any) => {
    if (message.type() === "error") {
      pendingConsoleErrors.push(
        formatConsoleMessage(message).then((formattedMessage) => {
          errors.push(`console.error: ${formattedMessage}`);
        })
      );
    }
  });

  return {
    async assertNoErrors() {
      await Promise.all(pendingConsoleErrors);
      await expect(errors).toEqual([]);
    }
  };
}
