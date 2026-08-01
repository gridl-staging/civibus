import { expect, test } from "playwright/test";
import type { Page, Request } from "playwright";

import {
  SMOKE_PUBLIC_API_CACHE_CONTRACT,
  SMOKE_PUBLIC_API_CONTRIBUTOR_CURL,
  SMOKE_PUBLIC_API_CONTRIBUTOR_SAMPLE_AMOUNT,
  SMOKE_PUBLIC_API_CONTRIBUTOR_SAMPLE_NAME,
  SMOKE_PUBLIC_API_CSV_HEADER,
  SMOKE_PUBLIC_API_ENDPOINTS,
  SMOKE_PUBLIC_API_EMPLOYER_COVERAGE_FIELD,
  SMOKE_PUBLIC_API_EMPLOYER_CURL,
  SMOKE_PUBLIC_API_EMPLOYER_UNKNOWN_BUCKET,
  SMOKE_PUBLIC_API_FOOTER_LINK,
  SMOKE_PUBLIC_API_HEADING,
  SMOKE_PUBLIC_API_METADATA_REFERENCE,
  SMOKE_PUBLIC_API_MIGRATION_COLUMNS,
  SMOKE_PUBLIC_API_MIGRATION_HEADING,
  SMOKE_PUBLIC_API_MIGRATION_ROWS,
  SMOKE_PUBLIC_API_REFERENCE_LINKS,
  SMOKE_PUBLIC_API_ROUTE_PATH,
  SMOKE_PUBLIC_API_SAMPLE_JSON_VALUE,
  SMOKE_PUBLIC_API_STABILITY_COPY,
  SMOKE_PUBLIC_API_STABILITY_HEADING
} from "./fixtures";

test.describe("public API smoke", () => {
  test("renders the static developers reference without live data", async ({ page }: { page: Page }) => {
    const unexpectedApiRequests: string[] = [];
    page.on("request", (networkRequest: Request) => {
      const requestUrl = new URL(networkRequest.url());
      if (requestUrl.pathname.startsWith("/api/")) {
        unexpectedApiRequests.push(`${networkRequest.method()} ${requestUrl.pathname}`);
      }
    });

    await page.goto("/developers");

    const main = page.getByRole("main");
    await expect(main.getByRole("heading", { name: SMOKE_PUBLIC_API_HEADING })).toBeVisible();

    for (const endpoint of SMOKE_PUBLIC_API_ENDPOINTS) {
      await expect(main.getByRole("heading", { name: endpoint, exact: true })).toBeVisible();
    }

    await expect(main.getByRole("heading", { name: SMOKE_PUBLIC_API_MIGRATION_HEADING })).toBeVisible();
    await expect(main.getByRole("heading", { name: SMOKE_PUBLIC_API_MIGRATION_HEADING })).toHaveCount(1);
    const migrationTable = main.getByRole("table");
    await expect(migrationTable).toHaveCount(1);
    for (const column of SMOKE_PUBLIC_API_MIGRATION_COLUMNS) {
      await expect(migrationTable.getByRole("columnheader", { name: column, exact: true })).toBeVisible();
    }
    for (const migrationRow of SMOKE_PUBLIC_API_MIGRATION_ROWS) {
      const row = migrationTable.getByRole("row").filter({ hasText: migrationRow.source });
      await expect(row).toContainText(migrationRow.civibusEquivalent);
      await expect(row).toContainText(migrationRow.delta);
    }
    await expect(main.getByText(SMOKE_PUBLIC_API_SAMPLE_JSON_VALUE)).toBeVisible();
    await expect(main.getByText(SMOKE_PUBLIC_API_CONTRIBUTOR_CURL)).toBeVisible();
    await expect(main.getByText(SMOKE_PUBLIC_API_EMPLOYER_CURL)).toBeVisible();
    await expect(main.getByText(SMOKE_PUBLIC_API_CONTRIBUTOR_SAMPLE_NAME)).toBeVisible();
    await expect(main.getByText(SMOKE_PUBLIC_API_CONTRIBUTOR_SAMPLE_AMOUNT)).toBeVisible();
    const employerEndpoint = main.getByRole("article").filter({ hasText: SMOKE_PUBLIC_API_ENDPOINTS[3] });
    await expect(employerEndpoint.getByText(SMOKE_PUBLIC_API_EMPLOYER_UNKNOWN_BUCKET)).toBeVisible();
    await expect(employerEndpoint.getByText(SMOKE_PUBLIC_API_EMPLOYER_COVERAGE_FIELD)).toBeVisible();
    await expect(main.getByText(SMOKE_PUBLIC_API_CSV_HEADER)).toBeVisible();

    const stabilitySection = main.getByRole("region", { name: SMOKE_PUBLIC_API_STABILITY_HEADING });
    await expect(stabilitySection.getByText(SMOKE_PUBLIC_API_STABILITY_COPY, { exact: true })).toBeVisible();
    await expect(
      stabilitySection.getByRole("link", { name: SMOKE_PUBLIC_API_METADATA_REFERENCE, exact: true })
    ).toHaveAttribute("href", "/api/public/v1/federal/metadata");
    await expect(stabilitySection.getByText(SMOKE_PUBLIC_API_CACHE_CONTRACT)).toBeVisible();

    for (const referenceLink of SMOKE_PUBLIC_API_REFERENCE_LINKS) {
      await expect(main.getByRole("link", { name: referenceLink })).toHaveAttribute("href", referenceLink);
    }

    await expect(
      page.getByRole("contentinfo").getByRole("link", { name: SMOKE_PUBLIC_API_FOOTER_LINK, exact: true })
    ).toHaveAttribute("href", SMOKE_PUBLIC_API_ROUTE_PATH);

    expect(unexpectedApiRequests).toEqual([]);
  });
});
