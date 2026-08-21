/** Shared browser-smoke assertions for SEO, navigation, and provenance UI. */
import { expect } from "playwright/test";
import type { Locator, Page } from "playwright";

const NEAR_BLACK_RGB_CHANNEL_MAX = 24;
const OPAQUE_ALPHA_MIN = 0.95;

export const LINE_SERIES_MARK_SELECTOR = "svg path.lc-path";
// layerchart draws a bar as a rounded <path class="lc-rect lc-bar lc-bars-bar">,
// NEVER as a <rect>. The only <rect> elements a bar chart emits are the
// transparent lc-tooltip-rect hit areas of its tooltip context — verified by DOM
// probe on the fixture person page (2026-08-20): 54/54 rects were
// lc-tooltip-rect with fill rgba(0,0,0,0). The previous value, "svg rect",
// therefore proved a tooltip overlay existed, never that a bar painted: with bar
// value plumbing deliberately severed (every bar y forced to NaN, path lengths
// 0), every consumer of this constant still passed. This selector goes red on
// that same breakage. civibus-d0o.
export const BAR_SERIES_MARK_SELECTOR = "svg path.lc-bar";

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
const CAMPAIGN_FINANCE_KEY_METRICS_SUCCESS_COPY = /\bTotal raised\b/i;
const CANDIDATE_KEY_FINANCIALS_SUCCESS_COPY = /\bTotal receipts\b/i;
const RENDERED_MONEY_VALUE_COPY = /\$(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?[KMB]?\b/;

export function assertNoBackendFailureText(renderedText: string): void {
  if (BACKEND_FAILURE_STATE_COPY.test(renderedText)) {
    throw new Error("Rendered content contains a backend failure state.");
  }
}

export function assertCampaignFinanceKeyMetricsTextReady(renderedText: string): void {
  assertNoBackendFailureText(renderedText);

  if (!CAMPAIGN_FINANCE_KEY_METRICS_SUCCESS_COPY.test(renderedText)) {
    throw new Error("Campaign-finance key metrics did not render loaded totals.");
  }
  if (!RENDERED_MONEY_VALUE_COPY.test(renderedText)) {
    throw new Error("Campaign-finance key metrics did not render a loaded money value.");
  }
}

export function assertCandidateKeyFinancialsTextReady(renderedText: string): void {
  assertNoBackendFailureText(renderedText);

  if (!CANDIDATE_KEY_FINANCIALS_SUCCESS_COPY.test(renderedText)) {
    throw new Error("Candidate key financials did not render loaded totals.");
  }
  if (!RENDERED_MONEY_VALUE_COPY.test(renderedText)) {
    throw new Error("Candidate key financials did not render a loaded money value.");
  }
}

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
  assertNoBackendFailureText((await page.locator("body").textContent()) ?? "");
  await expect(page.getByText(BACKEND_FAILURE_STATE_COPY)).toHaveCount(0);
}

export async function expectEarlierCycleOfficialTotalCaveat(
  caveat: Locator,
  options: {
    coverageStartDate: string;
    coverageEndDate: string;
    expectCompleteSpecCopy: boolean;
  }
): Promise<void> {
  await expect(caveat).toBeVisible({ timeout: 20_000 });
  await expect(caveat).toContainText(options.coverageStartDate);
  await expect(caveat).toContainText(options.coverageEndDate);
  await expect(caveat).toContainText(/not part of the \d{4} selected-cycle totals/i);
  await expect(caveat).not.toContainText(/career total|full campaign total/i);
  if (options.expectCompleteSpecCopy) {
    await expect(caveat).toContainText(/shown because selected-cycle activity is absent/i);
    await expect(caveat).toContainText("Official FEC candidate summary");
    await expect(caveat).toContainText("fec_weball");
  }
}

export async function expectCampaignFinanceKeyMetricsReady(
  page: Page,
  timeoutMs: number
): Promise<void> {
  const keyMetrics = page.getByTestId("key-metrics");
  await expect(keyMetrics).toBeVisible({ timeout: timeoutMs });
  await expect(keyMetrics.getByText("Total raised", { exact: true })).toBeVisible({
    timeout: timeoutMs
  });
  await expect(keyMetrics.getByText(RENDERED_MONEY_VALUE_COPY).first()).toBeVisible({
    timeout: timeoutMs
  });
  assertCampaignFinanceKeyMetricsTextReady((await keyMetrics.textContent()) ?? "");
}

