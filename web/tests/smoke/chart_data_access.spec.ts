import { expect, test } from "playwright/test";
import type { Locator, Page } from "playwright";

import {
  SMOKE_CHART_DATA_ACCESS_ROWS,
  SMOKE_CHART_LIVE_DATA_ACCESS_ROWS,
  SMOKE_CHART_LIVE_PERSON_ID,
  SMOKE_COMMITTEE_CASH_TREND_FIRST_BALANCE,
  SMOKE_COMMITTEE_CASH_TREND_FIRST_PERIOD,
  SMOKE_COMMITTEE_CASH_TREND_LATEST_BALANCE,
  SMOKE_COMMITTEE_CASH_TREND_MISSING_INTERVAL,
  SMOKE_COMMITTEE_CASH_TREND_NO_MISSING_INTERVAL,
  SMOKE_COMMITTEE_CASH_TREND_SECOND_PERIOD,
  SMOKE_COMMITTEE_SLUG,
  SMOKE_CONGRESS_LEADER_PERSON_ID,
  SMOKE_CONGRESS_LEADER_TOTAL_RAISED_COMPACT,
  SMOKE_PERSON_CANONICAL_NAME,
  SMOKE_PERSON_ID,
  SMOKE_USE_LIVE_API
} from "./fixtures";
import {
  buildCongressSmokeCleanupSql,
  seedLiveCongressDirectorySmoke
} from "./smoke-seed-sql";
import {
  BAR_SERIES_MARK_SELECTOR,
  chartRegion,
  expectRealChartRender
} from "./smoke-helpers";

type ExpectedRow = {
  label: string;
  values: readonly string[];
};

const IS_PRODUCTION_SMOKE_MODE = process.env.SMOKE_MODE === "production";
const CHART_DATA_ACCESS_CASES = [
  {
    owner: "ReceiptCompositionChart",
    route: "person",
    paintLabel: "Receipt source composition by dollars",
    testId: "person-receipt-composition",
    rows: SMOKE_USE_LIVE_API
      ? SMOKE_CHART_LIVE_DATA_ACCESS_ROWS.receiptComposition
      : SMOKE_CHART_DATA_ACCESS_ROWS.receiptComposition
  },
  {
    owner: "MonthlyContributionsChart",
    route: "person",
    paintLabel: "Monthly contribution columns",
    testId: "person-monthly-contributions",
    rows: SMOKE_USE_LIVE_API
      ? SMOKE_CHART_LIVE_DATA_ACCESS_ROWS.monthlyContributions
      : SMOKE_CHART_DATA_ACCESS_ROWS.monthlyContributions
  },
  {
    owner: "HorizontalBarChart",
    route: "person",
    paintLabel: "Itemized contribution-size buckets bar chart",
    testId: "person-size-buckets",
    rows: SMOKE_USE_LIVE_API
      ? SMOKE_CHART_LIVE_DATA_ACCESS_ROWS.sizeBuckets
      : SMOKE_CHART_DATA_ACCESS_ROWS.sizeBuckets
  },
  {
    owner: "GeographyShareChart",
    route: "person",
    paintLabel: "Geography dollar share by contributor location",
    testId: "person-geography-share",
    rows: SMOKE_USE_LIVE_API
      ? SMOKE_CHART_LIVE_DATA_ACCESS_ROWS.geographyShare
      : SMOKE_CHART_DATA_ACCESS_ROWS.geographyShare
  },
  {
    owner: "OutsideSpendingChart",
    route: "person",
    paintLabel: "Zero-centered support and oppose spending comparison",
    testId: "person-outside-spending",
    rows: SMOKE_USE_LIVE_API
      ? SMOKE_CHART_LIVE_DATA_ACCESS_ROWS.outsideSpending
      : SMOKE_CHART_DATA_ACCESS_ROWS.outsideSpending
  },
  {
    owner: "CashOnHandTrendChart",
    route: "committee",
    testId: "committee-cash-on-hand-trend",
    rows: [
      {
        label: SMOKE_COMMITTEE_CASH_TREND_FIRST_PERIOD,
        values: [
          `Cash on hand: ${SMOKE_COMMITTEE_CASH_TREND_FIRST_BALANCE}`,
          `Coverage gap: ${SMOKE_COMMITTEE_CASH_TREND_NO_MISSING_INTERVAL}`
        ]
      },
      {
        label: SMOKE_COMMITTEE_CASH_TREND_SECOND_PERIOD,
        values: [
          `Cash on hand: ${SMOKE_COMMITTEE_CASH_TREND_LATEST_BALANCE}`,
          `Coverage gap: ${SMOKE_COMMITTEE_CASH_TREND_MISSING_INTERVAL}`
        ]
      }
    ]
  },
  {
    owner: "ComparisonBar",
    route: "congress",
    testId: `comparison-row-${SMOKE_CONGRESS_LEADER_PERSON_ID}`,
    rows: []
  }
] as const;
type ChartDataAccessCase = (typeof CHART_DATA_ACCESS_CASES)[number];
type PersonChartDataAccessCase = Extract<ChartDataAccessCase, { route: "person" }>;

