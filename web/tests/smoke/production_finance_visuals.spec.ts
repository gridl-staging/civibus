import { expect, test } from "playwright/test";
import type { Locator, Page } from "playwright";

import releaseTargets from "./production_release_targets.json" with { type: "json" };
import {
  BAR_SERIES_MARK_SELECTOR,
  capturePageLoadErrors,
  chartRegion,
  escapeRegExp,
  expectAxisFormatMatchesDeclaredUnit,
  expectHtmlBarListRenderIfPlotted,
  expectNoBackendFailureStates,
  expectNoChartFrameOverflow,
  expectNoHorizontalOverflow,
  expectNoMaterialNearBlackOverlay,
  expectNoOpaqueNearBlackPaints,
  expectRealChartRender,
  expectTickLabelsInsidePlotBox,
  sampleVisibleRectPaints
} from "./smoke-helpers";

// Post-deploy visual smoke for a LIVE deployment (SMOKE_MODE=production +
// SMOKE_BASE_URL). Read-only by design: no seeding, no fixture backend. It
// pins the person-money release target and the explicit 2024 cycle scope, but
// keeps every value assertion structural (a real currency figure OR a truthful
// no-data state) so it never breaks when production data drifts.
const isProductionSmokeMode = (process.env.SMOKE_MODE ?? "local") === "production";

const RELEASE_PERSON_ID = releaseTargets.finance_visual_person_id;
const RELEASE_PERSON_NAME = releaseTargets.finance_visual_person_name;
const RELEASE_PERSON_PATH = releaseTargets.finance_visual_person_path;
const SELECTED_CYCLE = "2024";
const SELECTED_CYCLE_COPY = `${SELECTED_CYCLE} cycle`;
const PRIOR_CYCLE_COPY = "2026 cycle";
const MONEY_AT_GLANCE_REGION = "Money at a glance";
const CAMPAIGN_FINANCE_HEADING = "Campaign finance";
const CURRENCY_FIGURE = /\$[\d,]+\.\d{2}/;
const NONZERO_CURRENCY_FIGURE = /\$(?!0\.00)(?:\d{1,3}(?:,\d{3})+|[1-9]\d*)\.\d{2}/;
// "has not loaded" is the not-loaded selected-cycle copy
// (PERSON_NOT_LOADED_MESSAGE). It is an honest no-data state and must count
// as one; without it a correctly-honest page reads as having neither figures
// nor an explanation.
const TRUTHFUL_NO_DATA =
  /not available|unavailable|not available yet|not loaded yet|has not loaded|no .* available/i;
const CHART_FRAME_STATE_COPY =
  /not loaded|not available|unavailable|no .* loaded|no .* reported|do not reconcile|table-only|required before rendering/i;
const COVERAGE_DATE = /\d{4}-\d{2}-\d{2}/;
const EXACT_FEC_SOURCE =
  /^FEC (?:Schedule A itemized individual contributions|candidate and committee summaries|Schedule E independent expenditures)$/;

// SVG chart frames only. HTML bar lists have no aria-labelled svg section, so
// they are asserted separately by their stable frame testIds.
const FINANCE_CHART_FRAMES = [
  {
    title: "Itemized individual contributions by month",
    chartLabel: "Monthly contribution columns"
  },
  {
    title: "Geography",
    chartLabel: "Geography dollar share by contributor location"
  }
] as const;
const HTML_BAR_LIST_FRAME_TEST_IDS = [
  "person-receipt-composition",
  "person-size-buckets"
] as const;
const OUTSIDE_SPENDING_CHART_LABEL = "Zero-centered support and oppose spending comparison";
const OUTSIDE_SPENDING_CHART_FRAME = {
  title: "Outside spending",
  chartLabel: OUTSIDE_SPENDING_CHART_LABEL
} as const;

const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 1000 },
  { name: "mobile", width: 390, height: 1100 }
] as const;

