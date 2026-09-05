import { expect, test } from "playwright/test";
import {
  SMOKE_NC_SHOWCASE_COUNTY_HEADING,
  SMOKE_NC_SHOWCASE_COUNTY_SLUG
} from "./fixtures";

test.describe("NC county detail smoke", () => {
  test("/state/NC/county/wake renders navigation and refuses an unproven county total", async ({ page }: { page: any }) => {
    await page.goto(`/state/NC/county/${SMOKE_NC_SHOWCASE_COUNTY_SLUG}`);

    await expect(page.getByRole("heading", { name: SMOKE_NC_SHOWCASE_COUNTY_HEADING, exact: true })).toBeVisible();
    await expect(page.getByRole("region", { name: "Campaign finance unavailable" })).toBeVisible();
    await expect(page.getByText("No explicit county-wide campaign-finance coverage lineage is available.")).toBeVisible();
    await expect(page.getByRole("region", { name: "NC region map" })).toBeVisible();
    await expect(page.getByText("County boundaries:")).toBeVisible();
    await expect(page.getByRole("region", { name: "Ordinary-locality proxy control" })).toBeVisible();
    await expect(page.getByText(/not combined with state or county-wide totals/i)).toBeVisible();
    await expect(page.getByRole("heading", { name: "Donor total" })).toHaveCount(0);
  });

  test("/state/NC/county/[slug] returns backend 404 behavior for missing county", async ({ page }: { page: any }) => {
    const response = await page.goto("/state/NC/county/not-a-real-county");
    expect(response?.status()).toBe(404);
  });
});