export async function expectCandidateKeyFinancialsReady(
  page: Page,
  timeoutMs: number
): Promise<void> {
  const keyMetrics = page.getByTestId("key-metrics");
  await expect(keyMetrics).toBeVisible({ timeout: timeoutMs });
  await expect(keyMetrics.getByText("Total receipts", { exact: true })).toBeVisible({
    timeout: timeoutMs
  });
  await expect(keyMetrics.getByText(RENDERED_MONEY_VALUE_COPY).first()).toBeVisible({
    timeout: timeoutMs
  });
  assertCandidateKeyFinancialsTextReady((await keyMetrics.textContent()) ?? "");
}

/**
 */
export async function expectActionToVisibleContentWithinBudget({
  label,
  budgetMs,
  action,
  visibleContent
}: {
  label: string;
  budgetMs: number;
  action: () => Promise<void>;
  visibleContent: () => Promise<void>;
}): Promise<number> {
  const startedAt = performance.now();
  const actionPromise = action();
  const actionFailure = actionPromise.then(
    () => new Promise<never>(() => {}),
    (error) => Promise.reject(error)
  );

  try {
    await Promise.race([visibleContent(), actionFailure]);
    const elapsedMs = performance.now() - startedAt;
    expect(elapsedMs, `${label} action-to-visible-content`).toBeLessThan(budgetMs);
    await actionPromise;
    return elapsedMs;
  } catch (error) {
    await Promise.allSettled([actionPromise]);
    throw error;
  }
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
  pathLength: number | null;
};

export function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

const RENDERED_MONEY_PATTERN =
  /^\$(?<amount>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(?<magnitude>[KMB])?$/;
const RENDERED_MONEY_MULTIPLIERS = {
  K: 1_000,
  M: 1_000_000,
  B: 1_000_000_000
} as const;

/**
 */
export function parseRenderedMoneyLabel(label: string): number {
  const match = RENDERED_MONEY_PATTERN.exec(label.trim());
  if (!match?.groups) {
    throw new Error(`Invalid rendered money label: ${label}`);
  }

  const amount = Number(match.groups.amount.replaceAll(",", ""));
  const magnitude = match.groups.magnitude as keyof typeof RENDERED_MONEY_MULTIPLIERS | undefined;
  const multiplier = magnitude === undefined ? 1 : RENDERED_MONEY_MULTIPLIERS[magnitude];
  const dollars = amount * multiplier;

  if (!Number.isFinite(dollars)) {
    throw new Error(`Invalid rendered money label: ${label}`);
  }

  return dollars;
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
          boundingBox: box === null ? null : { width: box.width, height: box.height },
          pathLength: element instanceof SVGPathElement ? element.getTotalLength() : null
        };
      })
      .filter(
        (sample) => {
          const boundingBoxArea =
            (sample.boundingBox?.width ?? 0) * (sample.boundingBox?.height ?? 0);
          // LayerChart can emit a zero-length path for an empty plot, so tag presence alone is not paint.
          return sample.tagName === "path" ? (sample.pathLength ?? 0) > 0 : boundingBoxArea > 0;
        }
      )
  )) as SvgPaintSample[];
}

/**
 * Returns visible SVG series paint samples so smoke tests can reject fallback-black
 * chart fills.
 *
 * `svg path.lc-bar` is load-bearing and easy to lose: layerchart renders a bar as a
 * rounded <path class="lc-rect lc-bar lc-bars-bar">, NOT as a <rect>. The only
 * <rect> elements a bar chart emits are the transparent `lc-tooltip-rect` hit areas
 * in its second layout svg, so a sampler restricted to rects never looked at a
 * single bar - it sampled `rgba(0, 0, 0, 0)` hit areas and reported chart paint.
 */
