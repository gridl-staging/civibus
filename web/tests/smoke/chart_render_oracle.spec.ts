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
  expectRealChartRender,
  sampleVisibleRectPaints
} from "./smoke-helpers";

test.describe("chart render oracle", () => {
  test("line chart proof targets a LayerChart series path instead of generic SVG scaffolding", () => {
    expect(LINE_SERIES_MARK_SELECTOR).toBe("svg path.lc-path");
  });

  test("bar chart proof targets LayerChart bar paths, not tooltip hit rectangles", () => {
    // civibus-d0o: "svg rect" matched only the transparent lc-tooltip-rect hit
    // areas (a bar chart emits no other rects), so the render oracle proved a
    // tooltip overlay existed, never that a bar painted. Proven un-failable on
    // 2026-08-20: with every bar's value plumbing severed (y forced NaN, all
    // lc-bar path lengths 0), the rect selector still passed this suite.
    expect(BAR_SERIES_MARK_SELECTOR).toBe("svg path.lc-bar");
  });

  test("zero-length LayerChart paths do not count as visible chart paint", async ({
    page
  }: {
    page: Page;
  }) => {
    await page.setContent(`
      <main>
        <section data-testid="empty-chart">
          <svg width="120" height="40" viewBox="0 0 120 40">
            <path class="lc-path" d="" fill="none" stroke="rgb(30, 90, 160)" />
          </svg>
        </section>
        <section data-testid="line-chart">
          <svg width="120" height="40" viewBox="0 0 120 40">
            <path class="lc-path" d="M 4 32 L 116 8" fill="none" stroke="rgb(30, 90, 160)" />
          </svg>
        </section>
      </main>
    `);

    await expect(page.getByTestId("empty-chart")).toBeVisible();
    await expect(page.getByTestId("line-chart")).toBeVisible();

    await expect(sampleVisibleRectPaints(page.getByTestId("empty-chart"))).resolves.toEqual([]);
    await expect(sampleVisibleRectPaints(page.getByTestId("line-chart"))).resolves.toHaveLength(1);
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
    // The bar specimen is the monthly-contributions chart. It used to be the
    // size-buckets chart, but that module's svg was deleted with civibus-3a3 —
    // HorizontalBarChart's one visual encoding is a ranked HTML bar list,
    // covered by expectHtmlBarListRender in the finance-visuals suite.
    const barChartRegion = await chartRegion(page, "Monthly contribution columns");
    await expect(barChartRegion).toBeVisible();
    await expectRealChartRender(barChartRegion, BAR_SERIES_MARK_SELECTOR);
    await expectNoOpaqueNearBlackPaints(barChartRegion);
  });
});