test.describe("production person finance visuals (read-only)", () => {
  test.skip(!isProductionSmokeMode, "production-mode only — set SMOKE_MODE=production and SMOKE_BASE_URL");

  test("release target renders nonzero money values on Congress and person pages", async ({
    page
  }: {
    page: Page;
  }) => {
    const pageLoadErrors = capturePageLoadErrors(page);

    expect(RELEASE_PERSON_PATH).toBe(`/person/${RELEASE_PERSON_ID}`);
    await expectCongressReleaseTargetRendersMoney(page);
    await expectPersonReleaseTargetRendersMoney(page);

    await pageLoadErrors.assertNoErrors();
  });

  test("selecting the 2024 cycle scopes the money module and clears the prior-cycle copy", async ({
    page
  }: {
    page: Page;
  }) => {
    const pageLoadErrors = capturePageLoadErrors(page);

    // Baseline: the default person page renders the finance panel at all.
    await page.goto(RELEASE_PERSON_PATH);
    await expect(page.getByRole("heading", { name: CAMPAIGN_FINANCE_HEADING })).toBeVisible({
      timeout: 20_000
    });

    // No cycle in the URL means the backend-selected path, which is the one that opts into
    // person-money-bundle's fallback. Every other assertion in this file is deliberately
    // drift-tolerant — TRUTHFUL_NO_DATA even matches the word "unavailable" — so a total
    // money outage would otherwise be scored as an honest no-data page and pass the gate.
    // This is the only assertion here that separates "no data" from "backend broken".
    await expectNoBackendFailureStates(page);

    // Act like a reader following the explicit 2024 cycle URL.
    await page.goto(`${RELEASE_PERSON_PATH}?cycle=${SELECTED_CYCLE}`);
    await expect(page).toHaveURL(new RegExp(`${RELEASE_PERSON_PATH}\\?cycle=${SELECTED_CYCLE}$`));

    const moneyAtGlance = page.getByRole("region", { name: MONEY_AT_GLANCE_REGION });
    await expect(moneyAtGlance).toBeVisible({ timeout: 20_000 });
    await expect(moneyAtGlance.getByText(SELECTED_CYCLE_COPY, { exact: true })).toBeVisible();
    await expect(
      moneyAtGlance.getByRole("link", { name: SELECTED_CYCLE, exact: true })
    ).toHaveAttribute("aria-current", "page");
    // The selected-cycle module must not keep any 2026 copy after the switch.
    await expect(moneyAtGlance.getByText(PRIOR_CYCLE_COPY)).toHaveCount(0);

    await pageLoadErrors.assertNoErrors();
  });

  for (const viewport of VIEWPORTS) {
    test(`person finance visuals stay honest and bounded at ${viewport.name} width`, async ({
      page
    }: {
      page: Page;
    }) => {
      const pageLoadErrors = capturePageLoadErrors(page);
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto(`${RELEASE_PERSON_PATH}?cycle=${SELECTED_CYCLE}`);

      await expect(page.getByRole("heading", { name: CAMPAIGN_FINANCE_HEADING })).toBeVisible({
        timeout: 20_000
      });
      await expectSelectedCycleScope(page);
      await expectRealFigureOrTruthfulNoData(page);
      await expectRenderedFinanceChartsAreHonest(page);
      await expectDisclosureKeyboardReachable(page);
      await expectOutsideSpendingLabelsWhenPresent(page);

      await expectNoHorizontalOverflow(page);
      await expectNoMaterialNearBlackOverlay(page);
      await pageLoadErrors.assertNoErrors();
    });
  }
});

async function expectCongressReleaseTargetRendersMoney(page: Page): Promise<void> {
  await page.goto(`/congress?search=${encodeURIComponent(RELEASE_PERSON_NAME)}`);
  // The congress directory labels each row's money summary with an aria-label rather than a
  // landmark region: a directory can list up to 543 members, and one region landmark per row
  // would flood assistive-tech landmark navigation. Locate by accessible name, not region role.
  const releaseTargetMoney = page.locator(`[aria-label="Money summary for ${RELEASE_PERSON_NAME}"]`);
  await expect(releaseTargetMoney).toBeVisible({ timeout: 20_000 });
  await expectNonzeroMoneyValue(releaseTargetMoney);
}

async function expectPersonReleaseTargetRendersMoney(page: Page): Promise<void> {
  // Use the person's default (latest-cycle) view for the nonzero-money assertion: a pinned
  // release target may legitimately have no receipts in an arbitrary historical cycle (e.g. an
  // appointed senator with only current-cycle federal money), which would make a cycle-pinned
  // check flap on data drift. The explicit 2024-cycle scoping is covered by the cycle-scope test.
  await page.goto(RELEASE_PERSON_PATH);
  await expect(page.getByRole("heading", { name: CAMPAIGN_FINANCE_HEADING })).toBeVisible({
    timeout: 20_000
  });
  const moneyAtGlance = page.getByRole("region", { name: MONEY_AT_GLANCE_REGION });
  await expect(moneyAtGlance).toBeVisible({ timeout: 20_000 });
  await expectNonzeroMoneyValue(moneyAtGlance);
}

