import { expect, test } from "playwright/test";
import type { Locator, Page } from "playwright";

import releaseTargets from "./production_release_targets.json" with { type: "json" };
import {
  BAR_SERIES_MARK_SELECTOR,
  capturePageLoadErrors,
  chartRegion,
  escapeRegExp,
  expectBoundedNumericTickLabels,
  expectNoBackendFailureStates,
  expectNoChartFrameOverflow,
  expectNoHorizontalOverflow,
  expectNoMaterialNearBlackOverlay,
  expectNoOpaqueNearBlackPaints,
  expectRealChartRender,
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

  await expectRealChartRender(outsideRegion, BAR_SERIES_MARK_SELECTOR);
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
    await expectRealChartRender(chart, BAR_SERIES_MARK_SELECTOR);
    regions.push({ frame: figureRegion, chart });
  }
  return regions;
}
