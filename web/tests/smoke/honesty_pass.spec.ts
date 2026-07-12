import { expect, test } from "playwright/test";
import {
  SMOKE_HOME_BODY,
  SMOKE_HOME_COVERAGE_SUMMARY,
  SMOKE_HOME_FORBIDDEN_STATE_ACTION,
  SMOKE_HOME_FORBIDDEN_UNSUPPORTED_LABEL,
  SMOKE_HOME_FORBIDDEN_UNSUPPORTED_STATE,
  SMOKE_HOME_FORBIDDEN_WARNING_STATE,
  SMOKE_HOME_FORBIDDEN_WARNING_TEXT,
  SMOKE_NC_SHOWCASE_COUNTY_DIVISION_NAME
} from "./fixtures";

test.describe("honesty pass", () => {
  test("federal homepage states the bounded federal-only scope", async ({ page }: { page: any }) => {
    await page.goto("/");
    await expect(page.getByText(SMOKE_HOME_BODY)).toBeVisible();
    await expect(page.getByText(SMOKE_HOME_COVERAGE_SUMMARY)).toBeVisible();
  });

  test("does not expose unsupported-state map rows from the federal homepage", async ({ page }: { page: any }) => {
    await page.goto("/");
    await expect(page.getByRole("link", { name: SMOKE_HOME_FORBIDDEN_UNSUPPORTED_STATE })).toHaveCount(0);
    await expect(page.getByRole("link", { name: SMOKE_HOME_FORBIDDEN_STATE_ACTION })).toHaveCount(0);
    await expect(
      page.getByText(`${SMOKE_HOME_FORBIDDEN_UNSUPPORTED_STATE} — ${SMOKE_HOME_FORBIDDEN_UNSUPPORTED_LABEL}`)
    ).toHaveCount(0);
  });

  test("does not expose warning map copy from the federal homepage", async ({ page }: { page: any }) => {
    await page.goto("/");
    await expect(page.getByText(SMOKE_HOME_FORBIDDEN_WARNING_TEXT)).toHaveCount(0);
    await expect(page.getByRole("link", { name: SMOKE_HOME_FORBIDDEN_WARNING_STATE })).toHaveCount(0);
  });

  test("exposes county click-through only on supported drilldown coverage", async ({ page }: { page: any }) => {
    await page.goto("/state/NC");
    await expect(page.getByRole("link", { name: SMOKE_NC_SHOWCASE_COUNTY_DIVISION_NAME })).toHaveCount(1);
  });
});
