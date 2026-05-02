import { expect, test } from "playwright/test";
import {
  SMOKE_LANDING_MAP_UNSUPPORTED_LABEL,
  SMOKE_LANDING_MAP_UNSUPPORTED_STATE_NAME,
  SMOKE_LANDING_MAP_WARNING_STATE_NAME,
  SMOKE_LANDING_MAP_WARNING_TEXT,
  SMOKE_NC_SHOWCASE_COUNTY_DIVISION_NAME
} from "./fixtures";

test.describe("honesty pass", () => {
  test("keeps unsupported states non-clickable from landing map", async ({ page }: { page: any }) => {
    await page.goto("/");
    await expect(page.getByRole("link", { name: SMOKE_LANDING_MAP_UNSUPPORTED_STATE_NAME })).toHaveCount(0);
    await expect(
      page.getByText(`${SMOKE_LANDING_MAP_UNSUPPORTED_STATE_NAME} — ${SMOKE_LANDING_MAP_UNSUPPORTED_LABEL}`)
    ).toBeVisible();
  });

  test("shows warning label copy without overclaiming support", async ({ page }: { page: any }) => {
    await page.goto("/");
    await expect(page.getByText(SMOKE_LANDING_MAP_WARNING_TEXT)).toBeVisible();
    await expect(page.getByRole("link", { name: SMOKE_LANDING_MAP_WARNING_STATE_NAME })).toHaveCount(0);
  });

  test("exposes county click-through only on supported drilldown coverage", async ({ page }: { page: any }) => {
    await page.goto("/state/NC");
    await expect(page.getByRole("link", { name: SMOKE_NC_SHOWCASE_COUNTY_DIVISION_NAME })).toHaveCount(1);
  });
});
