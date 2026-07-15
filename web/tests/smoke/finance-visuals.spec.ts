import { expect, test } from "playwright/test";
import type { Locator, Page } from "playwright";

import {
  SMOKE_CANDIDACY_PERSON_NAME,
  SMOKE_CANDIDATE_CASH_ON_HAND,
  SMOKE_CANDIDATE_COVERAGE_THROUGH,
  SMOKE_CANDIDATE_ID,
  SMOKE_CANDIDATE_OPPOSE_TOTAL,
  SMOKE_CANDIDATE_OUTSIDE_SPENDING_CHART_SUMMARY,
  SMOKE_CANDIDATE_OUTSIDE_SPENDING_COVERAGE_META,
  SMOKE_CANDIDATE_OUTSIDE_SPENDING_EXPLANATION,
  SMOKE_CANDIDATE_SELECTED_CYCLE,
  SMOKE_CANDIDATE_SLUG,
  SMOKE_CANDIDATE_SUPPORT_TOTAL,
  SMOKE_CANDIDATE_TOTAL_RAISED,
  SMOKE_CANDIDATE_TOTAL_SPENT,
  SMOKE_COMMITTEE_CASH_TREND_COVERAGE_META,
  SMOKE_COMMITTEE_CASH_TREND_FIRST_BALANCE,
  SMOKE_COMMITTEE_CASH_TREND_FIRST_PERIOD,
  SMOKE_COMMITTEE_CASH_TREND_LATEST_BALANCE,
  SMOKE_COMMITTEE_CASH_TREND_LATEST_COPY,
  SMOKE_COMMITTEE_CASH_TREND_MISSING_INTERVAL,
  SMOKE_COMMITTEE_CASH_TREND_SECOND_PERIOD,
  SMOKE_COMMITTEE_IE_OPPOSE_TOTAL,
  SMOKE_COMMITTEE_IE_SOURCE_NAME,
  SMOKE_COMMITTEE_IE_SOURCE_RECORD_KEY,
  SMOKE_COMMITTEE_IE_SOURCE_URL,
  SMOKE_COMMITTEE_IE_SUPPORT_TOTAL,
  SMOKE_COMMITTEE_IE_TARGET_NAME,
  SMOKE_COMMITTEE_SECOND_FILING_ROW_LABEL,
  SMOKE_COMMITTEE_SLUG,
  SMOKE_CONTEST_ID,
  SMOKE_IE_COMMITTEE_A_ID,
  SMOKE_IE_COMMITTEE_A_NAME,
  SMOKE_IE_TRANSACTION_DISSEMINATION_DATE,
  SMOKE_PERSON_APPROXIMATE_GEOGRAPHY_NOTE,
  SMOKE_PERSON_CAREER_TOTAL,
  SMOKE_PERSON_CAREER_TOTAL_LABEL,
  SMOKE_PERSON_CYCLE_TOTAL,
  SMOKE_PERSON_DOLLARS_BY_SIZE_SUMMARY,
  SMOKE_PERSON_GEOGRAPHY_SUMMARY,
  SMOKE_PERSON_ID,
  SMOKE_PERSON_MONEY_AT_GLANCE_HEADING,
  SMOKE_PERSON_MONEY_CASH_ON_HAND,
  SMOKE_PERSON_MONEY_COVERAGE,
  SMOKE_PERSON_MONEY_DEBTS_OWED,
  SMOKE_PERSON_MONEY_DISBURSEMENTS,
  SMOKE_PERSON_MONEY_RECEIPTS,
  SMOKE_PERSON_MONEY_SOURCE_LABEL,
  SMOKE_PERSON_MONTHLY_CONTRIBUTIONS_SUMMARY,
  SMOKE_PERSON_OUTSIDE_SPENDING_HEADING,
  SMOKE_PERSON_OUTSIDE_SPENDING_SUMMARY,
  SMOKE_PERSON_RECEIPT_COMPOSITION_SUMMARY,
  SMOKE_PERSON_REPORTED_TRANSACTIONS_BY_SIZE_SUMMARY,
  SMOKE_PERSON_SELECTED_CYCLE,
  SMOKE_PERSON_CONTRIBUTION_CHART_COVERAGE_META,
  SMOKE_PERSON_TOP_DONOR_ONE_TOTAL,
  SMOKE_PERSON_TOP_DONOR_ONE_NAME,
  SMOKE_PERSON_TOP_EMPLOYER_ONE_TOTAL,
  SMOKE_PERSON_TOP_EMPLOYER_ONE_NAME,
  SMOKE_PERSON_SUMMARY_CHART_COVERAGE_META,
  SMOKE_PERSON_TOP_SPENDER_NAME,
  SMOKE_PERSON_TOP_SPENDER_TOTAL,
  SMOKE_PERSON_UNITEMIZED_EXCLUSION_NOTE,
  SMOKE_USE_LIVE_API
} from "./fixtures";
import {
  BAR_SERIES_MARK_SELECTOR,
  LINE_SERIES_MARK_SELECTOR,
  chartRegion,
  escapeRegExp,
  expectBoundedNumericTickLabels,
  expectNoChartFrameOverflow,
  expectNoHorizontalOverflow,
  expectNoMaterialNearBlackOverlay,
  expectNoOpaqueNearBlackPaints,
  expectNonZeroChartBox,
  expectRealChartRender
} from "./smoke-helpers";

