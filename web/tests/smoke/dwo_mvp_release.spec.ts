import { expect, test } from "playwright/test";

import {
  SMOKE_CANDIDATE_ID,
  SMOKE_CANDIDATE_NAME,
  SMOKE_CANDIDATE_SLUG,
  SMOKE_CANDIDATE_SUPPORT_TOTAL,
  SMOKE_CANDIDATES_FIRST_PAGE_LABEL,
  SMOKE_CANDIDATES_TITLE,
  SMOKE_COMMITTEE_NAME,
  SMOKE_COMMITTEE_SLUG,
  SMOKE_COMMITTEE_TITLE,
  SMOKE_COMMITTEES_FIRST_PAGE_LABEL,
  SMOKE_COMMITTEES_TITLE,
  SMOKE_HOME_DESCRIPTION,
  SMOKE_HOME_HEADING,
  SMOKE_HOME_PRIMARY_ACTION,
  SMOKE_HOME_PRIMARY_ACTION_HREF,
  SMOKE_HOME_TITLE,
  SMOKE_IE_COMMITTEE_A_NAME,
  SMOKE_SEARCH_DESCRIPTION,
  SMOKE_SEARCH_QUERY,
  SMOKE_SEARCH_RESULT_NAME,
  SMOKE_SEARCH_TITLE,
  SMOKE_STATE_DETAIL_RETIRED_HEADING,
  SMOKE_STATE_DETAIL_SUPPORTED_CODE,
  SMOKE_STATE_DETAIL_SUPPORTED_NAME
} from "./fixtures";
import { assertSearchHead, assertSeoHead } from "./smoke-helpers";

type RouteProbe = {
  exists: boolean;
  missingReason: string;
};

const isProductionSmokeMode = process.env.SMOKE_MODE === "production";

const browserIssuesByPage = new WeakMap<any, string[]>();

function registerBrowserErrorHooks(page: any) {
  const issues: string[] = [];

  page.on("console", (message: any) => {
    if (message.type() === "error") {
      issues.push(`console.error: ${message.text()}`);
    }
  });

  page.on("pageerror", (error: Error) => {
    issues.push(`pageerror: ${error.message}`);
  });

  browserIssuesByPage.set(page, issues);
}

function assertNoUnexpectedBrowserErrors(page: any, journeyName: string) {
  const issues = browserIssuesByPage.get(page) ?? [];
  expect(
    issues,
    `${journeyName} encountered unexpected browser/runtime errors:\n${issues.join("\n")}`
  ).toEqual([]);
}

async function probeOptionalRoute(page: any, routePath: string): Promise<RouteProbe> {
  const response = await page.goto(routePath, { waitUntil: "domcontentloaded" });
  const status = response?.status() ?? 0;

  if (status === 404) {
    return {
      exists: false,
      missingReason: `${routePath} resolved to framework not-found boundary (HTTP 404)`
    };
  }

  return {
    exists: true,
    missingReason: ""
  };
}

