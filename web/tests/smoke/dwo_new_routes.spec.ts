import { expect, test } from "playwright/test";
import {
  SMOKE_CALENDAR_HEADING,
  SMOKE_CALENDAR_DESCRIPTION,
  SMOKE_CONTEST_NAME,
  SMOKE_CALENDAR_ROUTE_PATH,
  SMOKE_CALENDAR_TITLE,
  SMOKE_COVERAGE_DOMAIN,
  SMOKE_COVERAGE_DESCRIPTION,
  SMOKE_COVERAGE_HEADING,
  SMOKE_COVERAGE_JURISDICTION,
  SMOKE_COVERAGE_ROUTE_PATH,
  SMOKE_COVERAGE_TITLE,
  SMOKE_DATA_SOURCE_NAME,
  SMOKE_DATA_SOURCES_DESCRIPTION,
  SMOKE_DATA_SOURCES_HEADING,
  SMOKE_DATA_SOURCES_ROUTE_PATH,
  SMOKE_DATA_SOURCES_TITLE,
  SMOKE_ELECTION_DATE,
  SMOKE_ELECTION_DESCRIPTION,
  SMOKE_ELECTION_HEADING,
  SMOKE_ELECTION_ROUTE_PATH,
  SMOKE_ELECTION_TITLE
} from "./fixtures";
import { assertSeoHead } from "./smoke-helpers";

function capturePageErrors(page: any): string[] {
  const errors: string[] = [];

  page.on("console", (message: any) => {
    if (message.type() === "error") {
      errors.push(`console: ${message.text()}`);
    }
  });
  page.on("pageerror", (error: Error) => {
    errors.push(`pageerror: ${error.message}`);
  });

  return errors;
}

async function gotoRouteAndAssertOk(page: any, routePath: string): Promise<string[]> {
  const pageErrors = capturePageErrors(page);
  const response = await page.goto(routePath);

  expect(response?.status()).toBe(200);

  return pageErrors;
}

function expectNoLoadErrors(routePath: string, pageErrors: string[]): void {
  expect(pageErrors, `Expected ${routePath} to load without console or page errors.`).toEqual([]);
}

test.describe("new routes smoke", () => {
  test("/coverage renders fixture-backed registry rows with shared SEO", async ({ page }: { page: any }) => {
    const pageErrors = await gotoRouteAndAssertOk(page, SMOKE_COVERAGE_ROUTE_PATH);

    await expect(page).toHaveTitle(SMOKE_COVERAGE_TITLE);
    await assertSeoHead(page, {
      title: SMOKE_COVERAGE_TITLE,
      description: SMOKE_COVERAGE_DESCRIPTION,
      ogType: "website",
      jsonLdCount: 0
    });
    await expect(page.getByRole("heading", { level: 2, name: SMOKE_COVERAGE_HEADING })).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Domain" })).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Jurisdiction" })).toBeVisible();
    await expect(page.getByRole("cell", { name: SMOKE_COVERAGE_DOMAIN })).toBeVisible();
    await expect(page.getByRole("cell", { name: SMOKE_COVERAGE_JURISDICTION })).toBeVisible();
    expectNoLoadErrors(SMOKE_COVERAGE_ROUTE_PATH, pageErrors);
  });

  test("/calendar renders upcoming election timeline with shared SEO", async ({ page }: { page: any }) => {
    const pageErrors = await gotoRouteAndAssertOk(page, SMOKE_CALENDAR_ROUTE_PATH);

    await expect(page).toHaveTitle(SMOKE_CALENDAR_TITLE);
    await assertSeoHead(page, {
      title: SMOKE_CALENDAR_TITLE,
      description: SMOKE_CALENDAR_DESCRIPTION,
      ogType: "website",
      jsonLdCount: 0
    });
    await expect(page.getByRole("heading", { level: 2, name: SMOKE_CALENDAR_HEADING })).toBeVisible();
    await expect(page.getByLabel("Upcoming election calendar")).toBeVisible();
    await expect(page.getByRole("heading", { level: 3, name: SMOKE_ELECTION_DATE })).toBeVisible();
    await expect(page.getByText(SMOKE_CONTEST_NAME)).toBeVisible();
    expectNoLoadErrors(SMOKE_CALENDAR_ROUTE_PATH, pageErrors);
  });

  test("/data-sources renders fixture-backed metadata rows with shared SEO", async ({ page }: { page: any }) => {
    const pageErrors = await gotoRouteAndAssertOk(page, SMOKE_DATA_SOURCES_ROUTE_PATH);

    await expect(page).toHaveTitle(SMOKE_DATA_SOURCES_TITLE);
    await assertSeoHead(page, {
      title: SMOKE_DATA_SOURCES_TITLE,
      description: SMOKE_DATA_SOURCES_DESCRIPTION,
      ogType: "website",
      jsonLdCount: 0
    });
    await expect(page.getByRole("heading", { level: 2, name: SMOKE_DATA_SOURCES_HEADING })).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Name" })).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Update frequency" })).toBeVisible();
    const sourceLink = page.getByRole("link", { name: SMOKE_DATA_SOURCE_NAME });
    await expect(sourceLink).toBeVisible();
    await expect(sourceLink).toHaveAttribute("target", "_blank");
    await expect(sourceLink).toHaveAttribute("rel", /(?:^|\s)noopener(?:\s|$)/);
    await expect(sourceLink).toHaveAttribute("rel", /(?:^|\s)nofollow(?:\s|$)/);
    expectNoLoadErrors(SMOKE_DATA_SOURCES_ROUTE_PATH, pageErrors);
  });

  test("/election/[date] renders aggregate page data with shared SEO", async ({ page }: { page: any }) => {
    const pageErrors = await gotoRouteAndAssertOk(page, SMOKE_ELECTION_ROUTE_PATH);

    await expect(page).toHaveTitle(SMOKE_ELECTION_TITLE);
    await assertSeoHead(page, {
      title: SMOKE_ELECTION_TITLE,
      description: SMOKE_ELECTION_DESCRIPTION,
      ogType: "website",
      jsonLdCount: 1
    });
    await expect(page.getByRole("heading", { level: 2, name: SMOKE_ELECTION_HEADING })).toBeVisible();
    await expect(page.getByRole("link", { name: "Canonical election route" })).toHaveAttribute(
      "href",
      SMOKE_ELECTION_ROUTE_PATH
    );
    await expect(page.getByText("Total contests: 1")).toBeVisible();
    await expect(page.getByText(SMOKE_CONTEST_NAME)).toBeVisible();
    expectNoLoadErrors(SMOKE_ELECTION_ROUTE_PATH, pageErrors);
  });
});