const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 1000 },
  { name: "tablet", width: 768, height: 1000 },
  { name: "mobile", width: 390, height: 1100 }
] as const;
const RESPONSIVE_SNAPSHOT_VIEWPORTS = VIEWPORTS.filter((viewport) => viewport.name !== "tablet");
const MOBILE_VIEWPORT = VIEWPORTS.find((viewport) => viewport.name === "mobile") ?? {
  name: "mobile",
  width: 390,
  height: 1100
};
const IS_PRODUCTION_SMOKE_MODE = process.env.SMOKE_MODE === "production";

const CHARTS = [
  {
    label: "Receipt source composition by dollars",
    markSelector: BAR_SERIES_MARK_SELECTOR
  },
  {
    label: "Monthly contribution columns",
    markSelector: BAR_SERIES_MARK_SELECTOR
  },
  {
    label: "Itemized contribution-size buckets bar chart",
    markSelector: BAR_SERIES_MARK_SELECTOR
  },
  {
    label: "Geography dollar share by contributor location",
    markSelector: BAR_SERIES_MARK_SELECTOR
  },
  {
    label: "Zero-centered support and oppose spending comparison",
    markSelector: BAR_SERIES_MARK_SELECTOR
  }
] as const;

test.describe("fixture-backed finance visuals", () => {
  test.skip(
    SMOKE_USE_LIVE_API || IS_PRODUCTION_SMOKE_MODE,
    "fixture-only visual oracle — production data can drift"
  );

  for (const viewport of VIEWPORTS) {
    test(`person finance charts render accessibly at ${viewport.name} width`, async ({
      page
    }: {
      page: Page;
    }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto(`/person/${SMOKE_PERSON_ID}`);

      const chartRegions: Locator[] = [];
      for (const chart of CHARTS) {
        const region = await chartRegion(page, chart.label);
        chartRegions.push(region);
        await expect(region).toBeVisible();
        await expectNonZeroChartBox(region, chart.markSelector);
        await expectRealChartRender(region, chart.markSelector);
      }
      await expectNoOpaqueNearBlackPaints(chartRegions);

      await expectPersonFinanceSemantics(page);
      await expectPersonFinanceLayout(page, chartRegions);
      await expectNoHorizontalOverflow(page);

      await expect(page).toHaveScreenshot(`person-finance-${viewport.name}.png`, {
        fullPage: true,
        animations: "disabled"
      });
    });
  }

  for (const viewport of RESPONSIVE_SNAPSHOT_VIEWPORTS) {
    test(`contest finance contract renders accessibly at ${viewport.name} width`, async ({
      page
    }: {
      page: Page;
    }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto(`/contest/${SMOKE_CONTEST_ID}`);

      await expectContestFinanceContract(page);

      const outsideSpendingRegion = await chartRegion(
        page,
        "Zero-centered support and oppose spending comparison"
      );
      await expect(outsideSpendingRegion).toBeVisible();
      await expectNonZeroChartBox(outsideSpendingRegion, BAR_SERIES_MARK_SELECTOR);
      await expectRealChartRender(outsideSpendingRegion, BAR_SERIES_MARK_SELECTOR);
      await expectNoOpaqueNearBlackPaints(outsideSpendingRegion);
      await expectNoHorizontalOverflow(page);

      await expect(page).toHaveScreenshot(`contest-finance-${viewport.name}.png`, {
        fullPage: true,
        animations: "disabled"
      });
    });
  }

  test("candidate finance detail keeps exact outside-spending facts", async ({ page }: { page: Page }) => {
    await page.goto(`/candidate/${SMOKE_CANDIDATE_ID}`);

    await expect(page).toHaveURL(new RegExp(`/candidate/${SMOKE_CANDIDATE_SLUG}$`));
    await expect(page.getByRole("heading", { name: "Outside Spending" })).toBeVisible();
    await expect(
      page.getByText(SMOKE_CANDIDATE_OUTSIDE_SPENDING_EXPLANATION, { exact: true })
    ).toBeVisible();
    await expect(page.getByRole("heading", { name: "Support spending" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Oppose spending" })).toBeVisible();
    await expect(page.getByText(SMOKE_CANDIDATE_SUPPORT_TOTAL, { exact: true })).toBeVisible();
    await expect(page.getByText(SMOKE_CANDIDATE_OPPOSE_TOTAL, { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: SMOKE_PERSON_TOP_SPENDER_NAME }).first()).toHaveAttribute(
      "href",
      `/committee/${SMOKE_IE_COMMITTEE_A_ID}`
    );
    await expect(
      page.getByTestId("outside-spending-transactions-scroll").getByRole("cell", {
        name: SMOKE_IE_TRANSACTION_DISSEMINATION_DATE,
        exact: true
      })
    ).toBeVisible();
  });

  for (const viewport of RESPONSIVE_SNAPSHOT_VIEWPORTS) {
    test(`committee cash trend renders accessibly at ${viewport.name} width`, async ({
      page
    }: {
      page: Page;
    }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto(`/committee/${SMOKE_COMMITTEE_SLUG}`);

      await expectCommitteeFinanceContract(page);

      const cashTrendRegion = await chartRegion(page, "Cash on hand trend by filing period");
      await expect(cashTrendRegion).toBeVisible();
      await expectNonZeroChartBox(cashTrendRegion, LINE_SERIES_MARK_SELECTOR);
      await expectRealChartRender(cashTrendRegion, LINE_SERIES_MARK_SELECTOR);
      await expectNoOpaqueNearBlackPaints(cashTrendRegion);
      await expectNoHorizontalOverflow(page);

      await expect(page).toHaveScreenshot(`committee-finance-${viewport.name}.png`, {
        fullPage: true,
        animations: "disabled"
      });
    });
  }

  test("committee filing breakdown keeps the mobile scroll contract", async ({ page }: { page: Page }) => {
    await page.setViewportSize({ width: MOBILE_VIEWPORT.width, height: MOBILE_VIEWPORT.height });
    await page.goto(`/committee/${SMOKE_COMMITTEE_SLUG}`);

    const filingBreakdownScroll = page.getByTestId("filing-breakdown-scroll");
    await expect(filingBreakdownScroll).toBeVisible();
    await expect(filingBreakdownScroll).toHaveCSS("overflow-x", "auto");
    await expectNoHorizontalOverflow(page);
  });

  test("person finance selected cycle and disclosure controls stay accessible", async ({
    page
  }: {
    page: Page;
  }) => {
    await page.setViewportSize({ width: MOBILE_VIEWPORT.width, height: MOBILE_VIEWPORT.height });
    await page.goto(`/person/${SMOKE_PERSON_ID}?cycle=${SMOKE_PERSON_SELECTED_CYCLE}`);

    await expect(page).toHaveURL(new RegExp(`/person/${SMOKE_PERSON_ID}\\?cycle=${SMOKE_PERSON_SELECTED_CYCLE}$`));
    await expectSelectedCycleState(page);
    await expectChartFrameCoverage(page);
    await expectAccessibleFinanceControls(page);
    await expectDisclosureKeyboardFlow(page.getByTestId("person-receipt-composition"));
  });
});

async function expectPersonFinanceSemantics(page: Page): Promise<void> {
  await expectSelectedCycleState(page);
  await expectContributionTotalToggle(page);
  await expectSizeBucketToggle(page);
  await expectMoneyAtGlance(page);
  await expectChartSummariesAndTables(page);
  await expectRankingTables(page);
  await expectSourceLinks(page);
}

async function expectSelectedCycleState(page: Page): Promise<void> {
  const moneyAtGlance = page.getByRole("region", {
    name: SMOKE_PERSON_MONEY_AT_GLANCE_HEADING
  });
  await expect(moneyAtGlance).toBeVisible();
  await expect(moneyAtGlance.getByText(`${SMOKE_PERSON_SELECTED_CYCLE} cycle`, { exact: true })).toBeVisible();
  await expect(moneyAtGlance.getByRole("link", { name: SMOKE_PERSON_SELECTED_CYCLE })).toHaveAttribute(
    "aria-current",
    "page"
  );
}

async function expectContributionTotalToggle(page: Page): Promise<void> {
  const contributionTotalsSummary = page.getByTestId("person-contribution-total-summary");
  await expect(contributionTotalsSummary.getByText(SMOKE_PERSON_CYCLE_TOTAL, { exact: true })).toBeVisible();
  await expect(contributionTotalsSummary.getByText(SMOKE_PERSON_CAREER_TOTAL, { exact: true })).toHaveCount(0);
  const contributionTotalsView = page.getByRole("group", { name: "Contribution totals view" });
  await expect(contributionTotalsView.getByRole("button", { name: "2026 cycle" })).toHaveAttribute(
    "aria-pressed",
    "true"
  );
  await contributionTotalsView.getByRole("button", { name: SMOKE_PERSON_CAREER_TOTAL_LABEL }).click();
  await expect(contributionTotalsSummary.getByText(SMOKE_PERSON_CAREER_TOTAL, { exact: true })).toBeVisible();
  await expect(contributionTotalsView.getByRole("button", { name: SMOKE_PERSON_CAREER_TOTAL_LABEL })).toHaveAttribute(
    "aria-pressed",
    "true"
  );
  await contributionTotalsView.getByRole("button", { name: "2026 cycle" }).click();
  await expect(contributionTotalsSummary.getByText(SMOKE_PERSON_CYCLE_TOTAL, { exact: true })).toBeVisible();
}

async function expectSizeBucketToggle(page: Page): Promise<void> {
  const sizeBucketControl = page.getByRole("group", { name: "Contribution-size bucket scale" });
  await expect(sizeBucketControl.getByText("Dollars | Reported transactions", { exact: true })).toBeVisible();
  await expect(sizeBucketControl.getByRole("button", { name: "Dollars" })).toHaveAttribute(
    "aria-pressed",
    "true"
  );
  await expect(page.getByTestId("person-size-buckets").getByText("$125.00; 1 reported transaction")).toBeVisible();
  await sizeBucketControl.getByRole("button", { name: "Reported transactions" }).click();
  await expect(sizeBucketControl.getByRole("button", { name: "Reported transactions" })).toHaveAttribute(
    "aria-pressed",
    "true"
  );
  await expect(
    page.getByTestId("person-size-buckets").getByText("1 reported transactions", { exact: true })
  ).toHaveCount(2);
  await sizeBucketControl.getByRole("button", { name: "Dollars" }).click();
}

async function expectMoneyAtGlance(page: Page): Promise<void> {
  const moneyAtGlance = page.getByRole("region", {
    name: SMOKE_PERSON_MONEY_AT_GLANCE_HEADING
  });
  await expect(moneyAtGlance.getByText(SMOKE_PERSON_MONEY_COVERAGE, { exact: true })).toBeVisible();
  await expect(moneyAtGlance.getByText(SMOKE_PERSON_MONEY_SOURCE_LABEL, { exact: true })).toBeVisible();
  await expect(moneyAtGlance.getByText("Outside spending details", { exact: true })).toHaveAttribute(
    "href",
    "#person-outside-spending"
  );
  await expect(moneyAtGlance.getByText(SMOKE_PERSON_MONEY_RECEIPTS, { exact: true })).toBeVisible();
  await expect(moneyAtGlance.getByText(SMOKE_PERSON_MONEY_DISBURSEMENTS, { exact: true })).toBeVisible();
  await expect(moneyAtGlance.getByText(SMOKE_PERSON_MONEY_CASH_ON_HAND, { exact: true })).toBeVisible();
  await expect(moneyAtGlance.getByText(SMOKE_PERSON_MONEY_DEBTS_OWED, { exact: true })).toBeVisible();
}

async function expectChartSummariesAndTables(page: Page): Promise<void> {
  await expectChartDisclosure(page.getByTestId("person-receipt-composition"), {
    summary: SMOKE_PERSON_RECEIPT_COMPOSITION_SUMMARY,
    rows: [
      { label: "Gross individual contributions", values: ["Dollars: $125.00", "Share: 50%", "Denominator: $250.00"] },
      { label: "PAC/other committee contributions", values: ["Dollars: $125.00", "Share: 50%", "Denominator: $250.00"] }
    ]
  });
  await expectChartDisclosure(page.getByTestId("person-monthly-contributions"), {
    summary: SMOKE_PERSON_MONTHLY_CONTRIBUTIONS_SUMMARY,
    rows: [
      { label: "January 2026", values: ["Dollars: $125.00", "Transactions: 1", "Coverage: Covered"] },
      { label: "February 2026", values: ["Dollars: $225.00", "Transactions: 1", "Coverage: Covered"] }
    ]
  });
  await expectChartDisclosure(page.getByTestId("person-size-buckets"), {
    summary: SMOKE_PERSON_DOLLARS_BY_SIZE_SUMMARY,
    rows: [
      { label: "$200 and under", values: ["Dollars: $125.00", "Transactions: 1"] },
      { label: "$200.01-$499.99", values: ["Dollars: $225.00", "Transactions: 1"] }
    ]
  });
  await page
    .getByRole("group", { name: "Contribution-size bucket scale" })
    .getByRole("button", { name: "Reported transactions" })
    .click();
  await expect(page.getByTestId("person-size-buckets").getByText(SMOKE_PERSON_REPORTED_TRANSACTIONS_BY_SIZE_SUMMARY, {
    exact: true
  })).toBeVisible();
  await page
    .getByRole("group", { name: "Contribution-size bucket scale" })
    .getByRole("button", { name: "Dollars" })
    .click();
  await expectChartDisclosure(page.getByTestId("person-geography-share"), {
    summary: SMOKE_PERSON_GEOGRAPHY_SUMMARY,
    rows: [
      { label: "In district", values: ["Dollars: $125.00", "Transactions: 1", "Denominator: $350.00"] },
      { label: "Out of district", values: ["Dollars: $225.00", "Transactions: 1", "Denominator: $350.00"] },
      { label: "Unknown", values: ["Dollars: $0.00", "Transactions: 0", "Denominator: $350.00"] }
    ]
  });
  await expectChartDisclosure(page.getByTestId("person-outside-spending"), {
    summary: SMOKE_PERSON_OUTSIDE_SPENDING_SUMMARY,
    rows: [
      { label: "Support spending", values: ["Dollars: $15,000.00", "Transactions: 12"] },
      { label: "Oppose spending", values: ["Dollars: $8,500.00", "Transactions: 5"] },
      { label: `Top spender: ${SMOKE_PERSON_TOP_SPENDER_NAME}`, values: ["Dollars: $10,000.00", "Transactions: 8"] }
    ]
  });
}

async function expectChartFrameCoverage(page: Page): Promise<void> {
  await expect(page.getByText(SMOKE_PERSON_SUMMARY_CHART_COVERAGE_META, { exact: true }).first()).toBeVisible();
  await expect(
    page.getByTestId("person-receipt-composition").getByText(SMOKE_PERSON_SUMMARY_CHART_COVERAGE_META, {
      exact: true
    })
  ).toBeVisible();
  await expect(
    page.getByTestId("person-monthly-contributions").getByText(SMOKE_PERSON_CONTRIBUTION_CHART_COVERAGE_META, {
      exact: true
    })
  ).toBeVisible();
  await expect(
    page.getByTestId("person-size-buckets").getByText(SMOKE_PERSON_CONTRIBUTION_CHART_COVERAGE_META, {
      exact: true
    })
  ).toBeVisible();
  await expect(
    page.getByTestId("person-geography-share").getByText(SMOKE_PERSON_CONTRIBUTION_CHART_COVERAGE_META, {
      exact: true
    })
  ).toBeVisible();
  await expect(
    page.getByTestId("person-outside-spending").getByText(SMOKE_CANDIDATE_OUTSIDE_SPENDING_COVERAGE_META, {
      exact: true
    })
  ).toBeVisible();
}

async function expectChartDisclosure(
  chart: Locator,
  expected: {
    summary: string;
    rows: Array<{ label: string; values: string[] }>;
  }
): Promise<void> {
  await expect(chart.getByText(expected.summary, { exact: true })).toBeVisible();
  await chart.getByText("View chart data", { exact: true }).click();
  for (const row of expected.rows) {
    const disclosureRow = chart.getByRole("row", {
      name: new RegExp(`^${escapeRegExp(row.label)}(?:\\s|$)`)
    });
    await expect(disclosureRow).toBeVisible();
    for (const value of row.values) {
      await expect(disclosureRow).toContainText(value);
    }
  }
}

async function expectAccessibleFinanceControls(page: Page): Promise<void> {
  const controls = [
    { label: "selected cycle link", locator: page.getByRole("link", { name: SMOKE_PERSON_SELECTED_CYCLE }) },
    {
      label: "outside spending details link",
      locator: page.getByRole("link", { name: "Outside spending details", exact: true })
    },
    {
      label: "contribution totals buttons",
      locator: page.getByRole("group", { name: "Contribution totals view" }).getByRole("button")
    },
    {
      label: "size bucket scale buttons",
      locator: page.getByRole("group", { name: "Contribution-size bucket scale" }).getByRole("button")
    },
    {
      label: "receipt composition disclosure summary",
      locator: page.getByTestId("person-receipt-composition").getByText("View chart data", { exact: true })
    },
    {
      label: "monthly contributions disclosure summary",
      locator: page.getByTestId("person-monthly-contributions").getByText("View chart data", { exact: true })
    },
    {
      label: "size buckets disclosure summary",
      locator: page.getByTestId("person-size-buckets").getByText("View chart data", { exact: true })
    },
    {
      label: "geography share disclosure summary",
      locator: page.getByTestId("person-geography-share").getByText("View chart data", { exact: true })
    },
    {
      label: "outside spending disclosure summary",
      locator: page.getByTestId("person-outside-spending").getByText("View chart data", { exact: true })
    }
  ];
  const undersizedControls: string[] = [];

  for (const control of controls) {
    const boxes = await control.locator.evaluateAll((elements: Element[]) =>
      elements.map((element) => {
        const box = element.getBoundingClientRect();
        return {
          height: Math.round(box.height),
          width: Math.round(box.width)
        };
      })
    );
    expect(boxes.length).toBeGreaterThan(0);
    for (const [index, box] of boxes.entries()) {
      if (box.height < 44 || box.width < 44) {
        undersizedControls.push(`${control.label} #${index + 1}: ${box.width}x${box.height}`);
      }
    }
  }
  expect(undersizedControls).toEqual([]);
}

async function expectDisclosureKeyboardFlow(chart: Locator): Promise<void> {
  // eslint-disable-next-line playwright/no-raw-locators -- details has no stable role before it is expanded.
  const disclosure = chart.locator("details");
  const summary = chart.getByText("View chart data", { exact: true });

  await expect(disclosure).not.toHaveAttribute("open", "");
  await summary.focus();
  await expect(summary).toBeFocused();
  await summary.press("Enter");
  await expect(disclosure).toHaveAttribute("open", "");
}

async function expectRankingTables(page: Page): Promise<void> {
  await expect(
    page.getByRole("heading", { name: SMOKE_PERSON_OUTSIDE_SPENDING_HEADING, exact: true })
  ).toBeVisible();
  await expect(page.getByText(SMOKE_PERSON_UNITEMIZED_EXCLUSION_NOTE, { exact: true })).toBeVisible();
  await expect(page.getByText(SMOKE_PERSON_APPROXIMATE_GEOGRAPHY_NOTE, { exact: true })).toHaveCount(2);
  const topDonorRow = page.getByTestId("person-top-donors-scroll").getByRole("row").nth(1);
  await expect(topDonorRow).toContainText(SMOKE_PERSON_TOP_DONOR_ONE_NAME);
  await expect(topDonorRow).toContainText(SMOKE_PERSON_TOP_DONOR_ONE_TOTAL);
  const topEmployerRow = page.getByTestId("person-top-employers-scroll").getByRole("row").nth(1);
  await expect(topEmployerRow).toContainText(SMOKE_PERSON_TOP_EMPLOYER_ONE_NAME);
  await expect(topEmployerRow).toContainText(SMOKE_PERSON_TOP_EMPLOYER_ONE_TOTAL);
  await expect(page.getByText(SMOKE_CANDIDATE_SUPPORT_TOTAL, { exact: true })).toHaveCount(2);
  await expect(page.getByText(SMOKE_CANDIDATE_OPPOSE_TOTAL, { exact: true })).toHaveCount(2);
  const topSpenderRow = page.getByTestId("person-ie-top-spenders-scroll").getByRole("row").nth(1);
  await expect(topSpenderRow).toContainText(SMOKE_PERSON_TOP_SPENDER_NAME);
  await expect(topSpenderRow).toContainText(SMOKE_PERSON_TOP_SPENDER_TOTAL);
}

async function expectSourceLinks(page: Page): Promise<void> {
  await expect(page.getByRole("link", { name: "View source record" })).toHaveAttribute(
    "href",
    "https://example.org/person-1"
  );
  await expect(
    page.getByTestId("person-ie-transactions-scroll").getByRole("link", { name: "Source filing" })
  ).toHaveAttribute("href", "/v1/filings/33333333-3333-4333-8333-333333333333");
}

async function expectContestFinanceContract(page: Page): Promise<void> {
  await expect(page.getByRole("heading", { name: "Candidate finance and outside spending" })).toBeVisible();
  await expect(
    page.getByRole("link", { name: SMOKE_CANDIDACY_PERSON_NAME, exact: true }).first()
  ).toHaveAttribute("href", `/person/${SMOKE_PERSON_ID}?cycle=${SMOKE_CANDIDATE_SELECTED_CYCLE}`);
  await expect(
    page.getByRole("heading", { name: SMOKE_CANDIDACY_PERSON_NAME, level: 4 }).getByRole("link", {
      name: SMOKE_CANDIDACY_PERSON_NAME,
      exact: true
    })
  ).toHaveAttribute("href", `/candidate/${SMOKE_CANDIDATE_SLUG}?cycle=${SMOKE_CANDIDATE_SELECTED_CYCLE}`);

  await expectContestFact(page, "Selected cycle", SMOKE_CANDIDATE_SELECTED_CYCLE);
  await expectContestFact(page, "Coverage through", SMOKE_CANDIDATE_COVERAGE_THROUGH);
  await expectContestFact(page, "Receipts", SMOKE_CANDIDATE_TOTAL_RAISED);
  await expectContestFact(page, "Disbursements", SMOKE_CANDIDATE_TOTAL_SPENT);
  await expectContestFact(page, "Cash on hand", SMOKE_CANDIDATE_CASH_ON_HAND);
  await expect(page.getByText("Fundraising summary", { exact: true })).toHaveCount(0);
  await expect(page.getByText(/Finance chart for|Outside spending chart for/)).toHaveCount(0);

  await expect(
    page.getByText(SMOKE_CANDIDATE_OUTSIDE_SPENDING_EXPLANATION, { exact: true })
  ).toBeVisible();
  await expect(
    page.getByText(SMOKE_CANDIDATE_OUTSIDE_SPENDING_COVERAGE_META, { exact: true })
  ).toBeVisible();
  await expect(
    page.getByText(SMOKE_CANDIDATE_OUTSIDE_SPENDING_CHART_SUMMARY, { exact: true })
  ).toBeVisible();
  await page.getByTestId(`contest-outside-spending-${SMOKE_PERSON_ID}`).getByText("View chart data").click();
  await expect(page.getByRole("cell").filter({ hasText: SMOKE_CANDIDATE_SUPPORT_TOTAL }).first()).toBeVisible();
  await expect(page.getByRole("cell").filter({ hasText: SMOKE_CANDIDATE_OPPOSE_TOTAL }).first()).toBeVisible();
  await expect(page.getByRole("link", { name: SMOKE_IE_COMMITTEE_A_NAME }).first()).toHaveAttribute(
    "href",
    `/committee/${SMOKE_IE_COMMITTEE_A_ID}`
  );
  await expect(
    page.getByRole("cell", { name: SMOKE_IE_TRANSACTION_DISSEMINATION_DATE, exact: true })
  ).toBeVisible();
}

async function expectContestFact(page: Page, label: string, value: string): Promise<void> {
  await expect(page.getByText(label, { exact: true }).first()).toBeVisible();
  await expect(page.getByText(value, { exact: true }).first()).toBeVisible();
}

async function expectCommitteeFinanceContract(page: Page): Promise<void> {
  const committeeOutsideSpending = page.getByTestId("committee-outside-spending");
  await expect(
    committeeOutsideSpending.getByRole("definition").filter({ hasText: SMOKE_COMMITTEE_IE_SUPPORT_TOTAL })
  ).toBeVisible();
  await expect(
    committeeOutsideSpending.getByRole("definition").filter({ hasText: SMOKE_COMMITTEE_IE_OPPOSE_TOTAL })
  ).toBeVisible();
  await expect(
    page.getByTestId("committee-outside-spending-targets").getByRole("link", {
      name: SMOKE_COMMITTEE_IE_TARGET_NAME,
      exact: true
    })
  ).toHaveAttribute("href", `/person/${SMOKE_PERSON_ID}`);
  const committeeOutsideSpendingSources = page.getByTestId("committee-outside-spending-sources");
  await expect(
    committeeOutsideSpendingSources.getByRole("link", {
      name: SMOKE_COMMITTEE_IE_SOURCE_NAME,
      exact: true
    })
  ).toHaveAttribute("href", SMOKE_COMMITTEE_IE_SOURCE_URL);
  await expect(committeeOutsideSpendingSources.getByText(SMOKE_COMMITTEE_IE_SOURCE_RECORD_KEY)).toBeVisible();

  await expect(
    page.getByText(SMOKE_COMMITTEE_CASH_TREND_COVERAGE_META, { exact: true })
  ).toBeVisible();
  await expect(page.getByText(SMOKE_COMMITTEE_CASH_TREND_LATEST_COPY, { exact: true })).toBeVisible();
  await page.getByTestId("committee-cash-on-hand-trend").getByText("View chart data").click();
  await expect(
    page
      .getByRole("row")
      .filter({ hasText: SMOKE_COMMITTEE_CASH_TREND_FIRST_PERIOD })
      .filter({ hasText: SMOKE_COMMITTEE_CASH_TREND_FIRST_BALANCE })
  ).toBeVisible();
  await expect(
    page
      .getByRole("row")
      .filter({ hasText: SMOKE_COMMITTEE_CASH_TREND_SECOND_PERIOD })
      .filter({ hasText: SMOKE_COMMITTEE_CASH_TREND_LATEST_BALANCE })
  ).toBeVisible();
  await expect(
    page.getByText(SMOKE_COMMITTEE_CASH_TREND_MISSING_INTERVAL, { exact: true })
  ).toBeVisible();
  await expect(
    page.getByRole("cell", { name: SMOKE_COMMITTEE_SECOND_FILING_ROW_LABEL, exact: true })
  ).toBeVisible();
}

async function expectPersonFinanceLayout(page: Page, chartRegions: Locator[]): Promise<void> {
  for (const chart of CHARTS) {
    await expect(page.getByLabel(new RegExp(`^${chart.label}(?: for .*)?$`, "i"))).toHaveCount(1);
  }
  await expectZeroDocumentOverflow(page);
  await expectNoChartFrameOverflow(chartRegions);
  await expectBoundedNumericTickLabels(chartRegions);
  await expectContainedTooltips(page);
  await expectNoMaterialNearBlackOverlay(page);
}

/* eslint-disable no-restricted-syntax -- Stage 4 keeps geometry oracles local to this person smoke spec. */
async function expectZeroDocumentOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => {
    const root = document.documentElement;
    return {
      x: Math.ceil(root.scrollWidth - root.clientWidth),
      bodyX: Math.ceil(document.body.scrollWidth - document.body.clientWidth)
    };
  });
  expect(overflow).toEqual({ x: 0, bodyX: 0 });
}

async function expectContainedTooltips(page: Page): Promise<void> {
  const escapedTooltips = await page.evaluate(() => {
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    return Array.from(document.querySelectorAll<HTMLElement>('[role="tooltip"], [data-testid*="tooltip"]'))
      .filter((element) => element.offsetParent !== null)
      .map((element) => element.getBoundingClientRect())
      .filter(
        (box) =>
          box.left < 0 ||
          box.top < 0 ||
          box.right > viewportWidth ||
          box.bottom > viewportHeight
      ).length;
  });
  expect(escapedTooltips).toBe(0);
}
/* eslint-enable no-restricted-syntax */
