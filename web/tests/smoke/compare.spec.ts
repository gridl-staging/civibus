import { expect, test } from "playwright/test";
import type { Locator, Page } from "playwright";
import {
  BACKEND_FAILURE_STATE_COPY,
  BAR_SERIES_MARK_SELECTOR,
  expectNoBackendFailureStates,
  expectNoChartFrameOverflow,
  expectNoHorizontalOverflow,
  expectNonZeroChartBox,
  expectRealChartRender
} from "./smoke-helpers";
import {
  compareExpectedChartScales,
  compareMetricRows,
  compareNationalGeographyCopy,
  compareNoItemizedCopy,
  compareNoSummaryCopy,
  compareOfficeholders,
  compareUnknownPersonId
} from "./compare-fixtures";
import { SMOKE_USE_LIVE_API } from "./fixtures";

const [delayedOfficeholder, nationalOfficeholder, noDataOfficeholder, errorOfficeholder] =
  compareOfficeholders;
const usesFixtureBackend = process.env.SMOKE_MODE !== "production" && !SMOKE_USE_LIVE_API;
const fairnessCopy =
  "Compare each officeholder within that person's selected cycle, using official FEC summaries when available and itemized records where summaries are not yet loaded.";
const provenanceCopy =
  "Campaign finance data comes from the Federal Election Commission; entity details link to their source records when available.";

