import { expect, test } from "playwright/test";

import {
  SMOKE_CANDIDACY_DESCRIPTION,
  SMOKE_CANDIDACY_ID,
  SMOKE_CANDIDACY_PERSON_NAME,
  SMOKE_CANDIDACY_TITLE,
  SMOKE_CONTEST_DESCRIPTION,
  SMOKE_CONTEST_ID,
  SMOKE_CONTEST_NAME,
  SMOKE_CONTEST_TITLE,
  SMOKE_EMPTY_OFFICE_DESCRIPTION,
  SMOKE_EMPTY_OFFICE_ID,
  SMOKE_EMPTY_OFFICE_NAME,
  SMOKE_EMPTY_OFFICE_TITLE,
  SMOKE_OFFICE_DESCRIPTION,
  SMOKE_OFFICE_ID,
  SMOKE_OFFICE_INCOMPLETE_DATA_WARNING,
  SMOKE_OFFICE_NAME,
  SMOKE_OFFICE_OFFICEHOLDER_NAME,
  SMOKE_OFFICE_TITLE,
  SMOKE_OFFICEHOLDER_EMPTY_STATE,
  SMOKE_OFFICEHOLDING_DESCRIPTION,
  SMOKE_OFFICEHOLDING_ID,
  SMOKE_OFFICEHOLDING_PERSON_NAME,
  SMOKE_OFFICEHOLDING_TITLE,
  SMOKE_ORG_CANONICAL_NAME,
  SMOKE_ORG_DESCRIPTION,
  SMOKE_ORG_ID,
  SMOKE_ORG_TITLE,
  SMOKE_PERSON_CANONICAL_NAME,
  SMOKE_PERSON_DESCRIPTION,
  SMOKE_PERSON_ID,
  SMOKE_PERSON_TITLE,
  SMOKE_PROVENANCE_LAST_PULLED,
  SMOKE_PROVENANCE_SOURCE_KEY,
  SMOKE_PROVENANCE_SOURCE_NAME,
  SMOKE_TECHNICAL_DISCLOSURE_SUMMARY,
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

test.describe("entity and civic detail smoke", () => {
  test("/person/[id] renders SSR detail presentation", async ({ page }: { page: any }) => {
    await page.goto(`/person/${SMOKE_PERSON_ID}`);

    await expect(page).toHaveTitle(SMOKE_PERSON_TITLE);
    await expect(page.locator('meta[name="description"]')).toHaveAttribute(
      "content",
      SMOKE_PERSON_DESCRIPTION
    );
    await assertSeoHead(page, {
      title: SMOKE_PERSON_TITLE,
      description: SMOKE_PERSON_DESCRIPTION,
      ogType: "profile",
      jsonLdCount: 1
    });
    await expect(page.getByRole("heading", { name: SMOKE_PERSON_CANONICAL_NAME })).toBeVisible();
    await expect(page.getByText(SMOKE_PROVENANCE_SOURCE_NAME)).toBeVisible();
    await expect(page.getByText(SMOKE_PROVENANCE_LAST_PULLED)).toHaveCount(1);
    await expect(page.getByText(SMOKE_PROVENANCE_SOURCE_KEY)).toBeVisible();
    await expect(page.getByText(SMOKE_TRUST_ADVISORY)).toBeVisible();
    await assertSourceRecordLink(page, "https://example.org/person-1");
    await expect(page.getByRole("link", { name: "Report a data issue" }).first()).toHaveAttribute(
      "href",
      "mailto:team@civibus.org?subject=Civibus%20data%20issue"
    );
    await assertBreadcrumbNav(page);
    await assertBreadcrumbJsonLd(page);
    await expect(page.getByRole("heading", { name: "Key metrics" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Identifiers" })).toBeVisible();
    // ER matches and graph relationships are inside a closed <details> disclosure
    const disclosure = page.getByRole("group", { name: "Entity internals" });
    await expect(disclosure).toHaveCount(1);
    await expect(page.getByText(SMOKE_TECHNICAL_DISCLOSURE_SUMMARY)).toBeVisible();
  });

  test("/org/[id] renders detail via /v1/org + /v1/er/organization + /v1/graph/org", async ({
    page
  }: {
    page: any;
  }) => {
    await page.goto(`/org/${SMOKE_ORG_ID}`);

    await expect(page).toHaveTitle(SMOKE_ORG_TITLE);
    await expect(page.locator('meta[name="description"]')).toHaveAttribute(
      "content",
      SMOKE_ORG_DESCRIPTION
    );
    await assertSeoHead(page, {
      title: SMOKE_ORG_TITLE,
      description: SMOKE_ORG_DESCRIPTION,
      ogType: "website",
      jsonLdCount: 1
    });
    await expect(page.getByRole("heading", { name: SMOKE_ORG_CANONICAL_NAME })).toBeVisible();
    await expect(page.getByText("Organization type")).toBeVisible();
    await expect(page.getByText(SMOKE_PROVENANCE_SOURCE_NAME)).toBeVisible();
    await expect(page.getByText(SMOKE_PROVENANCE_LAST_PULLED)).toHaveCount(1);
    await assertBreadcrumbNav(page);
    await assertBreadcrumbJsonLd(page);
    await expect(page.getByRole("heading", { name: "Key metrics" })).toBeVisible();
    // ER/graph are inside closed <details> — only disclosure summary is visible
    const disclosure = page.getByRole("group", { name: "Entity internals" });
    await expect(disclosure).toHaveCount(1);
    await expect(page.getByText(SMOKE_TECHNICAL_DISCLOSURE_SUMMARY)).toBeVisible();
  });

  test("/office/[id] renders office detail with officeholder and breadcrumb", async ({ page }: { page: any }) => {
    await page.goto(`/office/${SMOKE_OFFICE_ID}`);

    await expect(page).toHaveTitle(SMOKE_OFFICE_TITLE);
    await expect(page.locator('meta[name="description"]')).toHaveAttribute(
      "content",
      SMOKE_OFFICE_DESCRIPTION
    );
    await assertSeoHead(page, {
      title: SMOKE_OFFICE_TITLE,
      description: SMOKE_OFFICE_DESCRIPTION,
      ogType: "website",
      jsonLdCount: 1
    });
    await expect(page.getByRole("heading", { name: SMOKE_OFFICE_NAME })).toBeVisible();
    await expect(page.getByText(SMOKE_TRUST_ADVISORY)).toBeVisible();
    await expect(page.getByText(SMOKE_PROVENANCE_LAST_PULLED)).toHaveCount(1);
    await assertBreadcrumbNav(page);
    await assertBreadcrumbJsonLd(page);
    await expect(page.getByRole("heading", { name: "Key metrics" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Current officeholders" })).toBeVisible();
    await expect(page.getByRole("link", { name: SMOKE_OFFICE_OFFICEHOLDER_NAME })).toHaveAttribute(
      "href",
      `/person/${SMOKE_PERSON_ID}`
    );
  });

  test("/office/[id] empty fixture shows officeholder empty state and incomplete data warning", async ({
    page
  }: {
    page: any;
  }) => {
    await page.goto(`/office/${SMOKE_EMPTY_OFFICE_ID}`);

    await expect(page).toHaveTitle(SMOKE_EMPTY_OFFICE_TITLE);
    await expect(page.locator('meta[name="description"]')).toHaveAttribute(
      "content",
      SMOKE_EMPTY_OFFICE_DESCRIPTION
    );
    await assertSeoHead(page, {
      title: SMOKE_EMPTY_OFFICE_TITLE,
      description: SMOKE_EMPTY_OFFICE_DESCRIPTION,
      ogType: "website",
      jsonLdCount: 1
    });
    await expect(page.getByRole("heading", { name: SMOKE_EMPTY_OFFICE_NAME })).toBeVisible();
    await expect(page.getByText(SMOKE_OFFICEHOLDER_EMPTY_STATE)).toBeVisible();
    await expect(page.getByText(SMOKE_OFFICE_INCOMPLETE_DATA_WARNING)).toBeVisible();
    await expect(page.getByText(SMOKE_TRUST_LAST_PULLED_UNAVAILABLE)).toBeVisible();
    await expect(page.getByText(SMOKE_TRUST_EMPTY_MESSAGE)).toBeVisible();
    await assertBreadcrumbNav(page);
    await assertBreadcrumbJsonLd(page);
  });

  // Civic detail routes: contest, candidacy, officeholding
  // These routes are detail-only (link-navigable from person/office pages).
  // Backend search does NOT support contest/candidacy/officeholding — only office is searchable.

  test("/contest/[id] renders contest detail with candidacy list and breadcrumb", async ({ page }: { page: any }) => {
    await page.goto(`/contest/${SMOKE_CONTEST_ID}`);

    await expect(page).toHaveTitle(SMOKE_CONTEST_TITLE);
    await expect(page.locator('meta[name="description"]')).toHaveAttribute(
      "content",
      SMOKE_CONTEST_DESCRIPTION
    );
    await assertSeoHead(page, {
      title: SMOKE_CONTEST_TITLE,
      description: SMOKE_CONTEST_DESCRIPTION,
      ogType: "website",
      jsonLdCount: 1
    });
    await expect(page.getByRole("heading", { name: SMOKE_CONTEST_NAME })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Contest facts" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Key metrics" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Candidacies" })).toBeVisible();
    await expect(page.getByRole("link", { name: SMOKE_CANDIDACY_PERSON_NAME })).toHaveAttribute(
      "href",
      `/person/${SMOKE_PERSON_ID}`
    );
    await expect(page.getByText(SMOKE_TRUST_ADVISORY)).toBeVisible();
    await expect(page.getByText(SMOKE_PROVENANCE_LAST_PULLED)).toHaveCount(1);
    await assertBreadcrumbNav(page);
    await assertBreadcrumbJsonLd(page);
  });

  test("/candidacy/[id] renders candidacy detail with person link and breadcrumb", async ({ page }: { page: any }) => {
    await page.goto(`/candidacy/${SMOKE_CANDIDACY_ID}`);

    await expect(page).toHaveTitle(SMOKE_CANDIDACY_TITLE);
    await expect(page.locator('meta[name="description"]')).toHaveAttribute(
      "content",
      SMOKE_CANDIDACY_DESCRIPTION
    );
    await assertSeoHead(page, {
      title: SMOKE_CANDIDACY_TITLE,
      description: SMOKE_CANDIDACY_DESCRIPTION,
      ogType: "profile",
      jsonLdCount: 1
    });
    await expect(page.getByRole("heading", { name: `${SMOKE_CANDIDACY_PERSON_NAME} candidacy` })).toBeVisible();
    await expect(page.getByRole("link", { name: "View person record" })).toHaveAttribute(
      "href",
      `/person/${SMOKE_PERSON_ID}`
    );
    await expect(page.getByRole("heading", { name: "Candidacy facts" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Key metrics" })).toBeVisible();
    await expect(page.getByText(SMOKE_TRUST_ADVISORY)).toBeVisible();
    await expect(page.getByText(SMOKE_PROVENANCE_LAST_PULLED)).toHaveCount(1);
    await assertBreadcrumbNav(page);
    await assertBreadcrumbJsonLd(page);
  });

  test("/officeholding/[id] renders officeholding detail with person link and breadcrumb", async ({ page }: { page: any }) => {
    await page.goto(`/officeholding/${SMOKE_OFFICEHOLDING_ID}`);

    await expect(page).toHaveTitle(SMOKE_OFFICEHOLDING_TITLE);
    await expect(page.locator('meta[name="description"]')).toHaveAttribute(
      "content",
      SMOKE_OFFICEHOLDING_DESCRIPTION
    );
    await assertSeoHead(page, {
      title: SMOKE_OFFICEHOLDING_TITLE,
      description: SMOKE_OFFICEHOLDING_DESCRIPTION,
      ogType: "website",
      jsonLdCount: 1
    });
    await expect(page.getByRole("heading", { name: `${SMOKE_OFFICEHOLDING_PERSON_NAME} officeholding` })).toBeVisible();
    await expect(page.getByRole("link", { name: "View person record" })).toHaveAttribute(
      "href",
      `/person/${SMOKE_PERSON_ID}`
    );
    await expect(page.getByRole("heading", { name: "Officeholding facts" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Key metrics" })).toBeVisible();
    await expect(page.getByText(SMOKE_TRUST_ADVISORY)).toBeVisible();
    await expect(page.getByText(SMOKE_PROVENANCE_LAST_PULLED)).toHaveCount(1);
    await assertBreadcrumbNav(page);
    await assertBreadcrumbJsonLd(page);
  });
});
