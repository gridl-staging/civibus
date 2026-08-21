import { expect, test } from "playwright/test";
import type { Locator, Page } from "playwright";

import { APP_SHELL } from "../../src/lib/config/app";
import {
  SMOKE_CANDIDATES_FIRST_PAGE_LABEL,
  SMOKE_CANDIDATE_LIST_CONTEXT,
  SMOKE_CANDIDATE_NAME,
  SMOKE_COMMITTEES_FIRST_PAGE_LABEL,
  SMOKE_COMMITTEE_LIST_CONTEXT,
  SMOKE_COMMITTEE_NAME,
  SMOKE_CONGRESS_LEADER_NAME,
  SMOKE_HOME_BODY,
  SMOKE_HOME_HEADING,
  SMOKE_HOME_PRIMARY_ACTION,
  SMOKE_HOME_PRIMARY_ACTION_HREF,
  SMOKE_METHODOLOGY_SECTION_BODY,
  SMOKE_PUBLIC_API_ENDPOINTS,
  SMOKE_PUBLIC_API_HEADING,
  SMOKE_SEARCH_QUERY,
  SMOKE_SEARCH_RESULT_NAME,
  SMOKE_SHELL_NAV_CANDIDATES,
  SMOKE_SHELL_NAV_COMMITTEES,
  SMOKE_SHELL_NAV_CONGRESS,
  SMOKE_SHELL_NAV_DEVELOPERS,
  SMOKE_SHELL_NAV_HOME,
  SMOKE_SHELL_NAV_METHODOLOGY,
  SMOKE_SHELL_NAV_SEARCH
} from "./fixtures";

type PrimaryNavigationLabel =
  | typeof SMOKE_SHELL_NAV_HOME
  | typeof SMOKE_SHELL_NAV_SEARCH
  | typeof SMOKE_SHELL_NAV_CANDIDATES
  | typeof SMOKE_SHELL_NAV_COMMITTEES
  | typeof SMOKE_SHELL_NAV_CONGRESS
  | typeof SMOKE_SHELL_NAV_DEVELOPERS
  | typeof SMOKE_SHELL_NAV_METHODOLOGY;

const isProductionSmokeMode = (process.env.SMOKE_MODE ?? "local") === "production";
const primaryNavigationPathsByLabel = new Map(
  APP_SHELL.shellNavigation.map((destination) => [destination.label, destination.href])
);

function primaryNavigationPath(label: PrimaryNavigationLabel): string {
  const path = primaryNavigationPathsByLabel.get(label);
  if (path === undefined) {
    throw new Error(`APP_SHELL.shellNavigation is missing ${label}`);
  }
  return path;
}

async function expectDirectRoute(page: Page, path: string): Promise<void> {
  await page.goto(path);
  await expect(page).toHaveURL(new RegExp(`${path === "/" ? "/" : `${path}`}$`));
}

async function expectVisibleRows(rows: Locator): Promise<void> {
  await expect(rows.first()).toBeVisible();
  expect(await rows.count()).toBeGreaterThan(0);
}

async function expectFixtureSearchResult(page: Page): Promise<void> {
  await expect(page.getByRole("link", { name: SMOKE_SEARCH_RESULT_NAME })).toBeVisible();
}