test.describe("officeholder compare fixture smoke", () => {
  test.skip(!usesFixtureBackend, "fixture-only — deterministic delay, error, and money totals");

  test("person detail Compare action reaches the one-person add-officeholder state", async ({
    page
  }: {
    page: Page;
  }) => {
    await page.goto(`/person/${delayedOfficeholder.id}`);
    await expect(
      page.getByRole("heading", { name: delayedOfficeholder.name, level: 2 })
    ).toBeVisible();

    await page.getByRole("link", { name: "Compare", exact: true }).click();

    await expectPeopleQuery(page, [delayedOfficeholder.id]);
    await expectComparePage(page);
    await expect(
      page.getByText("Choose at least two officeholders to compare campaign finance.", {
        exact: true
      })
    ).toBeVisible();
  });

  test("visible add, remove, and four-person controls keep canonical URL state", async ({
    page
  }: {
    page: Page;
  }) => {
    await page.goto(`/compare?people=${delayedOfficeholder.id}`);
    await addOfficeholder(page, nationalOfficeholder);
    await expectPeopleQuery(page, [delayedOfficeholder.id, nationalOfficeholder.id]);

    await addOfficeholder(page, noDataOfficeholder);
    await expectPeopleQuery(page, [
      delayedOfficeholder.id,
      nationalOfficeholder.id,
      noDataOfficeholder.id
    ]);
    await addOfficeholder(page, errorOfficeholder);
    await expectPeopleQuery(page, compareOfficeholders.map(({ id }) => id));

    await expect(page.getByLabel("Add officeholder")).toBeDisabled();
    await expect(page.getByRole("button", { name: "Search", exact: true })).toBeDisabled();
    await expect(page.getByRole("list", { name: "Officeholder search results" })).toHaveCount(0);
    await expect(
      page.getByText("Remove an officeholder before adding another comparison column.", {
        exact: true
      })
    ).toBeVisible();

    await page
      .getByRole("link", { name: `Remove ${nationalOfficeholder.name}`, exact: true })
      .click();
    await expectPeopleQuery(
      page,
      compareOfficeholders.filter(({ id }) => id !== nationalOfficeholder.id).map(({ id }) => id)
    );
    await expect(page.getByLabel("Add officeholder")).toBeEnabled();
  });

  test("duplicate, unknown, and over-cap URLs canonicalize without route errors", async ({
    page
  }: {
    page: Page;
  }) => {
    await page.goto(
      `/compare?people=${delayedOfficeholder.id},${delayedOfficeholder.id}`
    );
    await expectPeopleQuery(page, [delayedOfficeholder.id]);
    await expectComparePage(page);

    await page.goto(
      `/compare?people=${delayedOfficeholder.id},${compareUnknownPersonId}`
    );
    await expectPeopleQuery(page, [delayedOfficeholder.id]);
    await expect(page).toHaveURL(/notice=unknown-people-dropped/);
    await expect(
      page.getByText("Some requested officeholders could not be found and were removed.", {
        exact: true
      })
    ).toBeVisible();
    await expectComparePage(page);

    await page.goto(
      `/compare?people=${[...compareOfficeholders.map(({ id }) => id), compareUnknownPersonId].join(",")}`
    );
    await expectPeopleQuery(page, compareOfficeholders.map(({ id }) => id));
    await expect(page).toHaveURL(/notice=max-4/);
    await expect(
      page.getByText("Only the first four officeholders can be compared at once.", { exact: true })
    ).toBeVisible();
    await expectComparePage(page);
  });

  test("delayed money renders per-column skeletons before the settled comparison", async ({
    page
  }: {
    page: Page;
  }) => {
    await page.goto(
      `/compare?people=${nationalOfficeholder.id},${delayedOfficeholder.id}`
    );
    const removeNationalOfficeholder = page
      .getByRole("link", { name: `Remove ${nationalOfficeholder.name}`, exact: true })
      .click();

    const delayedColumn = page.getByLabel(`Compare column for ${delayedOfficeholder.name}`);
    await expect(
      delayedColumn.getByLabel("Campaign finance column loading", { exact: true })
    ).toBeVisible();
    await expect(page.getByLabel("Comparison loading columns", { exact: true })).toBeVisible();

    await removeNationalOfficeholder;
    await expectPeopleQuery(page, [delayedOfficeholder.id]);
    await expect(page.getByLabel("Headline totals", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Comparison loading columns", { exact: true })).toHaveCount(0);
    await expectVisibleFootnotes(page);
  });

  test("error, no-data, and national-geography states stay isolated by column", async ({
    page
  }: {
    page: Page;
  }) => {
    await page.goto(
      `/compare?people=${nationalOfficeholder.id},${noDataOfficeholder.id},${errorOfficeholder.id}`
    );
    await expectComparePage(page);

    const nationalColumn = page.getByLabel(`Compare column for ${nationalOfficeholder.name}`);
    const noDataColumn = page.getByLabel(`Compare column for ${noDataOfficeholder.name}`);
    const errorColumn = page.getByLabel(`Compare column for ${errorOfficeholder.name}`);

    await expect(nationalColumn.getByText(compareNationalGeographyCopy, { exact: true })).toBeVisible();
    await expect(noDataColumn.getByText(compareNationalGeographyCopy, { exact: true })).toHaveCount(0);
    await expect(errorColumn.getByText(compareNationalGeographyCopy, { exact: true })).toHaveCount(0);
    await expect(noDataColumn.getByText(compareNoItemizedCopy, { exact: true })).toBeVisible();
    await expect(noDataColumn.getByText(compareNoSummaryCopy, { exact: true })).toBeVisible();
    await expect(noDataColumn.getByTestId(`compare-${noDataOfficeholder.id}-monthly`)).toHaveCount(0);
    await expect(noDataColumn.getByText("$0.00", { exact: true })).toHaveCount(0);
    await expect(
      errorColumn.getByText("Campaign finance data is unavailable for this person.", {
        exact: true
      })
    ).toBeVisible();
    await expect(nationalColumn.getByTestId(`compare-${nationalOfficeholder.id}-monthly`)).toBeVisible();
    await expectVisibleFootnotes(page);
  });

  // Control pair for expectNoBackendFailureStates, which the production gate relies on to
  // notice a backend outage. The person page degrades gracefully when a money call fails
  // (see fallbackWhenBackendSelectedInsightsUnavailable in person-money-bundle.ts), so an
  // outage renders as calm "temporarily unavailable" copy rather than an error — and the
  // production visuals spec counts that copy as a passing "truthful no-data" state. This
  // test pins both directions so the detector cannot silently stop discriminating:
  // it must stay quiet for a healthy person and it must see the failure copy for a
  // person whose contribution-insights call returns 503 (errorOfficeholder's fixture).
  test("backend-failure detector sees a failing money backend but stays quiet when healthy", async ({
    page
  }: {
    page: Page;
  }) => {
    // Healthy person: no failure copy anywhere, so the production assertion is meaningful
    // rather than vacuously true.
    await page.goto(`/person/${nationalOfficeholder.id}`);
    await expect(page.getByRole("heading", { name: "Campaign finance" })).toBeVisible();
    await expectNoBackendFailureStates(page);

    // Failing person: same detector must fire. This is what would have caught the
    // 2026-07-17 zcta_district.boundary_year schema drift, which broke contribution
    // insights in production while every existing gate stayed green.
    await page.goto(`/person/${errorOfficeholder.id}`);
    await expect(page.getByRole("heading", { name: "Campaign finance" })).toBeVisible();
    await expect(page.getByText(BACKEND_FAILURE_STATE_COPY).first()).toBeVisible();
  });

  for (const width of [1440, 768, 390]) {
    test(`three-column comparison remains dense and truthful at ${width}px`, async ({
      page
    }: {
      page: Page;
    }) => {
      await page.setViewportSize({ width, height: 1000 });
      const selectedOfficeholders = [
        delayedOfficeholder,
        nationalOfficeholder,
        noDataOfficeholder
      ];
      await page.goto(
        `/compare?people=${selectedOfficeholders.map(({ id }) => id).join(",")}`
      );
      await expectComparePage(page);
      await expect(page.getByLabel("Headline totals", { exact: true })).toBeVisible();

      await expectComparisonRows(page, selectedOfficeholders);
      await expectSharedChartScales(page, [delayedOfficeholder, nationalOfficeholder]);
      await expectCompareCharts(page, [delayedOfficeholder, nationalOfficeholder]);
      await expect(
        page
          .getByLabel(`Compare column for ${noDataOfficeholder.name}`)
          .getByText(compareNoItemizedCopy, { exact: true })
      ).toBeVisible();
      await expectVisibleFootnotes(page);
      await expectNoChartFrameOverflow(
        selectedOfficeholders.map((officeholder) =>
          page.getByLabel(`Compare column for ${officeholder.name}`)
        )
      );
      await expectNoHorizontalOverflow(page);
    });
  }
});

async function expectComparePage(page: Page): Promise<void> {
  await expect(page.getByRole("heading", { name: "Compare officeholders", exact: true })).toBeVisible();
  await expect(page.getByLabel("Officeholder comparison", { exact: true })).toBeVisible();
  await expect(page.getByText("Backend compare request failed.", { exact: true })).toHaveCount(0);
}

async function expectPeopleQuery(page: Page, expectedIds: readonly string[]): Promise<void> {
  await expect
    .poll(() => new URL(page.url()).searchParams.get("people"))
    .toBe([...expectedIds].sort().join(","));
}

async function addOfficeholder(
  page: Page,
  officeholder: (typeof compareOfficeholders)[number]
): Promise<void> {
  await page.getByLabel("Add officeholder").fill(officeholder.searchQuery);
  await page.getByRole("button", { name: "Search", exact: true }).click();
  const results = page.getByRole("list", { name: "Officeholder search results" });
  await expect(results.getByRole("link", { name: officeholder.name, exact: true })).toBeVisible();
  const addSelectedOfficeholder = results
    .getByRole("link", { name: officeholder.name, exact: true })
    .click();
  const loadingColumns = page.getByLabel("Comparison loading columns", { exact: true });
  await expect(loadingColumns).toBeVisible();
  await addSelectedOfficeholder;
  await expect(loadingColumns).toHaveCount(0);
  await expect
    .poll(() => new URL(page.url()).searchParams.get("people")?.split(",") ?? [])
    .toContain(officeholder.id);
  await expect(results).toHaveCount(0);
  await expect(
    page.getByRole("link", { name: `Remove ${officeholder.name}`, exact: true })
  ).toBeVisible();
  await expect(page.getByLabel("Headline totals", { exact: true })).toBeVisible();
}

async function expectVisibleFootnotes(page: Page): Promise<void> {
  const footnotes = page.getByLabel("Comparison footnotes", { exact: true });
  await expect(footnotes.getByText(fairnessCopy, { exact: true })).toBeVisible();
  await expect(footnotes.getByText(provenanceCopy, { exact: true })).toBeVisible();
}

async function expectComparisonRows(
  page: Page,
  officeholders: readonly (typeof compareOfficeholders)[number][]
): Promise<void> {
  for (const [rowIndex, metric] of compareMetricRows.entries()) {
    await expect(page.getByRole("heading", { name: metric.label, exact: true })).toBeVisible();
    for (const officeholder of officeholders) {
      const row = page.getByTestId(`comparison-row-${officeholder.id}`).nth(rowIndex);
      const endLabel = page
        .getByTestId(`comparison-end-label-${officeholder.id}`)
        .nth(rowIndex);
      await expect(row).toBeVisible();
      await expect(endLabel).toHaveText(officeholder.expectedTotals[metric.id]);
      await expectLocatorContained(row, endLabel);

      const bars = page.getByTestId(`comparison-bar-${officeholder.id}`);
      if (officeholder === noDataOfficeholder) {
        await expect(bars).toHaveCount(0);
        continue;
      }
      const bar = bars.nth(rowIndex);
      await expect(bar).toBeVisible();
      await expectLocatorContained(row, bar);
    }
  }
}

async function expectSharedChartScales(
  page: Page,
  officeholders: readonly (typeof compareOfficeholders)[number][]
): Promise<void> {
  const { monthlyContributions, sizeBucketDollars, outsideSpending } =
    compareExpectedChartScales;
  for (const officeholder of officeholders) {
    const column = page.getByLabel(`Compare column for ${officeholder.name}`);
    await expect(
      column.getByText(`Shared scale maximum: ${monthlyContributions.label}`, { exact: true })
    ).toBeVisible();
    await expect(
      column.getByText(`Shared scale maximum: ${sizeBucketDollars.label}`, { exact: true })
    ).toBeVisible();
    await expect(
      column.getByText(`Shared scale maximum: ${outsideSpending.label}`, { exact: true })
    ).toBeVisible();
    await expect(page.getByTestId(`compare-${officeholder.id}-monthly-plot`)).toHaveAttribute(
      "data-domain-max",
      String(monthlyContributions.value)
    );
    await expect(page.getByTestId(`compare-${officeholder.id}-size-plot`)).toHaveAttribute(
      "data-domain-max",
      String(sizeBucketDollars.value)
    );
    const outsidePlot = page.getByTestId(`compare-${officeholder.id}-outside-spending-plot`);
    await expect(outsidePlot).toHaveAttribute("data-domain-max", String(outsideSpending.value));
  }
}

async function expectCompareCharts(
  page: Page,
  officeholders: readonly (typeof compareOfficeholders)[number][]
): Promise<void> {
  for (const officeholder of officeholders) {
    for (const chartSuffix of ["monthly", "size", "geography", "outside-spending"]) {
      const chart = page.getByTestId(`compare-${officeholder.id}-${chartSuffix}`);
      await expect(chart).toBeVisible();
      await expectNonZeroChartBox(chart, BAR_SERIES_MARK_SELECTOR);
      await expectRealChartRender(chart, BAR_SERIES_MARK_SELECTOR);
    }
  }
}

async function expectLocatorContained(container: Locator, child: Locator): Promise<void> {
  const containerBox = await container.boundingBox();
  const childBox = await child.boundingBox();
  expect(containerBox).not.toBeNull();
  expect(childBox).not.toBeNull();
  if (containerBox === null || childBox === null) {
    return;
  }
  expect(childBox.x).toBeGreaterThanOrEqual(containerBox.x - 1);
  expect(childBox.y).toBeGreaterThanOrEqual(containerBox.y - 1);
  expect(childBox.x + childBox.width).toBeLessThanOrEqual(
    containerBox.x + containerBox.width + 1
  );
  expect(childBox.y + childBox.height).toBeLessThanOrEqual(
    containerBox.y + containerBox.height + 1
  );
}
