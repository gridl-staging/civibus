import { expect, test } from "playwright/test";

import {
  SMOKE_EMPTY_PROPERTY_DESCRIPTION,
  SMOKE_EMPTY_PROPERTY_ID,
  SMOKE_EMPTY_PROPERTY_PAGE_TITLE,
  SMOKE_EMPTY_PROPERTY_TITLE,
  SMOKE_ORG_ID,
  SMOKE_PERSON_ID,
  SMOKE_PROPERTY_DESCRIPTION,
  SMOKE_PROPERTY_EMPTY_ASSESSMENT_STATE,
  SMOKE_PROPERTY_EMPTY_OWNERSHIP_STATE,
  SMOKE_PROPERTY_GEOMETRY_PLACEHOLDER_MESSAGE,
  SMOKE_PROPERTY_ID,
  SMOKE_PROPERTY_PAGE_TITLE,
  SMOKE_PROPERTY_PROVENANCE_SOURCE_KEY,
  SMOKE_PROPERTY_PROVENANCE_SOURCE_NAME,
  SMOKE_PROPERTY_TITLE,
  SMOKE_PROVENANCE_LAST_PULLED,
  SMOKE_TRUST_ADVISORY,
  SMOKE_TRUST_EMPTY_MESSAGE,
  SMOKE_TRUST_LAST_PULLED_UNAVAILABLE
} from "./fixtures";
import {
  assertBreadcrumbJsonLd,
  assertBreadcrumbNav,
  assertSeoHead,
  assertSourceRecordLink
} from "./smoke-helpers";

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