test("person-scenario cleanup preserves a shared office that is still referenced", () => {
  const cleanupSql = buildCongressSmokeCleanupSql("charts");
  const officeCleanup = cleanupSql.match(
    /DELETE FROM civic\.office(?: AS office)?[\s\S]*?DELETE FROM civic\.electoral_division/
  )?.[0];

  expect(officeCleanup).toBeDefined();
  expect(officeCleanup).toContain("NOT EXISTS");
  expect(officeCleanup).toContain("FROM civic.officeholding");
});

// The `View chart data` table renders each fact as one accessible row whose name
// is the row label followed by every value segment. Playwright joins the value
// cells with a bare `;` (no surrounding space) and separates the label from the
// values with a single space, so this is the exact accessible name of one row.
// Asserting that whole string as a unit binds each label to its own complete
// value set: a swapped value, a changed count (`1` vs `12`), or a value that
// belongs to a different row all change this string and fail the contract.
function expectedAccessibleRowName(row: ExpectedRow): string {
  return `${row.label} ${row.values.join(";")}`;
}

function accessibleRowNames(snapshot: string): string[] {
  return snapshot
    .split("\n")
    .map((line) => {
      const match = line.trim().match(/^- (?:'row "(.+)"'|row "(.+)")(?::)?$/);
      return match?.[1] ?? match?.[2];
    })
    .filter((rowName): rowName is string => rowName !== undefined);
}

function expectExactAccessibleRows(snapshot: string, rows: readonly ExpectedRow[]): void {
  expect(accessibleRowNames(snapshot)).toEqual([
    "Label Values",
    ...rows.map(expectedAccessibleRowName)
  ]);
}

function expectExactAccessibleTextNode(snapshot: string, text: string): void {
  expect(snapshot.split("\n").map((line) => line.trim())).toContain(`- text: ${text}`);
}

async function openChartDataAndSnapshot(chart: Locator): Promise<string> {
  const disclosure = chart.getByText("View chart data", { exact: true });
  await expect(disclosure).toBeVisible();
  await disclosure.click();
  return chart.ariaSnapshot();
}

function chartCaseForRoute(route: "committee" | "congress") {
  const matches = CHART_DATA_ACCESS_CASES.filter((chartCase) => chartCase.route === route);
  expect(matches).toHaveLength(1);
  return matches[0];
}

function personChartCases(): PersonChartDataAccessCase[] {
  return CHART_DATA_ACCESS_CASES.filter(
    (chartCase): chartCase is PersonChartDataAccessCase => chartCase.route === "person"
  );
}

