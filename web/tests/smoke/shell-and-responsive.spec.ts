import { expect, test } from "playwright/test";

import {
  SMOKE_CANDIDATE_ID,
  SMOKE_CANDIDATE_NAME,
  SMOKE_COMMITTEE_SLUG,
  SMOKE_HOME_DESCRIPTION,
  SMOKE_HOME_HEADING,
  SMOKE_HOME_TITLE,
  SMOKE_HOME_COVERAGE_HEADING,
  SMOKE_HOME_COVERAGE_SUMMARY,
  SMOKE_METHODOLOGY_CONFIDENCE_HEADING,
  SMOKE_METHODOLOGY_DESCRIPTION,
  SMOKE_METHODOLOGY_SECTION_BODY,
  SMOKE_METHODOLOGY_SECTION_HEADING,
  SMOKE_METHODOLOGY_TITLE,
  SMOKE_OFFICE_ID,
  SMOKE_OFFICE_NAME,
  SMOKE_PERSON_CANONICAL_NAME,
  SMOKE_PERSON_ID,
  SMOKE_SEARCH_DESCRIPTION,
  SMOKE_SEARCH_EMPTY_DESCRIPTION,
  SMOKE_SEARCH_EMPTY_TITLE,
  SMOKE_SEARCH_QUERY,
  SMOKE_SEARCH_RESULT_NAME,
  SMOKE_SEARCH_TITLE,
  SMOKE_SHELL_NAV_CANDIDATES,
  SMOKE_SHELL_NAV_COMMITTEES,
  SMOKE_SHELL_NAV_HOME,
  SMOKE_SHELL_NAV_METHODOLOGY,
  SMOKE_SHELL_NAV_SEARCH,
  SMOKE_TECHNICAL_DISCLOSURE_SUMMARY
} from "./fixtures";
import {
  assertPrimaryNavLink,
  assertPrimaryNavTapTargetMinHeight,
  assertSearchHead,
  assertSeoHead
} from "./smoke-helpers";

