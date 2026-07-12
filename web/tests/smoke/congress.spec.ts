import { expect, test } from "playwright/test";

import {
  seedLiveCongressDirectorySmoke,
  SMOKE_CANDIDATE_OPPOSE_TOTAL,
  SMOKE_CANDIDATE_SUPPORT_TOTAL,
  SMOKE_CANDIDATE_TOTAL_RAISED,
  SMOKE_CANDIDATE_TOTAL_SPENT,
  SMOKE_CONGRESS_MEMBER_CONTEXT,
  SMOKE_CONGRESS_PERSON_ID,
  SMOKE_CONGRESS_PORTRAIT_ALT,
  SMOKE_CONGRESS_SEARCH_TERM,
  SMOKE_PERSON_CAMPAIGN_FINANCE_HEADING,
  SMOKE_PERSON_CANONICAL_NAME,
  SMOKE_PERSON_LINKED_COMMITTEES_HEADING,
  SMOKE_PERSON_OUTSIDE_SPENDING_HEADING,
  SMOKE_USE_LIVE_API
} from "./fixtures";
import { capturePageLoadErrors } from "./smoke-helpers";

test.describe("congress directory smoke (live mode)", () => {
  test.skip(!SMOKE_USE_LIVE_API, "live-mode only — set SMOKE_USE_LIVE_API=1");

  test("/congress links to a seeded member detail with federal finance and IE", async ({ page }: { page: any }) => {
    const cleanup = await seedLiveCongressDirectorySmoke();
    const pageLoadErrors = capturePageLoadErrors(page);

    try {
      await page.goto("/congress");

      await expect(page.getByRole("heading", { name: "Congress" })).toBeVisible();
      await expect(page.getByTestId("congress-search")).toBeVisible();
      await expect(page.getByTestId("congress-result-count")).toContainText("member");
      await expect(page.getByRole("link", { name: SMOKE_PERSON_CANONICAL_NAME })).toBeVisible();

      await page.getByTestId("congress-search").fill(SMOKE_CONGRESS_SEARCH_TERM);
      await expect(page.getByTestId("congress-result-count")).toHaveText("1 member");

      const memberRow = page.getByTestId("congress-member-row-0");
      await expect(memberRow).toContainText(SMOKE_PERSON_CANONICAL_NAME);
      await expect(memberRow).toContainText(SMOKE_CONGRESS_MEMBER_CONTEXT);
      await memberRow.getByRole("link", { name: SMOKE_PERSON_CANONICAL_NAME }).click();

      await expect(page).toHaveURL(`/person/${SMOKE_CONGRESS_PERSON_ID}`);
      await expect(page.getByRole("heading", { name: SMOKE_PERSON_CANONICAL_NAME })).toBeVisible();
      await expect(page.getByRole("img", { name: SMOKE_CONGRESS_PORTRAIT_ALT })).toBeVisible();
      await expect(page.getByRole("heading", { name: SMOKE_PERSON_CAMPAIGN_FINANCE_HEADING, exact: true })).toBeVisible();
      await expect(page.getByRole("heading", { name: SMOKE_PERSON_LINKED_COMMITTEES_HEADING, exact: true })).toBeVisible();
      await expect(page.getByRole("heading", { name: SMOKE_PERSON_OUTSIDE_SPENDING_HEADING, exact: true })).toBeVisible();
      await expect(page.getByText(SMOKE_CANDIDATE_TOTAL_RAISED)).toBeVisible();
      await expect(page.getByText(SMOKE_CANDIDATE_TOTAL_SPENT)).toBeVisible();
      await expect(page.getByText(SMOKE_CANDIDATE_SUPPORT_TOTAL)).toBeVisible();
      await expect(page.getByText(SMOKE_CANDIDATE_OPPOSE_TOTAL)).toBeVisible();
      await pageLoadErrors.assertNoErrors();
    } finally {
      await cleanup();
    }
  });
});