async function expectProductionSearchResult(page: Page): Promise<void> {
  // Two valid wordings, decided by production data volume (search.md pagination
  // contract, civibus-x9d/aug20): an unpaged set says "N results found." while
  // a set spanning pages says "N results shown." — production's org query
  // returns well over one page, so pinning "found" alone turned the 2026-08-20
  // deploy gate red against a healthy build.
  await expect(page.getByTestId("search-status")).toHaveText(/^[1-9]\d* results? (found|shown)\.$/);
  const matchingResult = page
    .getByTestId("search-results-region")
    .getByRole("link", { name: new RegExp(SMOKE_SEARCH_QUERY, "i") })
    .first();
  await expect(matchingResult).toBeVisible();
  await expect(matchingResult).toHaveAttribute("href", /^\/org\/[^/?#]+$/);
}

async function expectFixtureCandidateRows(page: Page): Promise<void> {
  await expect(page.getByRole("link", { name: SMOKE_CANDIDATE_NAME })).toBeVisible();
  await expect(page.getByText(SMOKE_CANDIDATE_LIST_CONTEXT)).toBeVisible();
  await expect(page.getByText(SMOKE_CANDIDATES_FIRST_PAGE_LABEL)).toBeVisible();
}

async function expectProductionCandidateRows(page: Page, candidateRows: Locator): Promise<void> {
  const candidateLink = candidateRows.getByRole("link").filter({ hasText: /\S/ }).first();
  await expect(candidateLink).toBeVisible();
  await expect(candidateLink).toHaveAttribute("href", /^\/candidate\/[^/?#]+$/);
  await expect(
    candidateRows.getByText(/^[A-Z0-9]{1,4} · [HSP] · (?:[A-Z]{2}|US)-\d{2}$/).first()
  ).toBeVisible();
  await expect(page.getByText(/^Showing 1–[1-9]\d*$/)).toBeVisible();
}

async function expectFixtureCommitteeRows(page: Page): Promise<void> {
  await expect(page.getByRole("link", { name: SMOKE_COMMITTEE_NAME })).toBeVisible();
  await expect(page.getByText(SMOKE_COMMITTEE_LIST_CONTEXT)).toBeVisible();
  await expect(page.getByText(SMOKE_COMMITTEES_FIRST_PAGE_LABEL)).toBeVisible();
}

async function expectProductionCommitteeRows(page: Page, committeeRows: Locator): Promise<void> {
  const committeeLink = committeeRows.getByRole("link").filter({ hasText: /[A-Za-z0-9]/ }).first();
  await expect(committeeLink).toBeVisible();
  await expect(committeeLink).toHaveAttribute("href", /^\/committee\/[^/?#]+$/);
  await expect(
    committeeRows.getByText(/^[A-Z] · (?:[A-Z]{2,3} · )?[A-Z]{2}$/).first()
  ).toBeVisible();
  await expect(page.getByText(/^Showing 1–[1-9]\d*$/)).toBeVisible();
}

async function expectFixtureCongressRows(page: Page): Promise<void> {
  await expect(page.getByTestId("congress-result-count")).toHaveText("3 members");
  await expect(page.getByRole("link", { name: SMOKE_CONGRESS_LEADER_NAME, exact: true })).toBeVisible();
}

async function expectProductionCongressRows(page: Page): Promise<void> {
  const resultCount = await page.getByTestId("congress-result-count").textContent();
  expect(Number.parseInt(resultCount ?? "0", 10)).toBeGreaterThanOrEqual(500);
  const memberLink = page
    .getByTestId("congress-member-row-0")
    .getByRole("link")
    .filter({ hasText: /\S/ })
    .first();
  await expect(memberLink).toBeVisible();
  await expect(memberLink).toHaveAttribute("href", /^\/person\/[^/?#]+$/);
}

const expectSearchResult = isProductionSmokeMode
  ? expectProductionSearchResult
  : expectFixtureSearchResult;
const expectCandidateRows = isProductionSmokeMode
  ? expectProductionCandidateRows
  : expectFixtureCandidateRows;
const expectCommitteeRows = isProductionSmokeMode
  ? expectProductionCommitteeRows
  : expectFixtureCommitteeRows;
const expectCongressRows = isProductionSmokeMode
  ? expectProductionCongressRows
  : expectFixtureCongressRows;

test.describe("primary nav non-empty smoke", () => {
  test(`primary-nav non-empty: ${SMOKE_SHELL_NAV_HOME}`, async ({ page }: { page: Page }) => {
    await expectDirectRoute(page, primaryNavigationPath(SMOKE_SHELL_NAV_HOME));

    await expect(page.getByRole("heading", { name: SMOKE_HOME_HEADING })).toBeVisible();
    await expect(page.getByText(SMOKE_HOME_BODY)).toBeVisible();
    await expect(page.getByRole("link", { name: SMOKE_HOME_PRIMARY_ACTION, exact: true })).toHaveAttribute(
      "href",
      SMOKE_HOME_PRIMARY_ACTION_HREF
    );
  });

  test(`primary-nav non-empty: ${SMOKE_SHELL_NAV_SEARCH}`, async ({ page }: { page: Page }) => {
    await expectDirectRoute(page, primaryNavigationPath(SMOKE_SHELL_NAV_SEARCH));

    await expect(page.getByRole("heading", { name: "Search" })).toBeVisible();
    await expect(page.getByLabel("Query")).toBeVisible();

    await page.goto(`${primaryNavigationPath(SMOKE_SHELL_NAV_SEARCH)}?q=${SMOKE_SEARCH_QUERY}&entity_type=org`);
    await expect(page).toHaveURL(new RegExp(`/search\\?q=${SMOKE_SEARCH_QUERY}&entity_type=org$`));
    await expectSearchResult(page);
  });

  test(`primary-nav non-empty: ${SMOKE_SHELL_NAV_CANDIDATES}`, async ({ page }: { page: Page }) => {
    await expectDirectRoute(page, primaryNavigationPath(SMOKE_SHELL_NAV_CANDIDATES));

    await expect(page.getByRole("heading", { name: "Candidates" })).toBeVisible();
    const candidateRows = page.getByTestId("candidate-result-row");
    await expectVisibleRows(candidateRows);
    await expectCandidateRows(page, candidateRows);
  });

  test(`primary-nav non-empty: ${SMOKE_SHELL_NAV_COMMITTEES}`, async ({ page }: { page: Page }) => {
    await expectDirectRoute(page, primaryNavigationPath(SMOKE_SHELL_NAV_COMMITTEES));

    await expect(page.getByRole("heading", { name: "Committees" })).toBeVisible();
    const committeeRows = page.getByTestId("committee-result-row");
    await expectVisibleRows(committeeRows);
    await expectCommitteeRows(page, committeeRows);
  });

  test(`primary-nav non-empty: ${SMOKE_SHELL_NAV_CONGRESS}`, async ({ page }: { page: Page }) => {
    await expectDirectRoute(page, primaryNavigationPath(SMOKE_SHELL_NAV_CONGRESS));

    await expect(page.getByRole("heading", { name: "Congress" })).toBeVisible();
    await expectCongressRows(page);
  });

  test(`primary-nav non-empty: ${SMOKE_SHELL_NAV_DEVELOPERS}`, async ({ page }: { page: Page }) => {
    await expectDirectRoute(page, primaryNavigationPath(SMOKE_SHELL_NAV_DEVELOPERS));

    const main = page.getByRole("main");
    await expect(main.getByRole("heading", { name: SMOKE_PUBLIC_API_HEADING })).toBeVisible();
    await expect(main.getByRole("heading", { name: SMOKE_PUBLIC_API_ENDPOINTS[0], exact: true })).toBeVisible();
  });

  test(`primary-nav non-empty: ${SMOKE_SHELL_NAV_METHODOLOGY}`, async ({ page }: { page: Page }) => {
    await expectDirectRoute(page, primaryNavigationPath(SMOKE_SHELL_NAV_METHODOLOGY));

    await expect(page.getByRole("heading", { level: 2, name: "Methodology", exact: true })).toBeVisible();
    await expect(page.getByText(SMOKE_METHODOLOGY_SECTION_BODY)).toBeVisible();
  });
});
