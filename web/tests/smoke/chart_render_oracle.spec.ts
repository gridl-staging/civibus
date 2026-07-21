import { expect, test } from "playwright/test";
import type { Page } from "playwright";

import {
  SMOKE_COMMITTEE_SLUG,
  SMOKE_PERSON_ID
} from "./fixtures";
import {
  BAR_SERIES_MARK_SELECTOR,
  LINE_SERIES_MARK_SELECTOR,
  chartRegion,
  expectNoOpaqueNearBlackPaints,
  expectRealChartRender
} from "./smoke-helpers";

test.describe("chart render oracle", () => {
  test("line chart proof targets a LayerChart series path instead of generic SVG scaffolding", () => {
    expect(LINE_SERIES_MARK_SELECTOR).toBe("svg path.lc-path");
  });

  test("real chart package line and bar renders do not paint opaque near-black SVG rectangles", async ({
    page
  }: {
    page: Page;
  }) => {
    await page.goto(`/committee/${SMOKE_COMMITTEE_SLUG}`);
    const lineChartRegion = await chartRegion(page, "Cash on hand trend by filing period");
    await expect(lineChartRegion).toBeVisible();
    await expectRealChartRender(lineChartRegion, LINE_SERIES_MARK_SELECTOR);
    await expectNoOpaqueNearBlackPaints(lineChartRegion);

    await page.goto(`/person/${SMOKE_PERSON_ID}`);
    const barChartRegion = await chartRegion(page, "Itemized contribution-size buckets bar chart");
    await expect(barChartRegion).toBeVisible();
    await expectRealChartRender(barChartRegion, BAR_SERIES_MARK_SELECTOR);
    await expectNoOpaqueNearBlackPaints(barChartRegion);
  });
});
