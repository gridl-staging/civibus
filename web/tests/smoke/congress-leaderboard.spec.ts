import { expect, test } from "playwright/test";
import type { Locator, Page } from "playwright";

import {
  SMOKE_CONGRESS_LEADER_CASH_ON_HAND,
  SMOKE_CONGRESS_LEADER_NAME,
  SMOKE_CONGRESS_LEADER_OUTSIDE_AGAINST,
  SMOKE_CONGRESS_LEADER_OUTSIDE_SUPPORT,
  SMOKE_CONGRESS_LEADER_PERSON_ID,
  SMOKE_CONGRESS_LEADER_SOURCE_HREF,
  SMOKE_CONGRESS_LEADER_TOTAL_RAISED,
  SMOKE_CONGRESS_NO_MONEY_NAME,
  SMOKE_CONGRESS_SECOND_CASH_ON_HAND,
  SMOKE_CONGRESS_SECOND_NAME,
  SMOKE_CONGRESS_SECOND_OUTSIDE_AGAINST,
  SMOKE_CONGRESS_SECOND_OUTSIDE_SUPPORT,
  SMOKE_CONGRESS_SECOND_PERSON_ID,
  SMOKE_CONGRESS_SECOND_SOURCE_HREF,
  SMOKE_CONGRESS_SECOND_TOTAL_RAISED
} from "./fixtures";
import { capturePageLoadErrors } from "./smoke-helpers";

const NO_REPORTED_MONEY = "No reported/loaded money.";

function memberRows(page: Page): Locator {
  return page.getByTestId(/^congress-member-row-/);
}

async function expectMemberOrder(page: Page, expectedNames: string[]): Promise<void> {
  const rows = memberRows(page);
  await expect(rows).toHaveCount(expectedNames.length);
  for (const [index, name] of expectedNames.entries()) {
    await expect(rows.nth(index)).toContainText(name);
  }
}

function rowForMember(page: Page, memberName: string): Locator {
  return memberRows(page).filter({ hasText: memberName });
}

async function expectLinkedMoney(row: Locator, amount: string, sourceHref: string): Promise<void> {
  await expect(row.getByRole("link", { name: amount, exact: true })).toHaveAttribute("href", sourceHref);
}

async function comparisonWidthPercent(page: Page, personId: string): Promise<number> {
  const inlineStyle = await page.getByTestId(`comparison-bar-${personId}`).getAttribute("style");
  const width = inlineStyle?.match(/--comparison-track-width:\s*([\d.]+)%/)?.[1];
  return Number.parseFloat(width ?? "NaN");
}

test("/congress renders a URL-owned money leaderboard and canonical compare handoff", async ({ page }: { page: Page }) => {
  const pageLoadErrors = capturePageLoadErrors(page);

  await page.goto("/congress");

  await expect(page.getByRole("heading", { name: "Congress" })).toBeVisible();
  await expect(page.getByTestId("congress-result-count")).toHaveText("3 members");
  await expect(page.getByRole("link", { name: SMOKE_CONGRESS_LEADER_NAME, exact: true })).toBeVisible();
  await expectMemberOrder(page, [
    SMOKE_CONGRESS_LEADER_NAME,
    SMOKE_CONGRESS_SECOND_NAME,
    SMOKE_CONGRESS_NO_MONEY_NAME
  ]);

  const leaderRow = rowForMember(page, SMOKE_CONGRESS_LEADER_NAME);
  await expectLinkedMoney(leaderRow, SMOKE_CONGRESS_LEADER_TOTAL_RAISED, SMOKE_CONGRESS_LEADER_SOURCE_HREF);
  await expectLinkedMoney(leaderRow, SMOKE_CONGRESS_LEADER_OUTSIDE_SUPPORT, SMOKE_CONGRESS_LEADER_SOURCE_HREF);
  await expectLinkedMoney(leaderRow, SMOKE_CONGRESS_LEADER_OUTSIDE_AGAINST, SMOKE_CONGRESS_LEADER_SOURCE_HREF);
  await expectLinkedMoney(leaderRow, SMOKE_CONGRESS_LEADER_CASH_ON_HAND, SMOKE_CONGRESS_LEADER_SOURCE_HREF);

  const secondRow = rowForMember(page, SMOKE_CONGRESS_SECOND_NAME);
  await expectLinkedMoney(secondRow, SMOKE_CONGRESS_SECOND_TOTAL_RAISED, SMOKE_CONGRESS_SECOND_SOURCE_HREF);
  await expectLinkedMoney(secondRow, SMOKE_CONGRESS_SECOND_OUTSIDE_SUPPORT, SMOKE_CONGRESS_SECOND_SOURCE_HREF);
  await expectLinkedMoney(secondRow, SMOKE_CONGRESS_SECOND_OUTSIDE_AGAINST, SMOKE_CONGRESS_SECOND_SOURCE_HREF);
  await expectLinkedMoney(secondRow, SMOKE_CONGRESS_SECOND_CASH_ON_HAND, SMOKE_CONGRESS_SECOND_SOURCE_HREF);
  await expect(rowForMember(page, SMOKE_CONGRESS_NO_MONEY_NAME).getByText(NO_REPORTED_MONEY, { exact: true })).toBeVisible();

  const leaderWidth = await comparisonWidthPercent(page, SMOKE_CONGRESS_LEADER_PERSON_ID);
  const secondWidth = await comparisonWidthPercent(page, SMOKE_CONGRESS_SECOND_PERSON_ID);
  expect(leaderWidth).toBeCloseTo(100, 8);
  expect(leaderWidth / secondWidth).toBeCloseTo(3, 8);

  const sort = page.getByTestId("congress-money-sort");
  await sort.selectOption("outside_against");
  await expect(page).toHaveURL(/\/congress\?sort=outside_against$/);
  await expectMemberOrder(page, [
    SMOKE_CONGRESS_SECOND_NAME,
    SMOKE_CONGRESS_LEADER_NAME,
    SMOKE_CONGRESS_NO_MONEY_NAME
  ]);

  await page.getByTestId("congress-search").fill("Alex Money");
  await expect(page).toHaveURL(/\/congress\?sort=outside_against&search=Alex\+Money$/);
  await expect(page.getByTestId("congress-result-count")).toHaveText("1 member");
  await page.goBack();
  await expect(page).toHaveURL(/\/congress\?sort=outside_against$/);
  await expect(sort).toHaveValue("outside_against");
  await expect(page.getByTestId("congress-search")).toHaveValue("");
  await expectMemberOrder(page, [
    SMOKE_CONGRESS_SECOND_NAME,
    SMOKE_CONGRESS_LEADER_NAME,
    SMOKE_CONGRESS_NO_MONEY_NAME
  ]);
  await page.goBack();
  await expect(page).toHaveURL(/\/congress$/);
  await expect(sort).toHaveValue("total_raised");

  const compareButton = page.getByRole("button", { name: "Compare selected (2–4)" });
  await expect(compareButton).toBeDisabled();
  await page.getByRole("checkbox", { name: `Select ${SMOKE_CONGRESS_SECOND_NAME} for comparison` }).check();
  await expect(compareButton).toBeDisabled();
  await page.getByRole("checkbox", { name: `Select ${SMOKE_CONGRESS_LEADER_NAME} for comparison` }).check();
  await expect(compareButton).toBeEnabled();
  await pageLoadErrors.assertNoErrors();
  await compareButton.click();
  await expect(page).toHaveURL(
    `/compare?people=${SMOKE_CONGRESS_LEADER_PERSON_ID},${SMOKE_CONGRESS_SECOND_PERSON_ID}`
  );
});
