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
  SMOKE_CONGRESS_LIVE_LEADER_CASH_ON_HAND,
  SMOKE_CONGRESS_LIVE_LEADER_OUTSIDE_AGAINST,
  SMOKE_CONGRESS_LIVE_LEADER_OUTSIDE_SUPPORT,
  SMOKE_CONGRESS_LIVE_LEADER_SOURCE_HREF,
  SMOKE_CONGRESS_LIVE_LEADER_TOTAL_RAISED,
  SMOKE_CONGRESS_LIVE_SECOND_CASH_ON_HAND,
  SMOKE_CONGRESS_LIVE_SECOND_OUTSIDE_AGAINST,
  SMOKE_CONGRESS_LIVE_SECOND_OUTSIDE_SUPPORT,
  SMOKE_CONGRESS_LIVE_SECOND_SOURCE_HREF,
  SMOKE_CONGRESS_LIVE_SECOND_TOTAL_RAISED,
  SMOKE_CONGRESS_NO_MONEY_NAME,
  SMOKE_CONGRESS_SECOND_CASH_ON_HAND,
  SMOKE_CONGRESS_SECOND_NAME,
  SMOKE_CONGRESS_SECOND_OUTSIDE_AGAINST,
  SMOKE_CONGRESS_SECOND_OUTSIDE_SUPPORT,
  SMOKE_CONGRESS_SECOND_PERSON_ID,
  SMOKE_CONGRESS_SECOND_SOURCE_HREF,
  SMOKE_CONGRESS_SECOND_TOTAL_RAISED,
  SMOKE_USE_LIVE_API
} from "./fixtures";
import { capturePageLoadErrors, parseRenderedMoneyLabel } from "./smoke-helpers";

// One journey, two backends (civibus-8lu). The three members, their ordering
// under both sorts, the URL contract, and the compare handoff are identical in
// both modes because the fixture data mirrors the live seed's people. Only the
// dollar values and money-source hrefs differ, and each backend's seed owns its
// exact numbers: fixture-data.ts for the fixture lane,
// test_support/browser_smoke_seed.py for the live lane.
type MemberMoneyExpectation = {
  totalRaised: string;
  outsideSupport: string;
  outsideAgainst: string;
  cashOnHand: string;
  sourceHref: string;
};
const LEADER_MONEY: MemberMoneyExpectation = SMOKE_USE_LIVE_API
  ? {
      totalRaised: SMOKE_CONGRESS_LIVE_LEADER_TOTAL_RAISED,
      outsideSupport: SMOKE_CONGRESS_LIVE_LEADER_OUTSIDE_SUPPORT,
      outsideAgainst: SMOKE_CONGRESS_LIVE_LEADER_OUTSIDE_AGAINST,
      cashOnHand: SMOKE_CONGRESS_LIVE_LEADER_CASH_ON_HAND,
      sourceHref: SMOKE_CONGRESS_LIVE_LEADER_SOURCE_HREF
    }
  : {
      totalRaised: SMOKE_CONGRESS_LEADER_TOTAL_RAISED,
      outsideSupport: SMOKE_CONGRESS_LEADER_OUTSIDE_SUPPORT,
      outsideAgainst: SMOKE_CONGRESS_LEADER_OUTSIDE_AGAINST,
      cashOnHand: SMOKE_CONGRESS_LEADER_CASH_ON_HAND,
      sourceHref: SMOKE_CONGRESS_LEADER_SOURCE_HREF
    };
const SECOND_MONEY: MemberMoneyExpectation = SMOKE_USE_LIVE_API
  ? {
      totalRaised: SMOKE_CONGRESS_LIVE_SECOND_TOTAL_RAISED,
      outsideSupport: SMOKE_CONGRESS_LIVE_SECOND_OUTSIDE_SUPPORT,
      outsideAgainst: SMOKE_CONGRESS_LIVE_SECOND_OUTSIDE_AGAINST,
      cashOnHand: SMOKE_CONGRESS_LIVE_SECOND_CASH_ON_HAND,
      sourceHref: SMOKE_CONGRESS_LIVE_SECOND_SOURCE_HREF
    }
  : {
      totalRaised: SMOKE_CONGRESS_SECOND_TOTAL_RAISED,
      outsideSupport: SMOKE_CONGRESS_SECOND_OUTSIDE_SUPPORT,
      outsideAgainst: SMOKE_CONGRESS_SECOND_OUTSIDE_AGAINST,
      cashOnHand: SMOKE_CONGRESS_SECOND_CASH_ON_HAND,
      sourceHref: SMOKE_CONGRESS_SECOND_SOURCE_HREF
    };
// The comparison bar encodes total_raised, so the expected width ratio is the
// seed-owned raised amounts' ratio (fixture 300/100 = 3, live 250/100 = 2.5).
const EXPECTED_COMPARISON_RATIO =
  parseRenderedMoneyLabel(LEADER_MONEY.totalRaised) / parseRenderedMoneyLabel(SECOND_MONEY.totalRaised);

const NO_REPORTED_MONEY = "No reported/loaded money.";
const CONGRESS_MEMBER_PROFILE_LINK_TEST_ID = "congress-member-profile-link";

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
  await expect(leaderRow.getByRole("link")).toHaveCount(5);
  await expect(leaderRow.getByTestId(CONGRESS_MEMBER_PROFILE_LINK_TEST_ID)).toHaveAttribute(
    "href",
    `/person/${SMOKE_CONGRESS_LEADER_PERSON_ID}`
  );
  await expectLinkedMoney(leaderRow, LEADER_MONEY.totalRaised, LEADER_MONEY.sourceHref);
  await expectLinkedMoney(leaderRow, LEADER_MONEY.outsideSupport, LEADER_MONEY.sourceHref);
  await expectLinkedMoney(leaderRow, LEADER_MONEY.outsideAgainst, LEADER_MONEY.sourceHref);
  await expectLinkedMoney(leaderRow, LEADER_MONEY.cashOnHand, LEADER_MONEY.sourceHref);

  const secondRow = rowForMember(page, SMOKE_CONGRESS_SECOND_NAME);
  await expectLinkedMoney(secondRow, SECOND_MONEY.totalRaised, SECOND_MONEY.sourceHref);
  await expectLinkedMoney(secondRow, SECOND_MONEY.outsideSupport, SECOND_MONEY.sourceHref);
  await expectLinkedMoney(secondRow, SECOND_MONEY.outsideAgainst, SECOND_MONEY.sourceHref);
  await expectLinkedMoney(secondRow, SECOND_MONEY.cashOnHand, SECOND_MONEY.sourceHref);
  await expect(rowForMember(page, SMOKE_CONGRESS_NO_MONEY_NAME).getByText(NO_REPORTED_MONEY, { exact: true })).toBeVisible();

  const leaderWidth = await comparisonWidthPercent(page, SMOKE_CONGRESS_LEADER_PERSON_ID);
  const secondWidth = await comparisonWidthPercent(page, SMOKE_CONGRESS_SECOND_PERSON_ID);
  expect(leaderWidth).toBeCloseTo(100, 8);
  expect(leaderWidth / secondWidth).toBeCloseTo(EXPECTED_COMPARISON_RATIO, 8);

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
