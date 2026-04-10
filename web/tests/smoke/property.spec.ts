import { expect, test } from "playwright/test";

import {
  SMOKE_EMPTY_PROPERTY_DESCRIPTION,
  SMOKE_EMPTY_PROPERTY_ID,
  SMOKE_EMPTY_PROPERTY_PAGE_TITLE,
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
    await expect(page.getByText("owner: Civibus Homeowner")).toBeVisible();
    await expect(page.getByText("tax year: 2025")).toBeVisible();
    await expect(page.getByText(SMOKE_PROPERTY_GEOMETRY_PLACEHOLDER_MESSAGE)).toBeVisible();
    await expect(page.getByText(SMOKE_PROPERTY_PROVENANCE_SOURCE_NAME)).toBeVisible();
    await expect(page.getByText(SMOKE_PROPERTY_PROVENANCE_SOURCE_KEY)).toBeVisible();
    await expect(page.getByText(SMOKE_PROVENANCE_LAST_PULLED)).toHaveCount(1);
    await expect(page.getByText(SMOKE_TRUST_ADVISORY)).toBeVisible();
    await assertSourceRecordLink(page, "https://example.org/parcel-1");
    await expect(page.getByRole("link", { name: "Report a data issue" }).first()).toHaveAttribute(
      "href",
      "mailto:team@civibus.org?subject=Civibus%20data%20issue"
    );
    await expect(page.getByRole("link", { name: "linked person" })).toHaveAttribute(
      "href",
      `/person/${SMOKE_PERSON_ID}`
    );
    await expect(page.getByRole("link", { name: "linked organization" })).toHaveAttribute(
      "href",
      `/org/${SMOKE_ORG_ID}`
    );
    await assertBreadcrumbNav(page);
    await assertBreadcrumbJsonLd(page);
    await expect(page.getByRole("heading", { name: "Key metrics" })).toBeVisible();
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
    await expect(page.getByText(SMOKE_PROPERTY_EMPTY_OWNERSHIP_STATE)).toBeVisible();
    await expect(page.getByText(SMOKE_PROPERTY_EMPTY_ASSESSMENT_STATE)).toBeVisible();
    await expect(page.getByText(SMOKE_PROPERTY_GEOMETRY_PLACEHOLDER_MESSAGE)).toBeVisible();
    await expect(page.getByText(SMOKE_TRUST_LAST_PULLED_UNAVAILABLE)).toBeVisible();
    await expect(page.getByText(SMOKE_TRUST_EMPTY_MESSAGE)).toBeVisible();
    await assertBreadcrumbNav(page);
    await assertBreadcrumbJsonLd(page);
  });
});
