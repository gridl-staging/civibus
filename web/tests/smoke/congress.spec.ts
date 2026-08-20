import { expect, test } from "playwright/test";

import {
  seedLiveCongressDirectorySmoke,
  SMOKE_CANDIDATE_OPPOSE_TOTAL,
  SMOKE_CANDIDATE_SUPPORT_TOTAL,
  SMOKE_CANDIDATE_TOTAL_RAISED,
  SMOKE_CANDIDATE_TOTAL_SPENT,
  SMOKE_CONGRESS_MEMBER_CONTEXT,
  SMOKE_CONGRESS_PERSON_CANONICAL_NAME,
  SMOKE_CONGRESS_PERSON_ID,
  SMOKE_CONGRESS_PORTRAIT_ALT,
  SMOKE_CONGRESS_SEARCH_TERM,
  SMOKE_PERSON_CAMPAIGN_FINANCE_HEADING,
  SMOKE_PERSON_LINKED_COMMITTEES_HEADING,
  SMOKE_PERSON_OUTSIDE_SPENDING_HEADING,
  SMOKE_USE_LIVE_API
} from "./fixtures";
import { capturePageLoadErrors, escapeRegExp } from "./smoke-helpers";

/**
 * The <dd> whose whole text is `value`.
 *
 * Outside-spending amounts render twice on a member page: once as the stated
 * fact in the definition list, and once inside the chart's own disclosure text.
 * Restricting to the definition role and anchoring the match asserts the figure
 * where the page states it, rather than anywhere it is mentioned - an unanchored
 * getByText resolved both and failed on a strict-mode violation.
 */
function statedAmount(page: any, value: string) {
  return page.getByRole("definition").filter({ hasText: new RegExp(`^${escapeRegExp(value)}$`) });
}

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
      await expect(page.getByRole("link", { name: SMOKE_CONGRESS_PERSON_CANONICAL_NAME })).toBeVisible();

      await page.getByTestId("congress-search").fill(SMOKE_CONGRESS_SEARCH_TERM);
      await expect(page.getByTestId("congress-result-count")).toHaveText("1 member");

      const memberRow = page.getByTestId("congress-member-row-0");
      await expect(memberRow).toContainText(SMOKE_CONGRESS_PERSON_CANONICAL_NAME);
      await expect(memberRow).toContainText(SMOKE_CONGRESS_MEMBER_CONTEXT);
      await memberRow.getByRole("link", { name: SMOKE_CONGRESS_PERSON_CANONICAL_NAME }).click();

      await expect(page).toHaveURL(`/person/${SMOKE_CONGRESS_PERSON_ID}`);
      await expect(page.getByRole("heading", { name: SMOKE_CONGRESS_PERSON_CANONICAL_NAME })).toBeVisible();
      await expect(page.getByRole("img", { name: SMOKE_CONGRESS_PORTRAIT_ALT })).toBeVisible();
      await expect(page.getByRole("heading", { name: SMOKE_PERSON_CAMPAIGN_FINANCE_HEADING, exact: true })).toBeVisible();
      await expect(page.getByRole("heading", { name: SMOKE_PERSON_LINKED_COMMITTEES_HEADING, exact: true })).toBeVisible();
      await expect(page.getByRole("heading", { name: SMOKE_PERSON_OUTSIDE_SPENDING_HEADING, exact: true })).toBeVisible();
      // exact: true on every money assertion. Without it these match any element
      // whose text merely CONTAINS the amount, and the chart frames now render a
      // disclosure sentence ("Receipt components disclose $250.00 in total
      // receipts…") beside the <dd> that carries the figure, so the unanchored
      // locator resolved two elements and failed on a strict-mode violation
      // rather than on anything about the money. Exact matching asserts the
      // figure is its own rendered value, which is what this journey is about.
      // Scoped to the summary panel and matched exactly. Unanchored getByText
      // matched any element merely CONTAINING the amount, so it also resolved the
      // chart frames' disclosure sentence; exact matching alone still resolved the
      // same figure where it recurs as a transaction table cell. Naming the region
      // the journey means asserts more than the loose locator did: the headline
      // total is rendered in the headline panel.
      const moneyAtGlance = page.getByLabel("Money at a glance");
      await expect(moneyAtGlance.getByText(SMOKE_CANDIDATE_TOTAL_RAISED, { exact: true })).toBeVisible();
      await expect(moneyAtGlance.getByText(SMOKE_CANDIDATE_TOTAL_SPENT, { exact: true })).toBeVisible();
      await expect(statedAmount(page, SMOKE_CANDIDATE_SUPPORT_TOTAL)).toBeVisible();
      await expect(statedAmount(page, SMOKE_CANDIDATE_OPPOSE_TOTAL)).toBeVisible();
      await pageLoadErrors.assertNoErrors();
    } finally {
      await cleanup();
    }
  });
});