export async function sampleVisibleRectPaints(region: Locator): Promise<SvgPaintSample[]> {
  return [
    ...(await sampleVisibleSvgPaints(region, "svg rect")),
    ...(await sampleVisibleSvgPaints(region, "svg path.lc-path")),
    ...(await sampleVisibleSvgPaints(region, "svg path.lc-bar"))
  ];
}

export async function expectRealChartRender(region: Locator, markSelector: string): Promise<void> {
  // eslint-disable-next-line playwright/no-raw-locators -- the oracle must prove the chart package rendered an SVG.
  await expect(region.locator("svg").first()).toBeVisible();
  await expect
    .poll(async () => (await sampleVisibleSvgPaints(region, markSelector)).length)
    .toBeGreaterThan(0);
}

// HorizontalBarChart's single-series hue. Kept equal to FINANCE_CHART_COLORS.support
// in web/src/lib/charts/finance.ts and to the hardcoded gradient hex in
// HorizontalBarChart.svelte's <style> (a Svelte style block cannot read a module
// constant, so this assertion is what holds the pairing). Change all three or none.
const HTML_BAR_LIST_FILL_HEX = "#0f766e";
const HTML_BAR_LIST_ROW_SELECTOR = ".horizontal-bars__row";
const HTML_BAR_LIST_MARK_SELECTOR = ".horizontal-bars__bar";

/**
 * Render oracle for the ranked HTML bar list that HorizontalBarChart draws
 * (civibus-3a3). The list is that component's ONLY visual encoding — until
 * 2026-08-20 it also drew the same series as a layerchart VERTICAL svg bar
 * chart, so this asserts both halves of the fix:
 *
 *  1. no `<svg>` exists anywhere in the frame (the duplicate encoding may not
 *     come back), and
 *  2. the bars actually painted: at least one row, every bar span carrying the
 *     shared-scale gradient in the single-series token, and at least one bar
 *     with a nonzero filled width.
 *
 * Each check can fail for a real defect: rows disappear if the data plumbing or
 * the CSS class is dropped, the gradient check fails if the fill breaks or the
 * hue drifts from the token, and the width check fails if the shared-scale
 * width computation regresses to all-zero.
 */
export async function expectHtmlBarListRender(region: Locator): Promise<void> {
  // eslint-disable-next-line playwright/no-raw-locators -- the oracle inspects the component's own bar markup.
  await expect(region.locator(HTML_BAR_LIST_ROW_SELECTOR).first()).toBeVisible();
  // eslint-disable-next-line playwright/no-raw-locators -- the single-encoding pin must count raw svg elements.
  await expect(region.locator("svg")).toHaveCount(0);

  const expectedFill = hexToComputedRgb(HTML_BAR_LIST_FILL_HEX);
  // eslint-disable-next-line playwright/no-raw-locators -- the oracle must read computed paint off package-free markup.
  const barPaints = await region.locator(HTML_BAR_LIST_MARK_SELECTOR).evaluateAll(
    (elements: Element[]) =>
      elements.map((element) => {
        const styles = window.getComputedStyle(element);
        const box = element.getBoundingClientRect();
        return {
          backgroundImage: styles.backgroundImage,
          filledWidth: styles.getPropertyValue("--finance-width").trim(),
          boundingBox: { width: box.width, height: box.height }
        };
      })
  );

  expect(barPaints.length, "html bar list rendered rows but no bar marks").toBeGreaterThan(0);
  for (const paint of barPaints) {
    expect(paint.backgroundImage, "bar mark lost its shared-scale gradient").toContain(
      "linear-gradient"
    );
    expect(paint.backgroundImage, "bar mark fill drifted from the single-series token").toContain(
      expectedFill
    );
    expect(paint.boundingBox.width).toBeGreaterThan(0);
    expect(paint.boundingBox.height).toBeGreaterThan(0);
  }

  const filledWidths = barPaints
    .map((paint) => Number.parseFloat(paint.filledWidth))
    .filter((width) => Number.isFinite(width) && width > 0);
  expect(filledWidths.length, "no bar carries a nonzero filled width").toBeGreaterThan(0);
}