test.describe("fixture-backed chart data accessibility", () => {
  test.skip(
    SMOKE_USE_LIVE_API || IS_PRODUCTION_SMOKE_MODE,
    "fixture-only chart data contract — production data can drift"
  );

  test("covers the exact seven route-facing chart owners", () => {
    expect(CHART_DATA_ACCESS_CASES).toHaveLength(7);
    expect(CHART_DATA_ACCESS_CASES.map(({ owner }) => owner)).toEqual([
      "ReceiptCompositionChart",
      "MonthlyContributionsChart",
      "HorizontalBarChart",
      "GeographyShareChart",
      "OutsideSpendingChart",
      "CashOnHandTrendChart",
      "ComparisonBar"
    ]);
  });

  test("person chart disclosures expose exact fixture facts", async ({ page }: { page: Page }) => {
    await page.goto(`/person/${SMOKE_PERSON_ID}`);

    for (const chartCase of personChartCases()) {
      await test.step(chartCase.owner, async () => {
        const chart = page.getByTestId(chartCase.testId);
        await expect(chart).toBeVisible();
        const snapshot = await openChartDataAndSnapshot(chart);
        expectExactAccessibleRows(snapshot, chartCase.rows);
      });
    }
  });

  test("committee cash-on-hand disclosure exposes exact filing-period facts", async ({
    page
  }: {
    page: Page;
  }) => {
    await page.goto(`/committee/${SMOKE_COMMITTEE_SLUG}`);

    const chartCase = chartCaseForRoute("committee");
    const chart = page.getByTestId(chartCase.testId);
    await expect(chart).toBeVisible();
    const snapshot = await openChartDataAndSnapshot(chart);
    expectExactAccessibleRows(snapshot, chartCase.rows);
  });

  test("Congress comparison exposes its canonical label and compact value", async ({
    page
  }: {
    page: Page;
  }) => {
    await page.goto("/congress");

    const comparisonCase = chartCaseForRoute("congress");
    const comparison = page
      .getByTestId("congress-member-row-0")
      .getByTestId(comparisonCase.testId);
    // Retain the scoped comparison-container accessibility snapshot as the tree
    // proof, but assert the label and end label as distinct exact nodes below so
    // neither the portrait's `img "Portrait of ..."` alt text nor a regressed
    // `$300.00` money-summary string can satisfy the ComparisonBar contract.
    const snapshot = await comparison.ariaSnapshot();

    // The canonical name must appear as the ComparisonBar's own link node — the
    // portrait exposes the same name only through `img` alt text, so a `link`
    // role with the exact name cannot be satisfied by the portrait.
    await expect(
      comparison.getByRole("link", { name: SMOKE_PERSON_CANONICAL_NAME, exact: true })
    ).toHaveCount(1);
    expect(snapshot).toContain(`link "${SMOKE_PERSON_CANONICAL_NAME}"`);

    // The independently pinned compact value rejects the full `$300.00`
    // money-summary text, which only shares the `$300` prefix.
    expectExactAccessibleTextNode(snapshot, SMOKE_CONGRESS_LEADER_TOTAL_RAISED_COMPACT);
    await expect(
      comparison.getByTestId(`comparison-end-label-${SMOKE_CONGRESS_LEADER_PERSON_ID}`)
    ).toHaveText(SMOKE_CONGRESS_LEADER_TOTAL_RAISED_COMPACT);
  });
});

test.describe.serial("live person chart data known-answer smoke", () => {
  test.skip(!SMOKE_USE_LIVE_API, "live-mode only — set SMOKE_USE_LIVE_API=1");

  let cleanupLiveChartSmoke: (() => Promise<void>) | undefined;

  test.beforeAll(async () => {
    cleanupLiveChartSmoke = await seedLiveCongressDirectorySmoke("charts");
  });

  test.afterAll(async () => {
    await cleanupLiveChartSmoke?.();
  });

  test("person money charts paint and expose every exact known-answer row", async ({
    page
  }: {
    page: Page;
  }) => {
    await page.goto(`/person/${SMOKE_CHART_LIVE_PERSON_ID}`);

    for (const chartCase of personChartCases()) {
      await test.step(chartCase.owner, async () => {
        const chartFrame = page.getByTestId(chartCase.testId);
        await expect(chartFrame).toBeVisible({ timeout: 15_000 });

        const paintedChart = await chartRegion(page, chartCase.paintLabel);
        await expect(paintedChart).toBeVisible();
        await expectRealChartRender(paintedChart, BAR_SERIES_MARK_SELECTOR);

        const snapshot = await openChartDataAndSnapshot(chartFrame);
        expectExactAccessibleRows(snapshot, chartCase.rows);
      });
    }
  });
});
