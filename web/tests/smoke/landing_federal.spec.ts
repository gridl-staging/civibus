import { expect, test } from "playwright/test";

import {
  SMOKE_HOME_ACTION_LABELS,
  SMOKE_HOME_BODY,
  SMOKE_HOME_COVERAGE_HEADING,
  SMOKE_HOME_COVERAGE_SUMMARY,
  SMOKE_HOME_DESCRIPTION,
  SMOKE_HOME_FEDERAL_SCOPE_PHRASE,
  SMOKE_HOME_FORBIDDEN_CANDIDATE_ACTION,
  SMOKE_HOME_FORBIDDEN_COMMITTEE_ACTION,
  SMOKE_HOME_FORBIDDEN_STATE_ACTION,
  SMOKE_HOME_FORBIDDEN_SUPPORTED_STATE,
  SMOKE_HOME_FORBIDDEN_UNSUPPORTED_LABEL,
  SMOKE_HOME_FORBIDDEN_UNSUPPORTED_STATE,
  SMOKE_HOME_FORBIDDEN_WARNING_STATE,
  SMOKE_HOME_FORBIDDEN_WARNING_TEXT,
  SMOKE_HOME_HEADING,
  SMOKE_HOME_METHODOLOGY_ACTION,
  SMOKE_HOME_METHODOLOGY_ACTION_HREF,
  SMOKE_HOME_PRIMARY_ACTION,
  SMOKE_HOME_PRIMARY_ACTION_HREF,
  SMOKE_HOME_SCOPE_LINK,
  SMOKE_HOME_SCOPE_LINK_HREF,
  SMOKE_HOME_SEARCH_ACTION,
  SMOKE_HOME_SEARCH_ACTION_HREF,
  SMOKE_HOME_TITLE,
  SMOKE_SHELL_FORBIDDEN_CANDIDATES,
  SMOKE_SHELL_FORBIDDEN_COMMITTEES,
  SMOKE_SHELL_PRIMARY_NAV_LABELS
} from "./fixtures";
import { assertSeoHead } from "./smoke-helpers";

function exactLabelsPattern(labels: readonly string[]): RegExp {
  return new RegExp(`^(${labels.map((label) => label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})$`);
}

test.describe("federal landing smoke", () => {
  test("renders the static federal-first homepage contract", async ({ page }: { page: any }) => {
    await page.goto("/");

    await expect(page).toHaveURL(/\/$/);
    await expect(page).toHaveTitle(SMOKE_HOME_TITLE);
    await assertSeoHead(page, {
      title: SMOKE_HOME_TITLE,
      description: SMOKE_HOME_DESCRIPTION,
      ogType: "website",
      jsonLdCount: 1
    });

    const main = page.getByRole("main");
    await expect(page.getByRole("heading", { name: "Civibus" })).toBeVisible();
    await expect(main.getByRole("heading", { name: SMOKE_HOME_HEADING })).toBeVisible();
    await expect(main.getByText(SMOKE_HOME_BODY)).toBeVisible();
    await expect(main.getByText(SMOKE_HOME_FEDERAL_SCOPE_PHRASE)).toHaveCount(2);
    await expect(main.getByRole("heading", { name: SMOKE_HOME_COVERAGE_HEADING })).toBeVisible();
    await expect(main.getByText(SMOKE_HOME_COVERAGE_SUMMARY)).toBeVisible();
    await expect(main.getByRole("link", { name: SMOKE_HOME_SCOPE_LINK })).toHaveAttribute(
      "href",
      SMOKE_HOME_SCOPE_LINK_HREF
    );

    await expect(main.getByRole("link", { name: exactLabelsPattern(SMOKE_HOME_ACTION_LABELS) })).toHaveCount(3);
    const primaryAction = main.getByRole("link", { name: SMOKE_HOME_PRIMARY_ACTION, exact: true });
    await expect(primaryAction).toHaveAttribute("href", SMOKE_HOME_PRIMARY_ACTION_HREF);
    await expect(main.getByRole("link", { name: SMOKE_HOME_SEARCH_ACTION, exact: true })).toHaveAttribute(
      "href",
      SMOKE_HOME_SEARCH_ACTION_HREF
    );
    await expect(main.getByRole("link", { name: SMOKE_HOME_METHODOLOGY_ACTION, exact: true })).toHaveAttribute(
      "href",
      SMOKE_HOME_METHODOLOGY_ACTION_HREF
    );

    await primaryAction.click();
    await expect(page).toHaveURL(new RegExp(`${SMOKE_HOME_PRIMARY_ACTION_HREF}$`));
    await expect(page.getByRole("heading", { name: "Congress" })).toBeVisible();
  });

  test("exposes only the federal primary shell navigation", async ({ page }: { page: any }) => {
    await page.goto("/");

    const primaryNav = page.getByRole("navigation", { name: "Primary" });
    await expect(primaryNav.getByRole("link")).toHaveText(SMOKE_SHELL_PRIMARY_NAV_LABELS);
    await expect(
      primaryNav.getByRole("link", { name: SMOKE_SHELL_FORBIDDEN_CANDIDATES, exact: true })
    ).toHaveCount(0);
    await expect(
      primaryNav.getByRole("link", { name: SMOKE_SHELL_FORBIDDEN_COMMITTEES, exact: true })
    ).toHaveCount(0);
  });

  test("does not expose retired state-map or list-promotion surfaces", async ({ page }: { page: any }) => {
    await page.goto("/");

    const main = page.getByRole("main");
    await expect(main.getByRole("link", { name: SMOKE_HOME_FORBIDDEN_STATE_ACTION })).toHaveCount(0);
    await expect(main.getByRole("link", { name: SMOKE_HOME_FORBIDDEN_SUPPORTED_STATE })).toHaveCount(0);
    await expect(
      main.getByText(`${SMOKE_HOME_FORBIDDEN_UNSUPPORTED_STATE} — ${SMOKE_HOME_FORBIDDEN_UNSUPPORTED_LABEL}`)
    ).toHaveCount(0);
    await expect(main.getByText(SMOKE_HOME_FORBIDDEN_WARNING_TEXT)).toHaveCount(0);
    await expect(main.getByRole("link", { name: SMOKE_HOME_FORBIDDEN_WARNING_STATE })).toHaveCount(0);
    await expect(main.getByRole("link", { name: SMOKE_HOME_FORBIDDEN_CANDIDATE_ACTION })).toHaveCount(0);
    await expect(main.getByRole("link", { name: SMOKE_HOME_FORBIDDEN_COMMITTEE_ACTION })).toHaveCount(0);
  });
});