async function expectNonzeroMoneyValue(region: Locator): Promise<void> {
  await expect(region.getByText(NONZERO_CURRENCY_FIGURE).first()).toBeVisible({ timeout: 20_000 });
}

async function expectSelectedCycleScope(page: Page): Promise<void> {
  const moneyAtGlance = page.getByRole("region", { name: MONEY_AT_GLANCE_REGION });
  await expect(moneyAtGlance).toBeVisible({ timeout: 20_000 });
  await expect(moneyAtGlance.getByText(SELECTED_CYCLE_COPY, { exact: true })).toBeVisible();

  // Two legitimate shapes for a re-scoped module, and the assertion has to know
  // both. The claim under test is that switching cycles actually re-scoped the
  // panel, which the absence of prior-cycle copy proves either way.
  //
  // Until 2026-08-18 this probe required a coverage-through date unconditionally.
  // That silently pinned the defect civibus-c4t describes: a cycle with NO loaded
  // evidence still rendered a coverage date and $0.00 figures, asserting coverage
  // Civibus does not have. A date is evidence about loaded data, so it can only be
  // required when there is loaded data.
  const notLoadedPanel = page.getByTestId("person-money-not-loaded");
  if ((await notLoadedPanel.count()) > 0) {
    // Stricter than the loaded branch, deliberately: no dollar figure of any
    // kind may appear, and the state must say why rather than just going blank.
    await expect(moneyAtGlance.getByText(CURRENCY_FIGURE)).toHaveCount(0);
    await expect(moneyAtGlance.getByText(TRUTHFUL_NO_DATA).first()).toBeVisible();
  } else {
    await expect(moneyAtGlance.getByText(COVERAGE_DATE).first()).toBeVisible();
  }

  await expect(moneyAtGlance.getByText(PRIOR_CYCLE_COPY)).toHaveCount(0);
}

async function expectRealFigureOrTruthfulNoData(page: Page): Promise<void> {
  const moneyAtGlance = page.getByRole("region", { name: MONEY_AT_GLANCE_REGION });
  const figureCount = await moneyAtGlance.getByText(CURRENCY_FIGURE).count();
  const noDataCount = await moneyAtGlance.getByText(TRUTHFUL_NO_DATA).count();
  expect(figureCount + noDataCount).toBeGreaterThan(0);
}

async function expectRenderedFinanceChartsAreHonest(page: Page): Promise<void> {
  const renderedCharts = await collectRenderedFinanceCharts(page, FINANCE_CHART_FRAMES);

  const plottedHtmlBarFrames: Locator[] = [];
  for (const testId of HTML_BAR_LIST_FRAME_TEST_IDS) {
    const frame = page.getByTestId(testId);
    if (await expectHtmlBarListRenderIfPlotted(frame)) {
      plottedHtmlBarFrames.push(frame);
    }
  }
  if (plottedHtmlBarFrames.length > 0) {
    await expectChartSourceLinksKeyboardReachable(plottedHtmlBarFrames);
  }

  if (renderedCharts.length === 0 && plottedHtmlBarFrames.length === 0) {
    // The invariant is "the reader is told why there is no chart", not "a chart
    // frame is the thing that tells them". When the selected cycle has no loaded
    // evidence, the Money at a glance panel says so directly and prominently,
    // and the receipt-composition frame that used to carry that message is
    // deliberately not rendered — building it would mean building it from money
    // values that are placeholders for evidence never loaded.
    //
    // This branch is not a relaxation: it requires the not-loaded panel to be
    // present AND visible, so a page that simply rendered nothing still fails.
    const notLoadedPanel = page.getByTestId("person-money-not-loaded");
    if ((await notLoadedPanel.count()) > 0) {
      await expect(notLoadedPanel.first()).toBeVisible();
      await expect(notLoadedPanel.first().getByText(TRUTHFUL_NO_DATA).first()).toBeVisible();
      return;
    }
    await expectFinanceChartNoDataState(page);
    return;
  }

  // Guarded: the html-bars module can be the only plotted chart, in which case
  // there are no svg regions to sample and the geometry oracles have no subject.
  if (renderedCharts.length > 0) {
    const chartRegions = renderedCharts.map((chart) => chart.chart);
    const chartFrames = renderedCharts.map((chart) => chart.frame);
    await expectNoOpaqueNearBlackPaints(chartRegions);
    await expectTickLabelsInsidePlotBox(chartRegions);
    await expectAxisFormatMatchesDeclaredUnit(chartRegions);
    await expectNoChartFrameOverflow(chartFrames);
    await expectChartSourceLinksKeyboardReachable(chartFrames);
  }
}

