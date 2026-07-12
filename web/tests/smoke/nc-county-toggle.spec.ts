import { expect, test } from "playwright/test";
import {
  SMOKE_NC_SHOWCASE_COUNTY_DIVISION_NAME,
  SMOKE_NC_SHOWCASE_COUNTY_HEADING,
  SMOKE_NC_SHOWCASE_COUNTY_SLUG,
  SMOKE_NC_SHOWCASE_DISTRICT_DIVISION_NAME
} from "./fixtures";

test.describe("NC county map toggle smoke", () => {
  test("/state/NC links to county detail and district overlay appears after toggle", async ({ page }: { page: any }) => {
    await page.goto("/state/NC");

    await expect(page.getByRole("heading", { name: "NC map overview" })).toBeVisible();
    await expect(page.getByRole("link", { name: SMOKE_NC_SHOWCASE_COUNTY_DIVISION_NAME })).toHaveAttribute(
      "href",
      `/state/NC/county/${SMOKE_NC_SHOWCASE_COUNTY_SLUG}`
    );
    await expect(page.getByText(SMOKE_NC_SHOWCASE_DISTRICT_DIVISION_NAME)).toHaveCount(0);

    await page.getByRole("checkbox", { name: "Congressional districts" }).check();
    await expect(page.getByText(SMOKE_NC_SHOWCASE_DISTRICT_DIVISION_NAME)).toBeVisible();
    await page.getByRole("checkbox", { name: "Congressional districts" }).uncheck();
    await expect(page.getByText(SMOKE_NC_SHOWCASE_DISTRICT_DIVISION_NAME)).toHaveCount(0);

    await page.getByRole("link", { name: SMOKE_NC_SHOWCASE_COUNTY_DIVISION_NAME }).click();
    await expect(page).toHaveURL(new RegExp(`/state/NC/county/${SMOKE_NC_SHOWCASE_COUNTY_SLUG}$`));
    await expect(page.getByRole("heading", { name: SMOKE_NC_SHOWCASE_COUNTY_HEADING })).toBeVisible();
  });
});