/**
 * Production-tolerant twin of `expectHtmlBarListRender` for data-dependent
 * surfaces: a live member may truthfully have no itemized size-bucket rows, in
 * which case the frame renders its no-data state and there is nothing to
 * assert. Returns whether a plotted list was actually asserted, so a caller
 * that requires at least one render can count. The strict twin runs in the
 * fixture lane on known-present data, which is what stops this tolerance from
 * making the check vacuous.
 */
export async function expectHtmlBarListRenderIfPlotted(region: Locator): Promise<boolean> {
  if ((await region.count()) === 0 || !(await region.first().isVisible())) {
    return false;
  }
  // eslint-disable-next-line playwright/no-raw-locators -- presence probe for the component's own bar markup.
  if ((await region.locator(HTML_BAR_LIST_ROW_SELECTOR).count()) === 0) {
    return false;
  }
  await expectHtmlBarListRender(region);
  return true;
}

export async function expectNoOpaqueNearBlackPaints(regions: Locator | Locator[]): Promise<void> {
  const regionList = Array.isArray(regions) ? regions : [regions];
  const samples = (
    await Promise.all(regionList.map((region) => sampleVisibleRectPaints(region)))
  ).flat();
  expect(samples.length).toBeGreaterThan(0);
  expect(samples.filter(isOpaqueNearBlack)).toEqual([]);
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
 * A rendered axis tick label may not extend past the edge of its own `<svg>` by
 * more than this many CSS pixels.
 *
 * The tolerance is deliberately sub-pixel rather than a comfortable 2px. The
 * clipped y-axis this guard replaces overflowed by 28-34px against live
 * production money values but by only ~1px against the small fixture values, so
 * a 2px tolerance is green on every local run and still ships the production
 * defect - the exact local-green / production-red shape behind three rollbacks
 * on this surface. Anything above zero is a real escape; 0.5px only absorbs
 * sub-pixel rounding in getBoundingClientRect.
 */
const TICK_LABEL_ESCAPE_TOLERANCE_PX = 0.5;

/** `#0f766e` -> `rgb(15, 118, 110)`, the form getComputedStyle returns a fill in. */
function hexToComputedRgb(hexColor: string): string {
  const channels = hexColor.replace("#", "");
  const [red, green, blue] = [0, 2, 4].map((offset) =>
    Number.parseInt(channels.slice(offset, offset + 2), 16)
  );
  return `rgb(${red}, ${green}, ${blue})`;
}

/**
 * Tick text a chart's value axis is allowed to render, keyed by the unit the
 * chart's `ChartFrame` declares via `data-unit`.
 *
 * The minus sign is matched in both forms: d3's default numeric formatter emits
 * U+2212 MINUS SIGN, the repo's own currency formatters emit ASCII hyphen.
 * Owner of the rule: `docs/reference/ui_chart_encoding.md` §3.
 */
const AXIS_TICK_TEXT_BY_DECLARED_UNIT: Record<string, RegExp> = {
  dollars: /^[−-]?\$\d[\d,]*(?:\.\d+)?[KMB]?$/,
  percent: /^[−-]?\d[\d,]*(?:\.\d+)?%$/,
  count: /^[−-]?\d[\d,]*$/,
  reported_transactions: /^[−-]?\d[\d,]*$/
};

/**
 * Asserts every rendered axis tick label sits inside the chart's own plot box.
 *
 * This replaces a guard that could not fail: it read tick *text* out of the DOM and
 * asserted each label was at most 12 characters, so the 9-character "1,000,000"
 * that was hanging 34px into the neighbouring column scored a pass. Character count
 * is not a rendering measurement. This one compares the label's real
 * getBoundingClientRect against the svg's, which is the thing a reader sees.
 */
export async function expectTickLabelsInsidePlotBox(regions: Locator[]): Promise<void> {
  let plottedCharts = 0;

  for (const region of regions) {
    const measurement = await region.evaluate((element: HTMLElement, tolerancePx: number) => {
      // The chart's own layout svg is the first one in the region. layerchart also
      // nests one <svg> per tick label inside it and appends a second layout svg
      // for tooltip hit areas after it, so "the first svg" is the plot box.
      const svg = element.querySelector("svg");
      // A frame in the no-data or table-only state renders no plot at all. Skipping
      // it is what makes this usable against live production, where a chart
      // legitimately has nothing to draw; the caller-side plottedCharts count below
      // is what stops an all-empty page from passing vacuously.
      if (svg === null) {
        return null;
      }

      const plot = svg.getBoundingClientRect();
      const escaping: Array<{ axis: string; text: string; escapedByPx: number }> = [];
      let tickCount = 0;

      for (const axis of Array.from(svg.querySelectorAll("g.lc-axis"))) {
        for (const label of Array.from(axis.querySelectorAll("text.lc-axis-tick-label"))) {
          const box = label.getBoundingClientRect();
          if (box.width === 0 && box.height === 0) {
            continue;
          }
          tickCount += 1;
          const escapedByPx = Math.max(
            plot.left - box.left,
            box.right - plot.right,
            plot.top - box.top,
            box.bottom - plot.bottom
          );
          if (escapedByPx > tolerancePx) {
            escaping.push({
              axis: axis.getAttribute("data-placement") ?? "unknown",
              text: label.textContent?.trim() ?? "",
              escapedByPx: Number(escapedByPx.toFixed(2))
            });
          }
        }
      }

      return {
        chart: element.getAttribute("aria-label") ?? "unlabelled chart",
        tickCount,
        escaping
      };
    }, TICK_LABEL_ESCAPE_TOLERANCE_PX);

    if (measurement === null) {
      continue;
    }

    plottedCharts += 1;
    expect(
      measurement.tickCount,
      `${measurement.chart} plotted an svg but rendered no axis tick labels`
    ).toBeGreaterThan(0);
    expect(
      measurement.escaping,
      `${measurement.chart} rendered tick labels outside its own plot box`
    ).toEqual([]);
  }

  expect(plottedCharts, "no chart region rendered a plot to measure").toBeGreaterThan(0);
}

/**
 * Asserts each chart's value axis renders in the unit its frame declares.
 *
 * Derived from the frame's own `data-unit`, never from a per-chart expectation, so
 * it holds for whichever way a disagreement is resolved. The live case:
 * `GeographyShareChart` declared `unit="dollars"`, printed `formatCurrency(...)` in
 * its rows and its disclosure table, and plotted a unitless 0.0-0.5 fraction. Three
 * surfaces of one chart, three answers.
 */
export async function expectAxisFormatMatchesDeclaredUnit(regions: Locator[]): Promise<void> {
  let checkedCharts = 0;

  for (const region of regions) {
    const measurement = await region.evaluate((element: HTMLElement) => {
      const svg = element.querySelector("svg");
      if (svg === null) {
        return null;
      }
      const valueAxis = svg.querySelector('g.lc-axis[data-placement="left"]');
      return {
        chart: element.getAttribute("aria-label") ?? "unlabelled chart",
        declaredUnit: element.closest("figure.finance-chart")?.getAttribute("data-unit") ?? null,
        ticks: Array.from(valueAxis?.querySelectorAll("text.lc-axis-tick-label") ?? []).map(
          (label) => label.textContent?.trim() ?? ""
        )
      };
    });

    if (measurement === null) {
      continue;
    }

    const { declaredUnit, ticks } = measurement;
    expect(declaredUnit, `${measurement.chart} is not inside a frame declaring a unit`).not.toBeNull();

    const allowedTickText = AXIS_TICK_TEXT_BY_DECLARED_UNIT[declaredUnit as string];
    expect(
      allowedTickText,
      `no axis tick format is declared for unit "${declaredUnit}"`
    ).toBeDefined();
    expect(ticks.length, `${measurement.chart} rendered no value-axis ticks`).toBeGreaterThan(0);
    expect(
      ticks.filter((tick) => !allowedTickText.test(tick)),
      `${measurement.chart} declares unit "${declaredUnit}" but its value axis does not render in it`
    ).toEqual([]);
    checkedCharts += 1;
  }

  expect(checkedCharts, "no chart region rendered a value axis to check").toBeGreaterThan(0);
}

/**
 * Asserts hovering a chart surfaces a tooltip carrying the series label and a real
 * money value.
 *
 * Deliberately asserts tooltip CONTENT and not `pointer-events`. Asserting the CSS
 * property would assert the harness rather than the behaviour, which is the same
 * invalid-probe mistake as counting characters in a tick label. Tooltips ship with
 * layerchart (`BarChart` defaults `tooltipContext` to true) and were dark only
 * because the adapter set `pointer-events: none` on the svg.
 */
export async function expectChartTooltipOnHover(
  region: Locator,
  expected: { seriesLabel: string }
): Promise<void> {
  // Hover the band hit area, which is the element a reader's pointer actually
  // lands on: layerchart overlays the plot with one transparent `lc-tooltip-rect`
  // per band, so hovering the plot svg itself is intercepted by them. Playwright's
  // actionability check is what surfaces that — and is also what proves the
  // reachability, since a covered or pointer-events-disabled target fails here.
  // eslint-disable-next-line playwright/no-raw-locators -- package-rendered SVG hit area carrying no role of its own.
  const bandHitArea = region.locator("svg rect.lc-tooltip-rect").first();
  await expect(bandHitArea).toBeVisible();
  await bandHitArea.hover();

  // The tooltip is portaled out of the chart region, so it is located on the page.
  const tooltip = region.page().getByRole("tooltip");
  await expect(tooltip).toBeVisible();
  await expect(tooltip).toContainText(expected.seriesLabel);
  await expect(tooltip).toContainText(RENDERED_MONEY_VALUE_COPY);

  // Containment is checked HERE, with a tooltip actually open, because that is the
  // only moment it can fail. finance-visuals.spec.ts used to run the same check on
  // a page where nothing was hovered: it queried [role="tooltip"], found zero
  // elements, and asserted zero had escaped — a pass that no defect could have
  // turned red.
  const escapedTooltips = await region.page().evaluate(() =>
    Array.from(document.querySelectorAll<HTMLElement>('[role="tooltip"]'))
      .filter((element) => element.offsetParent !== null)
      .map((element) => element.getBoundingClientRect())
      .filter(
        (box) =>
          box.left < 0 ||
          box.top < 0 ||
          box.right > window.innerWidth ||
          box.bottom > window.innerHeight
      )
  );
  expect(escapedTooltips, "an open chart tooltip rendered outside the viewport").toEqual([]);
}

/**
 * Asserts a diverging chart paints its two stances in two distinct fills, and in
 * exactly the colours the surrounding HTML rows already use for the same stance.
 *
 * Before this, the whole zero-centered support/oppose plot was one series, so every
 * bar carried `color[0]` and only the bar's direction distinguished spending FOR a
 * candidate from spending AGAINST them - while the HTML rows immediately below
 * carried the stance in a coloured left border. Two encodings of one fact.
 */
export async function expectDivergingStanceFills(
  region: Locator,
  expectedHexFills: string[]
): Promise<void> {
  // Callers pass the same design tokens the components consume, so the expectation
  // has one owner; computed fills come back from the browser as rgb() triples.
  const expectedFills = expectedHexFills.map(hexToComputedRgb);

  // Scoped to the bar marks themselves. The wider paint sampler also returns the
  // transparent `lc-tooltip-rect` hit areas, which carry no encoding.
  await expect
    .poll(async () => (await sampleVisibleSvgPaints(region, "svg path.lc-bar")).length, {
      message: "diverging chart painted no series marks"
    })
    .toBeGreaterThan(0);

  const samples = await sampleVisibleSvgPaints(region, "svg path.lc-bar");
  const paintedFills = Array.from(
    new Set(samples.map((sample) => samplePaint(sample).color))
  ).sort();

  expect(paintedFills, "diverging chart did not paint its two stances distinctly").toEqual(
    [...expectedFills].sort()
  );
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

export async function assertRobotsHead(page: any, expectedContent: "noindex" | null) {
  const robots = page.locator('meta[name="robots"]');
  await expect(robots).toHaveCount(expectedContent === null ? 0 : 1);
  if (expectedContent !== null) {
    await expect(robots).toHaveAttribute("content", expectedContent);
  }
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

export async function readStructuredDataScripts(page: any): Promise<unknown[]> {
  return page.evaluate(() =>
    Array.from(document.scripts)
      .filter((script) => script.type === "application/ld+json")
      .map((script) => JSON.parse(script.textContent ?? "null"))
  );
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
