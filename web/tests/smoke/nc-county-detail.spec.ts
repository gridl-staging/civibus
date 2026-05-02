import { expect, test } from "playwright/test";
import {
  SMOKE_NC_SHOWCASE_COUNTY_HEADING,
  SMOKE_NC_SHOWCASE_COUNTY_SLUG,
  SMOKE_NC_SHOWCASE_DONOR_TOTAL,
  SMOKE_NC_SHOWCASE_RECIPIENT_NAME,
  SMOKE_NC_SHOWCASE_TRUST_SOURCE_NAME
} from "./fixtures";

test.describe("NC county detail smoke", () => {
  test("/state/NC/county/wake renders county heading, map content, and campaign-finance summary", async ({ page }: { page: any }) => {
    await page.goto(`/state/NC/county/${SMOKE_NC_SHOWCASE_COUNTY_SLUG}`);

    await expect(page.getByRole("heading", { name: SMOKE_NC_SHOWCASE_COUNTY_HEADING })).toBeVisible();
    await expect(page.getByRole("region", { name: "Region map" })).toBeVisible();
    await expect(page.getByText("County boundaries:")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Donor total" })).toBeVisible();
    await expect(page.getByText(SMOKE_NC_SHOWCASE_DONOR_TOTAL)).toBeVisible();
    await expect(page.getByRole("heading", { name: "Top recipient committees" })).toBeVisible();
    await expect(page.getByText(SMOKE_NC_SHOWCASE_RECIPIENT_NAME)).toBeVisible();
    await expect(page.getByRole("heading", { name: "Top linked candidates" })).toBeVisible();
    await expect(page.getByText("Casey Example")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Source and freshness" })).toBeVisible();
    await expect(page.getByText(SMOKE_NC_SHOWCASE_TRUST_SOURCE_NAME)).toBeVisible();
  });
});
