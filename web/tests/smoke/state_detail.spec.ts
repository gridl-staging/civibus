import { expect, test } from "playwright/test";
import {
  SMOKE_STATE_DETAIL_RETIRED_HEADING,
  SMOKE_STATE_DETAIL_RETIRED_MESSAGE,
  SMOKE_STATE_DETAIL_SUPPORTED_CODE,
  SMOKE_STATE_DETAIL_SUPPORTED_NAME
} from "./fixtures";

test.describe("state detail smoke", () => {
  test("renders retired federal-first v1 state detail route", async ({ page }: { page: any }) => {
    await page.goto(`/state/${SMOKE_STATE_DETAIL_SUPPORTED_CODE}`);
    await expect(page.getByRole("heading", { name: SMOKE_STATE_DETAIL_SUPPORTED_NAME })).toBeVisible();
    await expect(page.getByRole("status").filter({ hasText: SMOKE_STATE_DETAIL_RETIRED_HEADING })).toBeVisible();
    await expect(page.getByText(SMOKE_STATE_DETAIL_RETIRED_MESSAGE)).toBeVisible();
    await expect(page.getByRole("heading", { name: "NC map context" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Reopening state coverage" })).toBeVisible();
    await expect(page.getByTestId("top-candidate-row-0")).toHaveCount(0);
    await expect(page.getByTestId("top-committee-row-0")).toHaveCount(0);
    await expect(page.getByTestId("top-ie-spender-row-0")).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Source and freshness" })).toHaveCount(0);
    await expect(page.getByText("Coverage status:")).toHaveCount(0);
  });

  test("renders the same retired copy for states that previously had warning or unsupported labels", async ({
    page
  }: {
    page: any;
  }) => {
    for (const stateCode of ["AR", "MN", "LA"]) {
      await page.goto(`/state/${stateCode}`);
      await expect(page.getByRole("status").filter({ hasText: SMOKE_STATE_DETAIL_RETIRED_HEADING })).toBeVisible();
      await expect(page.getByText(SMOKE_STATE_DETAIL_RETIRED_MESSAGE)).toBeVisible();
      await expect(page.getByText("Coverage status:")).toHaveCount(0);
    }
  });
});
