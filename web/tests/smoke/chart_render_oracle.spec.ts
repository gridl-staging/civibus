import { expect, test } from "playwright/test";
import type { Page } from "playwright";

import {
  SMOKE_PERSON_CANONICAL_NAME,
  SMOKE_PERSON_DONATION_COUNT_BY_SIZE_HEADING,
  SMOKE_PERSON_DONATIONS_OVER_TIME_HEADING,
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
    await page.goto(`/person/${SMOKE_PERSON_ID}`);

    const lineChartRegion = await chartRegion(
      page,
      `${SMOKE_PERSON_DONATIONS_OVER_TIME_HEADING} for ${SMOKE_PERSON_CANONICAL_NAME}`
    );
    const barChartRegion = await chartRegion(
      page,
      `${SMOKE_PERSON_DONATION_COUNT_BY_SIZE_HEADING} for ${SMOKE_PERSON_CANONICAL_NAME}`
    );
    await expect(lineChartRegion).toBeVisible();
    await expect(barChartRegion).toBeVisible();

    await expectRealChartRender(lineChartRegion, LINE_SERIES_MARK_SELECTOR);
    await expectRealChartRender(barChartRegion, BAR_SERIES_MARK_SELECTOR);
    await expectNoOpaqueNearBlackPaints([lineChartRegion, barChartRegion]);
  });
});