test.describe("DWO MVP release smoke", () => {
  test.beforeEach(async ({ page }: { page: any }) => {
    registerBrowserErrorHooks(page);
  });

  test.afterEach(async ({ page }: { page: any }, testInfo: any) => {
    if (testInfo.status === "skipped") {
      return;
    }
    assertNoUnexpectedBrowserErrors(page, testInfo.title);
  });

  test("landing journey renders MVP shell", async ({ page }: { page: any }) => {
    test.skip(isProductionSmokeMode, "Local fixture assertions are not stable for production-target smoke.");
    await page.goto("/");

    await expect(page).toHaveURL(/\/$/);
    await expect(page).toHaveTitle(SMOKE_HOME_TITLE);
    await assertSeoHead(page, {
      title: SMOKE_HOME_TITLE,
      description: SMOKE_HOME_DESCRIPTION,
      ogType: "website",
      jsonLdCount: 1
    });
    await expect(page.getByRole("heading", { name: "Civibus" })).toBeVisible();
    await expect(page.getByRole("heading", { name: SMOKE_HOME_HEADING })).toBeVisible();
    await expect(page.getByRole("link", { name: SMOKE_HOME_PRIMARY_ACTION })).toHaveAttribute(
      "href",
      SMOKE_HOME_PRIMARY_ACTION_HREF
    );
  });

  test("search journey executes deterministic query flow", async ({ page }: { page: any }) => {
    test.skip(isProductionSmokeMode, "Local fixture assertions are not stable for production-target smoke.");
    await page.goto(`/search?q=${SMOKE_SEARCH_QUERY}&entity_type=org`);

    await expect(page).toHaveURL(/\/search\?q=civ&entity_type=org$/);
    await assertSearchHead(page, {
      title: SMOKE_SEARCH_TITLE,
      description: SMOKE_SEARCH_DESCRIPTION
    });
    await expect(page.getByRole("heading", { name: "Search" })).toBeVisible();
    await expect(page.getByRole("link", { name: SMOKE_SEARCH_RESULT_NAME })).toBeVisible();
  });

  test("candidates journey renders list and detail target", async ({ page }: { page: any }) => {
    test.skip(isProductionSmokeMode, "Local fixture assertions are not stable for production-target smoke.");
    await page.goto("/candidates");

    await expect(page).toHaveURL(/\/candidates(?:\?limit=1)?$/);
    await expect(page).toHaveTitle(SMOKE_CANDIDATES_TITLE);
    await expect(page.getByRole("heading", { name: "Candidates" })).toBeVisible();
    await expect(page.getByRole("link", { name: SMOKE_CANDIDATE_NAME })).toHaveAttribute(
      "href",
      `/candidate/${SMOKE_CANDIDATE_SLUG}`
    );
    await expect(page.getByText(SMOKE_CANDIDATES_FIRST_PAGE_LABEL)).toBeVisible();
  });

  test("committees journey renders list and detail target", async ({ page }: { page: any }) => {
    test.skip(isProductionSmokeMode, "Local fixture assertions are not stable for production-target smoke.");
    await page.goto("/committees");

    await expect(page).toHaveURL(/\/committees(?:\?limit=1)?$/);
    await expect(page).toHaveTitle(SMOKE_COMMITTEES_TITLE);
    await expect(page.getByRole("heading", { name: "Committees" })).toBeVisible();
    await expect(page.getByRole("link", { name: SMOKE_COMMITTEE_NAME })).toHaveAttribute(
      "href",
      `/committee/${SMOKE_COMMITTEE_SLUG}`
    );
    await expect(page.getByText(SMOKE_COMMITTEES_FIRST_PAGE_LABEL)).toBeVisible();
  });

  test("candidate detail journey includes IE context", async ({ page }: { page: any }) => {
    test.skip(isProductionSmokeMode, "Local fixture assertions are not stable for production-target smoke.");
    await page.goto(`/candidate/${SMOKE_CANDIDATE_ID}`);

    await expect(page).toHaveURL(new RegExp(`/candidate/${SMOKE_CANDIDATE_SLUG}$`));
    await expect(page.getByRole("heading", { name: SMOKE_CANDIDATE_NAME })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Outside Spending" })).toBeVisible();
    await expect(page.getByText(SMOKE_CANDIDATE_SUPPORT_TOTAL)).toBeVisible();
    await expect(page.getByRole("link", { name: SMOKE_IE_COMMITTEE_A_NAME }).first()).toHaveAttribute(
      "href",
      /\/committee\//
    );
  });

  test("committee detail journey renders fundraising summary", async ({ page }: { page: any }) => {
    test.skip(isProductionSmokeMode, "Local fixture assertions are not stable for production-target smoke.");
    await page.goto(`/committee/${SMOKE_COMMITTEE_SLUG}`);

    await expect(page).toHaveURL(new RegExp(`/committee/${SMOKE_COMMITTEE_SLUG}$`));
    await expect(page).toHaveTitle(SMOKE_COMMITTEE_TITLE);
    await expect(page.getByRole("heading", { name: SMOKE_COMMITTEE_NAME })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Fundraising summary" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Filing-period breakdown" })).toBeVisible();
  });

  test("state detail journey renders retired v1 state page", async ({ page }: { page: any }) => {
    test.skip(isProductionSmokeMode, "Local fixture assertions are not stable for production-target smoke.");
    await page.goto(`/state/${SMOKE_STATE_DETAIL_SUPPORTED_CODE}`);

    await expect(page).toHaveURL(new RegExp(`/state/${SMOKE_STATE_DETAIL_SUPPORTED_CODE}$`));
    await expect(page.getByRole("heading", { name: SMOKE_STATE_DETAIL_SUPPORTED_NAME })).toBeVisible();
    await expect(page.getByRole("status").filter({ hasText: SMOKE_STATE_DETAIL_RETIRED_HEADING })).toBeVisible();
    await expect(page.getByTestId("top-ie-spender-row-0")).toHaveCount(0);
  });

  test("pm_11 /coverage route check", async ({ page }: { page: any }) => {
    const routePath = "/coverage";
    const probe = await probeOptionalRoute(page, routePath);

    test.skip(!probe.exists, `Skipping ${routePath} assertion: ${probe.missingReason}`);
    await expect(page).toHaveURL(new RegExp(`${routePath}$`));
    await expect(page.locator("main")).toBeVisible();
  });

  test("pm_11 /calendar route check", async ({ page }: { page: any }) => {
    const routePath = "/calendar";
    const probe = await probeOptionalRoute(page, routePath);

    test.skip(!probe.exists, `Skipping ${routePath} assertion: ${probe.missingReason}`);
    await expect(page).toHaveURL(new RegExp(`${routePath}$`));
    await expect(page.locator("main")).toBeVisible();
  });

  test("pm_11 /data-sources route check", async ({ page }: { page: any }) => {
    const routePath = "/data-sources";
    const probe = await probeOptionalRoute(page, routePath);

    test.skip(!probe.exists, `Skipping ${routePath} assertion: ${probe.missingReason}`);
    await expect(page).toHaveURL(new RegExp(`${routePath}$`));
    await expect(page.locator("main")).toBeVisible();
  });

  test("production mode core route invariants", async ({ page }: { page: any }) => {
    test.skip(!isProductionSmokeMode, "Production-only invariant smoke.");

    for (const routePath of ["/", "/search", "/candidates", "/committees"]) {
      const response = await page.goto(routePath, { waitUntil: "domcontentloaded" });
      expect(response?.status(), `Expected HTTP 200-ish for ${routePath}`).toBeLessThan(400);
      await expect(page.locator("main")).toBeVisible();
      await expect(page.getByRole("link", { name: "Methodology" })).toBeVisible();
    }
  });
});