test.describe("property smoke", () => {
  test("/property/[id] renders parcel details and geometry placeholder", async ({ page }: { page: any }) => {
    await page.goto(`/property/${SMOKE_PROPERTY_ID}`);

    await expect(page).toHaveTitle(SMOKE_PROPERTY_PAGE_TITLE);
    await expect(page.locator('meta[name="description"]')).toHaveAttribute(
      "content",
      SMOKE_PROPERTY_DESCRIPTION
    );
    await assertSeoHead(page, {
      title: SMOKE_PROPERTY_PAGE_TITLE,
      description: SMOKE_PROPERTY_DESCRIPTION,
      ogType: "website",
      jsonLdCount: 1
    });
    await expect(page.getByRole("heading", { name: SMOKE_PROPERTY_TITLE })).toBeVisible();
    await expect(page.getByRole("heading", { level: 3 })).toHaveText([
      "Parcel facts",
      "Source and freshness",
      "Key metrics",
      "Ownership history",
      "Assessment history",
      "Map and geometry"
    ]);

    await expect(page.getByText(/REID\s*200000001/)).toBeVisible();
    await expect(page.getByText(/PIN\s*0999999999/)).toBeVisible();
    await expect(page.getByText(/Site address\s*123 MAIN ST/)).toBeVisible();
    await expect(page.getByText(/Property description\s*Single family home/)).toBeVisible();
    await expect(page.getByText(/City\s*Durham/)).toBeVisible();
    await expect(page.getByText(/Zoning class\s*R-20/)).toBeVisible();
    await expect(page.getByText(/Land class\s*Residential/)).toBeVisible();
    await expect(page.getByText(/Acreage\s*1.2500/)).toBeVisible();
    await expect(page.getByText(/Neighborhood\s*Northside/)).toBeVisible();
    await expect(page.getByText(/Fire district\s*Durham/)).toBeVisible();
    await expect(page.getByText(/Pending\s*No/)).toBeVisible();
    await expect(page.getByText(/Deed date\s*2024-01-15/)).toBeVisible();
    await expect(page.getByText(/Deed book\s*1234/)).toBeVisible();
    await expect(page.getByText(/Deed page\s*567/)).toBeVisible();

    await expect(page.getByText(/Ownership records\s*1/)).toBeVisible();
    await expect(page.getByText(/Assessments\s*1/)).toBeVisible();

    await expect(page.getByRole("table")).toHaveCount(2);
    const ownershipTable = page.getByRole("table").nth(0);
    const assessmentTable = page.getByRole("table").nth(1);

    await expect(ownershipTable.getByRole("columnheader", { name: "Owner" })).toBeVisible();
    await expect(ownershipTable.getByRole("columnheader", { name: "Recorded at" })).toBeVisible();
    await expect(ownershipTable.getByRole("columnheader", { name: "Valid period" })).toBeVisible();
    await expect(ownershipTable.getByRole("columnheader", { name: "Date precision" })).toBeVisible();
    await expect(ownershipTable.getByRole("columnheader", { name: "Mailing address" })).toBeVisible();
    await expect(ownershipTable.getByRole("columnheader", { name: "Linked records" })).toBeVisible();

    await expect(ownershipTable.getByText("Civibus Homeowner", { exact: true })).toBeVisible();
    await expect(ownershipTable.getByText("2024-02-01", { exact: true })).toBeVisible();
    await expect(ownershipTable.getByText("[2024-02-01,)")).toBeVisible();
    await expect(ownershipTable.getByText("day", { exact: true })).toBeVisible();
    await expect(ownershipTable.getByText("123 MAIN ST, Durham, NC, 27701")).toBeVisible();

    await expect(assessmentTable.getByRole("columnheader", { name: "Tax year" })).toBeVisible();
    await expect(assessmentTable.getByRole("columnheader", { name: "Land assessed value" })).toBeVisible();
    await expect(assessmentTable.getByRole("columnheader", { name: "Improvement assessed value" })).toBeVisible();
    await expect(assessmentTable.getByRole("columnheader", { name: "Total assessed value" })).toBeVisible();
    await expect(assessmentTable.getByRole("columnheader", { name: "Assessed at" })).toBeVisible();
    await expect(assessmentTable.getByRole("columnheader", { name: "Heated area" })).toBeVisible();
    await expect(assessmentTable.getByRole("columnheader", { name: "Exemption" })).toBeVisible();

    await expect(assessmentTable.getByText("2025", { exact: true })).toBeVisible();
    await expect(assessmentTable.getByText("150000.00")).toBeVisible();
    await expect(assessmentTable.getByText("350000.00")).toBeVisible();
    await expect(assessmentTable.getByText("500000.00")).toBeVisible();
    await expect(assessmentTable.getByText("2025-01-31")).toBeVisible();
    await expect(assessmentTable.getByText("2500", { exact: true })).toBeVisible();
    await expect(assessmentTable.getByText("Homestead")).toBeVisible();

    await expect(page.getByText("owner: Civibus Homeowner")).toHaveCount(0);
    await expect(page.getByText("tax year: 2025")).toHaveCount(0);

    const caveatsPanel = page.getByRole("note", { name: "Parcel geometry placeholder" });
    await expect(caveatsPanel).toBeVisible();
    await expect(caveatsPanel.getByText(SMOKE_PROPERTY_GEOMETRY_PLACEHOLDER_MESSAGE)).toBeVisible();

    await expect(page.getByText(SMOKE_PROPERTY_PROVENANCE_SOURCE_NAME)).toBeVisible();
    await expect(page.getByText(SMOKE_PROPERTY_PROVENANCE_SOURCE_KEY)).toBeVisible();
    await expect(page.getByText(SMOKE_PROVENANCE_LAST_PULLED)).toHaveCount(1);
    await expect(page.getByText(SMOKE_TRUST_ADVISORY)).toBeVisible();
    await assertSourceRecordLink(page, "https://example.org/parcel-1");
    await expect(page.getByRole("link", { name: "Report a data issue" }).first()).toHaveAttribute(
      "href",
      "mailto:team@civibus.org?subject=Civibus%20data%20issue"
    );

    await expect(page.getByRole("link", { name: "View person record for Civibus Homeowner" })).toHaveAttribute(
      "href",
      `/person/${SMOKE_PERSON_ID}`
    );
    await expect(
      page.getByRole("link", { name: "View organization record for Civibus Homeowner" })
    ).toHaveAttribute(
      "href",
      `/org/${SMOKE_ORG_ID}`
    );

    await assertBreadcrumbNav(page);
    await assertBreadcrumbJsonLd(page);
  });

  test("/property/[id] empty fixture shows ownership/assessment empty states and trust empty copy", async ({
    page
  }: {
    page: any;
  }) => {
    await page.goto(`/property/${SMOKE_EMPTY_PROPERTY_ID}`);

    await expect(page).toHaveTitle(SMOKE_EMPTY_PROPERTY_PAGE_TITLE);
    await expect(page.locator('meta[name="description"]')).toHaveAttribute(
      "content",
      SMOKE_EMPTY_PROPERTY_DESCRIPTION
    );
    await assertSeoHead(page, {
      title: SMOKE_EMPTY_PROPERTY_PAGE_TITLE,
      description: SMOKE_EMPTY_PROPERTY_DESCRIPTION,
      ogType: "website",
      jsonLdCount: 1
    });

    await expect(page.getByRole("heading", { name: SMOKE_EMPTY_PROPERTY_TITLE })).toBeVisible();
    await expect(page.getByRole("heading", { level: 3 })).toHaveText([
      "Parcel facts",
      "Source and freshness",
      "Key metrics",
      "Ownership history",
      "Assessment history",
      "Map and geometry"
    ]);

    await expect(page.getByText(/REID\s*200000099/)).toBeVisible();
    await expect(page.getByText(/PIN\s*0999999900/)).toBeVisible();
    await expect(page.getByText(/Site address\s*999 EMPTY RD/)).toBeVisible();
    await expect(page.getByText(/Property description\s*—/)).toBeVisible();
    await expect(page.getByText(/City\s*Durham/)).toBeVisible();
    await expect(page.getByText(/Zoning class\s*—/)).toBeVisible();
    await expect(page.getByText(/Land class\s*—/)).toBeVisible();
    await expect(page.getByText(/Acreage\s*—/)).toBeVisible();
    await expect(page.getByText(/Neighborhood\s*—/)).toBeVisible();
    await expect(page.getByText(/Fire district\s*—/)).toBeVisible();
    await expect(page.getByText(/Pending\s*No/)).toBeVisible();
    await expect(page.getByText(/Deed date\s*—/)).toBeVisible();
    await expect(page.getByText(/Deed book\s*—/)).toBeVisible();
    await expect(page.getByText(/Deed page\s*—/)).toBeVisible();

    await expect(page.getByText(/Ownership records\s*0/)).toBeVisible();
    await expect(page.getByText(/Assessments\s*0/)).toBeVisible();

    await expect(page.getByRole("table")).toHaveCount(0);
    const mainContent = page.getByRole("main");
    const ownershipPanelCopyPattern = new RegExp(
      `Ownership history\\s+${escapeRegExp(SMOKE_PROPERTY_EMPTY_OWNERSHIP_STATE)}\\s*Assessment history`
    );
    const assessmentPanelCopyPattern = new RegExp(
      `Assessment history\\s+${escapeRegExp(SMOKE_PROPERTY_EMPTY_ASSESSMENT_STATE)}\\s*Map and geometry`
    );
    await expect(mainContent).toContainText(ownershipPanelCopyPattern);
    await expect(mainContent).toContainText(assessmentPanelCopyPattern);

    await expect(page.getByText("owner: Civibus Homeowner")).toHaveCount(0);
    await expect(page.getByText("tax year: 2025")).toHaveCount(0);
    await expect(page.getByRole("link", { name: /View person record for/ })).toHaveCount(0);
    await expect(page.getByRole("link", { name: /View organization record for/ })).toHaveCount(0);

    const caveatsPanel = page.getByRole("note", { name: "Parcel geometry placeholder" });
    await expect(caveatsPanel).toBeVisible();
    await expect(caveatsPanel.getByText(SMOKE_PROPERTY_GEOMETRY_PLACEHOLDER_MESSAGE)).toBeVisible();

    const trustPanelCopyPattern = new RegExp(
      `Source and freshness[\\s\\S]*${escapeRegExp(SMOKE_TRUST_LAST_PULLED_UNAVAILABLE)}[\\s\\S]*${escapeRegExp(SMOKE_TRUST_EMPTY_MESSAGE)}[\\s\\S]*Key metrics`
    );
    await expect(mainContent).toContainText(trustPanelCopyPattern);

    await assertBreadcrumbNav(page);
    await assertBreadcrumbJsonLd(page);
  });

  test("/property/[id] unknown UUID renders 404 error boundary with recovery links", async ({
    page
  }: {
    page: any;
  }) => {
    const response = await page.goto("/property/00000000-0000-4000-8000-000000000000");

    expect(response?.status()).toBe(404);

    await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
    await expect(page.getByText("HTTP 404")).toBeVisible();

    const returnHomeLink = page.getByRole("link", { name: "Return home" });
    const goToSearchLink = page.getByRole("link", { name: "Go to search" });
    await expect(returnHomeLink).toBeVisible();
    await expect(returnHomeLink).toHaveAttribute("href", "/");
    await expect(goToSearchLink).toBeVisible();
    await expect(goToSearchLink).toHaveAttribute("href", "/search");
  });
});