async function expectFinanceChartNoDataState(page: Page): Promise<void> {
  const chartFrames = await collectChartFrameRegions(page, FINANCE_CHART_FRAMES);
  for (const testId of HTML_BAR_LIST_FRAME_TEST_IDS) {
    const frame = page.getByTestId(testId);
    if ((await frame.count()) > 0 && (await frame.isVisible())) {
      chartFrames.push(frame);
    }
  }
  const financeChartNoDataStates: Locator[] = [];
  for (const frame of chartFrames) {
    const chartOwnedState = frame.getByText(CHART_FRAME_STATE_COPY).first();
    if ((await chartOwnedState.count()) > 0 && (await chartOwnedState.isVisible())) {
      financeChartNoDataStates.push(chartOwnedState);
    }
  }

  expect(financeChartNoDataStates.length).toBeGreaterThan(0);
  await expect(financeChartNoDataStates[0]).toBeVisible();
}

async function expectChartSourceLinksKeyboardReachable(regions: Locator[]): Promise<void> {
  for (const region of regions) {
    const sourceLink = region.getByRole("link", { name: EXACT_FEC_SOURCE }).first();
    await expect(sourceLink).toBeVisible();
    await sourceLink.focus();
    await expect(sourceLink).toBeFocused();
    await expect(sourceLink).toHaveAttribute("href", /^https:\/\/www\.fec\.gov\//);
  }
}

async function expectDisclosureKeyboardReachable(page: Page): Promise<void> {
  const disclosure = page.getByRole("button", { name: /^View chart data(?::|$)/ });
  const expectedDisclosureCount = await disclosure.count();
  if (expectedDisclosureCount === 0) {
    return;
  }

  const dataTables = page.getByRole("table").filter({
    has: page.getByRole("columnheader", { name: "Label", exact: true })
  });
  for (let index = 0; index < expectedDisclosureCount; index += 1) {
    const currentDisclosure = disclosure.nth(index);
    await currentDisclosure.focus();
    await expect(currentDisclosure).toBeFocused();
    await currentDisclosure.press("Enter");
    const openedDisclosureCount = index + 1;
    await expect(dataTables).toHaveCount(openedDisclosureCount);
    await expect(dataTables.nth(index)).toBeVisible();
  }
}

async function expectOutsideSpendingLabelsWhenPresent(page: Page): Promise<void> {
  // Three-state contract, decided by VALUES, never by label presence:
  //   nonzero totals  -> the zero-centered chart must render real bar marks;
  //   loaded_zero     -> the figure's honest words arm renders and NO marks may;
  //   not_loaded/none -> the totals <dl> never appears; nothing to assert here.
  // The pre-2026-08-21 predicate keyed on "Support total" label VISIBILITY with
  // an unwaited isVisible(), which failed twice at once: the 2024 Schedule E
  // load created the first real loaded_zero view (labels + $0.00, no marks) and
  // the gate demanded marks against it; and on slow hydration the race made the
  // whole helper silently skip -- a vacuous pass. Deploy run 32450666834 is the
  // recorded red; the desktop retry-green in the same run is the recorded race.
  const totals = await settledOutsideSpendingTotals(page);
  if (totals === null) {
    return;
  }

  const outsideFrame = await chartFrameRegion(page, OUTSIDE_SPENDING_CHART_FRAME.title);
  await expect(outsideFrame).toBeVisible({ timeout: 20_000 });

  if (!totals.hasNonzeroActivity) {
    // Measured zero: the figure states it in words, and marks would be a lie.
    await expect(
      outsideFrame.getByText(/reports \$0\.00 in support spending and \$0\.00 in oppose spending/i)
    ).toBeVisible({ timeout: 20_000 });
    expect(await outsideFrame.locator(BAR_SERIES_MARK_SELECTOR).count()).toBe(0);
    await expectChartSourceLinksKeyboardReachable([outsideFrame]);
    return;
  }

  const outsideRegion = await chartRegion(page, OUTSIDE_SPENDING_CHART_FRAME.chartLabel);
  await expect(outsideRegion).toBeVisible({ timeout: 20_000 });

  await expectRealChartRender(outsideRegion, BAR_SERIES_MARK_SELECTOR);
  const outsidePaints = await sampleVisibleRectPaints(outsideRegion);
  expect(outsidePaints.length).toBeGreaterThan(0);

  await expect(outsideRegion.getByText(/support/i).first()).toBeVisible();
  await expect(outsideRegion.getByText(/oppose/i).first()).toBeVisible();
  await expectNoOpaqueNearBlackPaints(outsideRegion);
  await expectTickLabelsInsidePlotBox([outsideRegion]);
  await expectAxisFormatMatchesDeclaredUnit([outsideRegion]);
  await expectNoChartFrameOverflow([outsideFrame]);
  await expectChartSourceLinksKeyboardReachable([outsideFrame]);
}

/**
 * Waits for the outside-spending panel to settle, then reads the totals.
 *
 * Returns null when the panel never presents a totals <dl> (the not_loaded /
 * no-candidate arms render words without "Support total"/"Oppose total"
 * definitions). Waiting on the panel heading first -- server-rendered on every
 * arm -- and then polling for the totals keeps this deterministic where the old
 * unwaited isVisible() pair raced hydration and skipped the whole assertion.
 */
async function settledOutsideSpendingTotals(
  page: Page
): Promise<{ hasNonzeroActivity: boolean } | null> {
  await expect(page.getByRole("heading", { name: "Outside spending" }).first()).toBeVisible({
    timeout: 20_000
  });

  const supportLabel = page.getByText("Support total", { exact: true }).first();
  try {
    await supportLabel.waitFor({ state: "visible", timeout: 20_000 });
  } catch {
    return null;
  }

  // dt/dd pairs: the definition follows its term inside the same row container.
  const readTotal = async (label: string): Promise<string> => {
    // eslint-disable-next-line playwright/no-raw-locators -- dt/dd totals have no role-bearing row wrapper.
    const row = page
      .locator("div", { has: page.getByText(label, { exact: true }) })
      .filter({ hasText: /\$/ })
      .first();
    return (await row.textContent()) ?? "";
  };

  const supportText = await readTotal("Support total");
  const opposeText = await readTotal("Oppose total");
  const nonzero = (text: string): boolean => {
    const match = text.match(/\$([\d,]+\.\d{2})/);
    return match !== null && Number(match[1].replace(/,/g, "")) > 0;
  };

  return { hasNonzeroActivity: nonzero(supportText) || nonzero(opposeText) };
}

type FinanceChartFrame = {
  title: string;
  chartLabel: string;
};

type RenderedFinanceChart = {
  frame: Locator;
  chart: Locator;
};

async function chartFrameRegion(page: Page, title: string): Promise<Locator> {
  return page
    .getByRole("figure", { name: new RegExp(`^${escapeRegExp(title)}(?:\\s|$)`, "i") })
    .first();
}

async function collectChartFrameRegions(
  page: Page,
  frames: readonly FinanceChartFrame[]
): Promise<Locator[]> {
  const regions: Locator[] = [];
  for (const frame of frames) {
    const region = await chartFrameRegion(page, frame.title);
    if ((await region.count()) > 0 && (await region.isVisible())) {
      regions.push(region);
    }
  }
  return regions;
}

async function collectRenderedFinanceCharts(
  page: Page,
  frames: readonly FinanceChartFrame[]
): Promise<RenderedFinanceChart[]> {
  const regions: RenderedFinanceChart[] = [];
  for (const frame of frames) {
    const chart = await chartRegion(page, frame.chartLabel);
    if ((await chart.count()) === 0 || !(await chart.isVisible())) {
      continue;
    }
    const figureRegion = await chartFrameRegion(page, frame.title);
    if ((await figureRegion.count()) === 0 || !(await figureRegion.isVisible())) {
      continue;
    }
    await expectRealChartRender(chart, BAR_SERIES_MARK_SELECTOR);
    regions.push({ frame: figureRegion, chart });
  }
  return regions;
}
