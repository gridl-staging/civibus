import { expect, test } from "playwright/test";
import {
  SMOKE_LANDING_MAP_WARNING_STATE_NAME,
  SMOKE_STATE_DETAIL_IE_CAVEAT,
  SMOKE_STATE_DETAIL_INCOMPLETE_MAP_LABEL,
  SMOKE_STATE_DETAIL_INCOMPLETE_LABEL,
  SMOKE_STATE_DETAIL_NO_IE_CODE,
  SMOKE_STATE_DETAIL_SUPPORTED_CODE,
  SMOKE_STATE_DETAIL_SUPPORTED_NAME,
  SMOKE_STATE_DETAIL_TOP_CANDIDATE_NAME,
  SMOKE_STATE_DETAIL_TOP_CANDIDATE_TOTAL,
  SMOKE_STATE_DETAIL_TOP_COMMITTEE_NAME,
  SMOKE_STATE_DETAIL_TOP_COMMITTEE_TOTAL,
  SMOKE_STATE_DETAIL_TOP_IE_SPENDER_NAME,
  SMOKE_STATE_DETAIL_TOP_IE_SPENDER_TOTAL,
  SMOKE_STATE_DETAIL_UNSUPPORTED_CODE,
  SMOKE_STATE_DETAIL_UNSUPPORTED_LABEL,
  SMOKE_STATE_DETAIL_UNSUPPORTED_MESSAGE,
  SMOKE_STATE_DETAIL_WARNING_CODE,
  SMOKE_STATE_DETAIL_WARNING_TEXT
} from "./fixtures";

test.describe("state detail smoke", () => {
  test("renders supported state detail route", async ({ page }: { page: any }) => {
    await page.goto(`/state/${SMOKE_STATE_DETAIL_SUPPORTED_CODE}`);
    await expect(
      page.getByRole("heading", {
        name: `${SMOKE_STATE_DETAIL_SUPPORTED_NAME} campaign finance`
      })
    ).toBeVisible();
    await expect(page.getByText("Coverage status:")).toBeVisible();
    await expect(page.getByTestId("top-candidate-row-0")).toContainText(SMOKE_STATE_DETAIL_TOP_CANDIDATE_NAME);
    await expect(page.getByTestId("top-candidate-row-0")).toContainText(SMOKE_STATE_DETAIL_TOP_CANDIDATE_TOTAL);
    await expect(page.getByTestId("top-committee-row-0")).toContainText(SMOKE_STATE_DETAIL_TOP_COMMITTEE_NAME);
    await expect(page.getByTestId("top-committee-row-0")).toContainText(SMOKE_STATE_DETAIL_TOP_COMMITTEE_TOTAL);
    await expect(page.getByTestId("top-ie-spender-row-0")).toContainText(SMOKE_STATE_DETAIL_TOP_IE_SPENDER_NAME);
    await expect(page.getByTestId("top-ie-spender-row-0")).toContainText(SMOKE_STATE_DETAIL_TOP_IE_SPENDER_TOTAL);
  });

  test("returns backend 404 behavior for missing state", async ({ page }: { page: any }) => {
    const response = await page.goto("/state/ZZ");
    expect(response?.status()).toBe(404);
  });

  test("renders unsupported honesty copy", async ({ page }: { page: any }) => {
    await page.goto(`/state/${SMOKE_STATE_DETAIL_UNSUPPORTED_CODE}`);
    await expect(page.getByText(`Coverage status: ${SMOKE_STATE_DETAIL_UNSUPPORTED_LABEL}`)).toBeVisible();
    await expect(page.getByText(SMOKE_STATE_DETAIL_UNSUPPORTED_MESSAGE)).toBeVisible();
  });

  test("renders warning/incomplete messaging", async ({ page }: { page: any }) => {
    await page.goto(`/state/${SMOKE_STATE_DETAIL_WARNING_CODE}`);
    await expect(page.getByText(`Coverage status: ${SMOKE_STATE_DETAIL_INCOMPLETE_LABEL}`)).toBeVisible();
    await expect(
      page.getByText(`${SMOKE_LANDING_MAP_WARNING_STATE_NAME} — ${SMOKE_STATE_DETAIL_INCOMPLETE_MAP_LABEL}`)
    ).toBeVisible();
    await expect(
      page.getByRole("status").filter({ hasText: SMOKE_STATE_DETAIL_WARNING_TEXT })
    ).toBeVisible();
    await expect(page.getByText(SMOKE_STATE_DETAIL_UNSUPPORTED_MESSAGE)).toHaveCount(0);
  });

  test("reuses trust section owner when truthful state-level provenance exists", async ({
    page
  }: {
    page: any;
  }) => {
    await page.goto(`/state/${SMOKE_STATE_DETAIL_SUPPORTED_CODE}`);
    await expect(page.getByRole("heading", { name: "Source and freshness" })).toBeVisible();
    await expect(page.getByText("Last pulled:")).toBeVisible();
    await expect(page.getByText("NC State Campaign Finance (campaign_finance/state/NC)")).toBeVisible();
  });

  test("renders IE caveat for supported states whose source lacks an IE lane", async ({ page }: { page: any }) => {
    await page.goto(`/state/${SMOKE_STATE_DETAIL_NO_IE_CODE}`);
    await expect(
      page.getByRole("status").filter({ hasText: SMOKE_STATE_DETAIL_IE_CAVEAT })
    ).toBeVisible();
    await expect(page.getByText(SMOKE_STATE_DETAIL_UNSUPPORTED_MESSAGE)).toHaveCount(0);
  });
});