test.describe("shell and responsive smoke", () => {
  test("/ renders landing coverage and navigates to /search", async ({ page }: { page: any }) => {
    await page.goto("/");

    await expect(page).toHaveTitle(SMOKE_HOME_TITLE);
    await expect(page.locator('meta[name="description"]')).toHaveAttribute("content", SMOKE_HOME_DESCRIPTION);
    await assertSeoHead(page, {
      title: SMOKE_HOME_TITLE,
      description: SMOKE_HOME_DESCRIPTION,
      ogType: "website",
      jsonLdCount: 1
    });
    await expect(page.getByRole("heading", { name: "Civibus" })).toBeVisible();
    await expect(page.getByRole("heading", { name: SMOKE_HOME_HEADING })).toBeVisible();
    await expect(page.getByRole("heading", { name: SMOKE_HOME_COVERAGE_HEADING })).toBeVisible();
    await expect(page.getByText(SMOKE_HOME_COVERAGE_SUMMARY)).toBeVisible();
    await assertPrimaryNavLink(page, SMOKE_SHELL_NAV_HOME);
    await assertPrimaryNavLink(page, SMOKE_SHELL_NAV_SEARCH);
    await assertPrimaryNavLink(page, SMOKE_SHELL_NAV_CANDIDATES);
    await assertPrimaryNavLink(page, SMOKE_SHELL_NAV_COMMITTEES);
    await assertPrimaryNavLink(page, SMOKE_SHELL_NAV_METHODOLOGY);

    await page.getByRole("link", { name: "Start with search" }).click();

    await expect(page).toHaveURL(/\/search$/);
    await assertSearchHead(page, {
      title: SMOKE_SEARCH_EMPTY_TITLE,
      description: SMOKE_SEARCH_EMPTY_DESCRIPTION
    });
    await expect(page.getByRole("heading", { name: "Search" })).toBeVisible();
    await expect(page.getByText("0 results found.")).toHaveCount(0);
  });

  test("/methodology renders shared shell title and reporting link", async ({ page }: { page: any }) => {
    await page.goto("/methodology");

    await expect(page).toHaveTitle(SMOKE_METHODOLOGY_TITLE);
    await expect(page.locator('meta[name="description"]')).toHaveAttribute(
      "content",
      SMOKE_METHODOLOGY_DESCRIPTION
    );
    await assertSeoHead(page, {
      title: SMOKE_METHODOLOGY_TITLE,
      description: SMOKE_METHODOLOGY_DESCRIPTION,
      ogType: "article",
      jsonLdCount: 1
    });
    await expect(page.getByRole("heading", { name: "Civibus" })).toBeVisible();
    await expect(page.getByRole("heading", { level: 2, name: "Methodology", exact: true })).toBeVisible();
    await expect(page.getByText(SMOKE_METHODOLOGY_SECTION_HEADING)).toBeVisible();
    await expect(page.getByText(SMOKE_METHODOLOGY_SECTION_BODY)).toBeVisible();
    await expect(page.getByText(SMOKE_METHODOLOGY_CONFIDENCE_HEADING)).toBeVisible();
    await expect(page.getByLabel("Methodology").getByRole("link", { name: "Report a data issue" })).toHaveAttribute(
      "href",
      "mailto:team@civibus.org?subject=Civibus%20data%20issue"
    );
  });

  test("/search renders server data from /v1/search", async ({ page }: { page: any }) => {
    await page.goto(`/search?q=${SMOKE_SEARCH_QUERY}&entity_type=org`);

    await assertSearchHead(page, {
      title: SMOKE_SEARCH_TITLE,
      description: SMOKE_SEARCH_DESCRIPTION
    });
    await expect(page.getByRole("heading", { name: "Search" })).toBeVisible();
    await expect(page.getByText("1 result found.")).toBeVisible();
    await expect(page.getByRole("link", { name: SMOKE_SEARCH_RESULT_NAME })).toBeVisible();
  });

  test("narrow viewport keeps empty states readable without two-column detail rows", async ({
    page
  }: {
    page: any;
  }) => {
    await page.setViewportSize({ width: 360, height: 780 });
    await page.goto("/search");
    await expect(page.getByText("Enter at least 2 characters to search.")).toBeVisible();

    await page.goto(`/person/${SMOKE_PERSON_ID}`);
    await expect(page.getByText(SMOKE_TECHNICAL_DISCLOSURE_SUMMARY)).toBeVisible();
    await expect(page.getByRole("term").first()).toHaveText("Canonical name");
    await expect(page.getByRole("definition").first()).toHaveText(SMOKE_PERSON_CANONICAL_NAME);
  });

  test("tablet viewport stacks person detail rows for readability", async ({ page }: { page: any }) => {
    await page.setViewportSize({ width: 768, height: 1024 });
    await page.goto(`/person/${SMOKE_PERSON_ID}`);

    const canonicalTerm = page.getByRole("term").first();
    const canonicalDefinition = page.getByRole("definition").first();
    const termBox = await canonicalTerm.boundingBox();
    const definitionBox = await canonicalDefinition.boundingBox();

    expect(termBox).not.toBeNull();
    expect(definitionBox).not.toBeNull();
    expect(Math.abs((termBox?.x ?? 0) - (definitionBox?.x ?? 0))).toBeLessThanOrEqual(4);
  });

  test("small-mobile committee filing table renders inside a horizontal scroll container", async ({
    page
  }: {
    page: any;
  }) => {
    await page.setViewportSize({ width: 360, height: 780 });
    await page.goto(`/committee/${SMOKE_COMMITTEE_SLUG}`);

    const filingTableScroll = page.getByTestId("filing-breakdown-scroll");
    await expect(filingTableScroll).toBeVisible();
    await expect(filingTableScroll).toHaveCSS("overflow-x", "auto");
    await expect(filingTableScroll.getByRole("table")).toBeVisible();
  });

  test("responsive viewport 375px keeps home, search, candidate detail, and office detail tap targets accessible", async ({
    page
  }: {
    page: any;
  }) => {
    await page.setViewportSize({ width: 375, height: 812 });

    await page.goto("/");
    await expect(page.getByRole("heading", { name: SMOKE_HOME_HEADING })).toBeVisible();
    await expect(page.getByRole("link", { name: "Start with search" })).toHaveCSS("min-height", "44px");

    await page.goto("/search");
    await expect(page.getByRole("heading", { name: "Search" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Search" })).toHaveCSS("min-height", "44px");

    await page.goto(`/candidate/${SMOKE_CANDIDATE_ID}`);
    await expect(page.getByRole("heading", { name: SMOKE_CANDIDATE_NAME })).toBeVisible();
    await assertPrimaryNavTapTargetMinHeight(page, SMOKE_SHELL_NAV_SEARCH);

    await page.goto(`/office/${SMOKE_OFFICE_ID}`);
    await expect(page.getByRole("heading", { name: SMOKE_OFFICE_NAME })).toBeVisible();
    await assertPrimaryNavTapTargetMinHeight(page, SMOKE_SHELL_NAV_CANDIDATES);
  });

  test("responsive viewport 412px keeps home, search, candidate detail, and office detail tap targets accessible", async ({
    page
  }: {
    page: any;
  }) => {
    await page.setViewportSize({ width: 412, height: 915 });

    await page.goto("/");
    await expect(page.getByRole("heading", { name: SMOKE_HOME_HEADING })).toBeVisible();
    await expect(page.getByRole("link", { name: "Start with search" })).toHaveCSS("min-height", "44px");

    await page.goto("/search");
    await expect(page.getByRole("heading", { name: "Search" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Search" })).toHaveCSS("min-height", "44px");

    await page.goto(`/candidate/${SMOKE_CANDIDATE_ID}`);
    await expect(page.getByRole("heading", { name: SMOKE_CANDIDATE_NAME })).toBeVisible();
    await assertPrimaryNavTapTargetMinHeight(page, SMOKE_SHELL_NAV_SEARCH);

    await page.goto(`/office/${SMOKE_OFFICE_ID}`);
    await expect(page.getByRole("heading", { name: SMOKE_OFFICE_NAME })).toBeVisible();
    await assertPrimaryNavTapTargetMinHeight(page, SMOKE_SHELL_NAV_CANDIDATES);
  });
});
