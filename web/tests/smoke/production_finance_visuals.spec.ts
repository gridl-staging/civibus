import { expect, test } from "playwright/test";
import type { Locator, Page } from "playwright";

import {
  capturePageLoadErrors,
  chartRegion,
  escapeRegExp,
  expectBoundedNumericTickLabels,
  expectNoBackendFailureStates,
  expectNoChartFrameOverflow,
  expectNoHorizontalOverflow,
  expectNoMaterialNearBlackOverlay,
  expectNoOpaqueNearBlackPaints,
  sampleVisibleRectPaints
} from "./smoke-helpers";

// Post-deploy visual smoke for a LIVE deployment (SMOKE_MODE=production +
// SMOKE_BASE_URL). Read-only by design: no seeding, no fixture backend. It
// pins the person-money release target and the explicit 2024 cycle scope, but
// keeps every value assertion structural (a real currency figure OR a truthful
// no-data state) so it never breaks when production data drifts.
const isProductionSmokeMode = (process.env.SMOKE_MODE ?? "local") === "production";

const RELEASE_PERSON_ID = "d2944415-3ec6-47b0-b44f-2cd28ddfbc0b";
const RELEASE_PERSON_PATH = `/person/${RELEASE_PERSON_ID}`;
const SELECTED_CYCLE = "2024";
const SELECTED_CYCLE_COPY = `${SELECTED_CYCLE} cycle`;
const PRIOR_CYCLE_COPY = "2026 cycle";
const MONEY_AT_GLANCE_REGION = "Money at a glance";
const CAMPAIGN_FINANCE_HEADING = "Campaign finance";
const CURRENCY_FIGURE = /\$[\d,]+\.\d{2}/;
const TRUTHFUL_NO_DATA = /not available|unavailable|not available yet|not loaded yet|no .* available/i;
const CHART_FRAME_STATE_COPY =
  /not loaded|not available|unavailable|no .* loaded|no .* reported|do not reconcile|table-only|required before rendering/i;
const COVERAGE_DATE = /\d{4}-\d{2}-\d{2}/;
const EXACT_FEC_SOURCE =
  /^FEC (?:Schedule A itemized individual contributions|candidate and committee summaries|Schedule E independent expenditures)$/;

const FINANCE_CHART_FRAMES = [
  {
    title: "Sources of receipts",
    chartLabel: "Receipt source composition by dollars"
  },
  {
    title: "Itemized individual contributions by month",
    chartLabel: "Monthly contribution columns"
  },
  {
    title: "Itemized contribution-size buckets",
    chartLabel: "Itemized contribution-size buckets bar chart"
  },
  {
    title: "Geography",
    chartLabel: "Geography dollar share by contributor location"
  }
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

async function expectSelectedCycleScope(page: Page): Promise<void> {
  const moneyAtGlance = page.getByRole("region", { name: MONEY_AT_GLANCE_REGION });
  await expect(moneyAtGlance).toBeVisible({ timeout: 20_000 });
  await expect(moneyAtGlance.getByText(SELECTED_CYCLE_COPY, { exact: true })).toBeVisible();
  await expect(moneyAtGlance.getByText(COVERAGE_DATE).first()).toBeVisible();
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
  if (renderedCharts.length === 0) {
    await expectFinanceChartNoDataState(page);
    return;
  }

  const chartRegions = renderedCharts.map((chart) => chart.chart);
  const chartFrames = renderedCharts.map((chart) => chart.frame);
  await expectNoOpaqueNearBlackPaints(chartRegions);
  await expectBoundedNumericTickLabels(chartRegions);
  await expectNoChartFrameOverflow(chartFrames);
  await expectChartSourceLinksKeyboardReachable(chartFrames);
}

async function expectFinanceChartNoDataState(page: Page): Promise<void> {
  const chartFrames = await collectChartFrameRegions(page, FINANCE_CHART_FRAMES);
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
  const disclosure = page.getByRole("button", { name: "View chart data", exact: true });
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
  if (!(await outsideSpendingHasReportedActivity(page))) {
    return;
  }

  const outsideRegion = await chartRegion(page, OUTSIDE_SPENDING_CHART_FRAME.chartLabel);
  const outsideFrame = await chartFrameRegion(page, OUTSIDE_SPENDING_CHART_FRAME.title);
  await expect(outsideRegion).toBeVisible({ timeout: 20_000 });
  await expect(outsideFrame).toBeVisible({ timeout: 20_000 });

  const outsidePaints = await sampleVisibleRectPaints(outsideRegion);
  expect(outsidePaints.length).toBeGreaterThan(0);

  await expect(outsideRegion.getByText(/support/i).first()).toBeVisible();
  await expect(outsideRegion.getByText(/oppose/i).first()).toBeVisible();
  await expectNoOpaqueNearBlackPaints(outsideRegion);
  await expectBoundedNumericTickLabels([outsideRegion]);
  await expectNoChartFrameOverflow([outsideFrame]);
  await expectChartSourceLinksKeyboardReachable([outsideFrame]);
}

async function outsideSpendingHasReportedActivity(page: Page): Promise<boolean> {
  const supportTotal = page.getByText("Support total", { exact: true }).first();
  const opposeTotal = page.getByText("Oppose total", { exact: true }).first();
  return (await supportTotal.isVisible()) && (await opposeTotal.isVisible());
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
    if ((await sampleVisibleRectPaints(chart)).length > 0) {
      regions.push({ frame: figureRegion, chart });
    }
  }
  return regions;
}
