import { expect, test } from "playwright/test";

import {
  SMOKE_CANDIDACY_ID,
  SMOKE_CANDIDACY_PERSON_NAME,
  SMOKE_CANDIDATE_ID,
  SMOKE_CANDIDATE_NAME,
  SMOKE_COMMITTEE_SLUG,
  SMOKE_CONTEST_ID,
  SMOKE_CONTEST_NAME,
  SMOKE_OFFICEHOLDING_ID,
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
  SMOKE_OFFICE_OFFICEHOLDER_NAME,
  SMOKE_OFFICE_OFFICEHOLDER_ID,
  SMOKE_OFFICE_NAME,
  SMOKE_PERSON_CANONICAL_NAME,
  SMOKE_PERSON_ID,
  SMOKE_SEARCH_CANDIDATE_QUERY,
  SMOKE_SEARCH_CANDIDATE_RESULT_NAME,
  SMOKE_SEARCH_CONTEST_QUERY,
  SMOKE_SEARCH_CONTEST_RESULT_NAME,
  SMOKE_SEARCH_DESCRIPTION,
  SMOKE_SEARCH_EMPTY_DESCRIPTION,
  SMOKE_SEARCH_EMPTY_TITLE,
  SMOKE_SEARCH_QUERY,
  SMOKE_SEARCH_RESULT_NAME,
  SMOKE_SEARCH_SLOW_QUERY,
  SMOKE_SEARCH_TITLE,
  SMOKE_SEARCH_VALIDATION_MESSAGE,
  SMOKE_SEARCH_VALIDATION_QUERY,
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

type RouteGate = {
  waitForRequest: Promise<void>;
  release: () => void;
  remove: () => Promise<void>;
};

async function gateDataRoute(page: any, urlPattern: string): Promise<RouteGate> {
  let markRequestSeen: (() => void) | undefined;
  const waitForRequest = new Promise<void>((resolve) => {
    markRequestSeen = resolve;
  });
  let releaseRoute: (() => void) | undefined;
  const waitForRelease = new Promise<void>((resolve) => {
    releaseRoute = resolve;
  });
  const handler = async (route: any) => {
    markRequestSeen?.();
    markRequestSeen = undefined;
    await waitForRelease;
    await route.continue();
  };

  await page.route(urlPattern, handler);

  return {
    waitForRequest,
    release: () => releaseRoute?.(),
    remove: () => page.unroute(urlPattern, handler)
  };
}

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

  test("/search candidate results route to canonical person detail", async ({ page }: { page: any }) => {
    await page.goto(`/search?q=${SMOKE_SEARCH_CANDIDATE_QUERY}&entity_type=candidate`);

    const candidateResultCard = page
      .getByRole("listitem")
      .filter({ has: page.getByRole("link", { name: SMOKE_SEARCH_CANDIDATE_RESULT_NAME }) });
    await expect(candidateResultCard).toBeVisible();
    await expect(candidateResultCard.getByText("Candidate", { exact: true })).toBeVisible();

    await candidateResultCard.getByRole("link", { name: SMOKE_SEARCH_CANDIDATE_RESULT_NAME }).click();

    await expect(page).toHaveURL(`/person/${SMOKE_PERSON_ID}`);
    await expect(page.getByRole("heading", { name: SMOKE_PERSON_CANONICAL_NAME })).toBeVisible();
  });

  test("/search keeps backend 422 validation inline instead of routing to +error", async ({
    page
  }: {
    page: any;
  }) => {
    await page.goto("/search");

    await page.getByLabel("Query").fill(SMOKE_SEARCH_VALIDATION_QUERY);
    await page.getByLabel("Entity type").selectOption("candidate");
    await page.getByRole("button", { name: "Search" }).click();

    await expect(page).toHaveURL("/search");
    await expect(page.getByLabel("Query")).toHaveValue(SMOKE_SEARCH_VALIDATION_QUERY);
    await expect(page.getByLabel("Entity type")).toHaveValue("candidate");
    await expect(page.getByText(SMOKE_SEARCH_VALIDATION_MESSAGE)).toBeVisible();
    await expect(page.getByText("Search could not run. Fix validation issues and try again.")).toBeVisible();
  });

  test("/search keeps URL-param validation inline and does not render the route error page", async ({
    page
  }: {
    page: any;
  }) => {
    await page.goto(`/search?q=${SMOKE_SEARCH_VALIDATION_QUERY}&entity_type=candidate`);

    await expect(page).toHaveURL(
      `/search?q=${SMOKE_SEARCH_VALIDATION_QUERY}&entity_type=candidate`
    );
    await expect(page.getByRole("heading", { name: "Search" })).toBeVisible();
    await expect(page.getByLabel("Query")).toHaveValue(SMOKE_SEARCH_VALIDATION_QUERY);
    await expect(page.getByLabel("Entity type")).toHaveValue("candidate");
    await expect(page.getByText(SMOKE_SEARCH_VALIDATION_MESSAGE)).toBeVisible();
    await expect(page.getByText("Search could not run. Fix validation issues and try again.")).toBeVisible();
    await expect(
      page.getByText("The server rejected this request. Check the URL or try searching for a record.")
    ).toHaveCount(0);
  });

  test("/search submit shows deterministic pending labels while request is in flight", async ({
    page
  }: {
    page: any;
  }) => {
    await page.goto("/search");

    await page.getByLabel("Query").fill(SMOKE_SEARCH_SLOW_QUERY);
    await page.getByLabel("Entity type").selectOption("org");
    const submit = page.getByRole("button", { name: "Search" });
    const submitPromise = submit.click();

    await expect(page.getByRole("button", { name: "Searching..." })).toBeVisible();
    await expect(page.getByTestId("search-status")).toHaveText("Searching...");

    await submitPromise;
    await expect(page).toHaveURL(`/search?q=${SMOKE_SEARCH_SLOW_QUERY}&entity_type=org`);
  });

  test("/search contest results route to contest detail", async ({ page }: { page: any }) => {
    await page.goto(`/search?q=${SMOKE_SEARCH_CONTEST_QUERY}&entity_type=contest`);

    const contestResultCard = page
      .getByRole("listitem")
      .filter({ has: page.getByRole("link", { name: SMOKE_SEARCH_CONTEST_RESULT_NAME }) });
    await expect(contestResultCard).toBeVisible();
    await expect(contestResultCard.getByText("Contest", { exact: true })).toBeVisible();

    await contestResultCard.getByRole("link", { name: SMOKE_SEARCH_CONTEST_RESULT_NAME }).click();

    await expect(page).toHaveURL(`/contest/${SMOKE_CONTEST_ID}`);
    await expect(page.getByRole("heading", { name: SMOKE_CONTEST_NAME })).toBeVisible();
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

  test("small-mobile civic detail routes keep cross-links visible and expose loading state attributes", async ({
    page
  }: {
    page: any;
  }) => {
    await page.setViewportSize({ width: 360, height: 780 });

    await page.goto(`/contest/${SMOKE_CONTEST_ID}`);
    await expect(page.getByRole("main")).toHaveAttribute("aria-busy", "false");
    await expect(page.getByRole("link", { name: "View office record" })).toHaveAttribute(
      "href",
      `/office/${SMOKE_OFFICE_ID}`
    );
    const candidacyDetailLink = page.getByRole("link", {
      name: `View candidacy detail for ${SMOKE_CANDIDACY_PERSON_NAME}`
    });
    await expect(candidacyDetailLink).toHaveAttribute(
      "href",
      `/candidacy/${SMOKE_CANDIDACY_ID}`
    );
    const candidacyDataRoute = await gateDataRoute(page, `**/candidacy/${SMOKE_CANDIDACY_ID}/__data.json*`);

    const navigateToCandidacy = candidacyDetailLink.click();
    await candidacyDataRoute.waitForRequest;
    await expect(page.getByRole("main")).toHaveAttribute("aria-busy", "true");
    await expect(page.getByRole("progressbar")).toHaveAttribute("class", /navigation-progress--active/);
    candidacyDataRoute.release();
    await navigateToCandidacy;
    await candidacyDataRoute.remove();

    await expect(page).toHaveURL(`/candidacy/${SMOKE_CANDIDACY_ID}`);
    await expect(page.getByRole("main")).toHaveAttribute("aria-busy", "false");
    await expect(page.getByRole("link", { name: "View person record" })).toHaveAttribute(
      "href",
      `/person/${SMOKE_PERSON_ID}`
    );
    await expect(page.getByRole("link", { name: "View contest record" })).toHaveAttribute(
      "href",
      `/contest/${SMOKE_CONTEST_ID}`
    );

    await page.goto(`/office/${SMOKE_OFFICE_ID}`);
    await expect(page.getByRole("main")).toHaveAttribute("aria-busy", "false");
    await expect(page.getByRole("link", { name: `View officeholding detail for ${SMOKE_OFFICE_OFFICEHOLDER_NAME}` })).toHaveAttribute(
      "href",
      `/officeholding/${SMOKE_OFFICE_OFFICEHOLDER_ID}`
    );

    await page.goto(`/officeholding/${SMOKE_OFFICEHOLDING_ID}`);
    await expect(page.getByRole("main")).toHaveAttribute("aria-busy", "false");
    await expect(page.getByRole("link", { name: "View person record" })).toHaveAttribute(
      "href",
      `/person/${SMOKE_PERSON_ID}`
    );
    await expect(page.getByRole("link", { name: "View office record" })).toHaveAttribute(
      "href",
      `/office/${SMOKE_OFFICE_ID}`
    );
  });

  test("outbound civic-detail navigation to person does not show stale civic skeleton", async ({
    page
  }: {
    page: any;
  }) => {
    await page.goto(`/office/${SMOKE_OFFICE_ID}`);
    await expect(page.getByRole("main")).toHaveAttribute("aria-busy", "false");
    await expect(page.getByRole("heading", { name: SMOKE_OFFICE_NAME })).toBeVisible();

    const personLink = page.getByRole("link", { name: SMOKE_OFFICE_OFFICEHOLDER_NAME, exact: true });
    await expect(personLink).toHaveAttribute("href", `/person/${SMOKE_PERSON_ID}`);

    const personDataRoute = await gateDataRoute(page, `**/person/${SMOKE_PERSON_ID}/__data.json*`);

    const navigateToPerson = personLink.click();
    await personDataRoute.waitForRequest;
    await expect(page.getByRole("main")).toHaveAttribute("aria-busy", "true");
    await expect(page.getByText("office detail loading")).toHaveCount(0);
    personDataRoute.release();
    await navigateToPerson;
    await personDataRoute.remove();

    await expect(page).toHaveURL(`/person/${SMOKE_PERSON_ID}`);
    await expect(page.getByRole("main")).toHaveAttribute("aria-busy", "false");
    await expect(page.getByRole("heading", { name: SMOKE_PERSON_CANONICAL_NAME })).toBeVisible();
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
