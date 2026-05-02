import { expect, test } from "playwright/test";

import {
  SMOKE_CONTEST_FINANCE_LINK_NAME,
  SMOKE_CONTEST_WINNER_NAME,
  SMOKE_OFFICE_RECENT_CONTEST_NAME,
  SMOKE_PERSON_CAMPAIGN_FINANCE_HEADING,
  SMOKE_PERSON_DONORS_AND_VENDORS_HEADING,
  SMOKE_PERSON_LINKED_COMMITTEES_HEADING,
  SMOKE_PERSON_OUTSIDE_SPENDING_HEADING,
  SMOKE_PERSON_GRAPH_ORG_NAME,
  SMOKE_CANDIDACY_DESCRIPTION,
  SMOKE_CANDIDATE_ID,
  SMOKE_CANDIDACY_ID,
  SMOKE_CANDIDACY_PERSON_NAME,
  SMOKE_CANDIDACY_TITLE,
  SMOKE_ENTITY_PORTRAIT_IMAGE_TEST_ID,
  SMOKE_ENTITY_PORTRAIT_SILHOUETTE_TEST_ID,
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
  SMOKE_OFFICE_OFFICEHOLDER_ID,
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
  SMOKE_PERSON_MISSING_PORTRAIT_CANONICAL_NAME,
  SMOKE_PERSON_MISSING_PORTRAIT_FIELD_ID,
  SMOKE_PERSON_NO_PORTRAIT_CANONICAL_NAME,
  SMOKE_PERSON_NO_PORTRAIT_ID,
  SMOKE_ROSTER_DURHAM_PERSON_CANONICAL_NAME,
  SMOKE_ROSTER_DURHAM_PERSON_ID,
  SMOKE_ROSTER_DURHAM_PORTRAIT_URL,
  SMOKE_ROSTER_NC_HOUSE_PERSON_CANONICAL_NAME,
  SMOKE_ROSTER_NC_HOUSE_PERSON_ID,
  SMOKE_ROSTER_NC_HOUSE_PORTRAIT_URL,
  SMOKE_PERSON_TITLE,
  SMOKE_PROVENANCE_LAST_PULLED,
  SMOKE_PROVENANCE_SOURCE_KEY,
  SMOKE_PROVENANCE_SOURCE_NAME,
  SMOKE_TECHNICAL_DISCLOSURE_SUMMARY,
  SMOKE_TRUST_ADVISORY,
  SMOKE_TRUST_EMPTY_MESSAGE,
  SMOKE_TRUST_LAST_PULLED_UNAVAILABLE,
  SMOKE_USE_LIVE_API
} from "./fixtures";
import {
  capturePageLoadErrors,
  assertBreadcrumbJsonLd,
  assertBreadcrumbNav,
  assertSeoHead,
  assertSourceRecordLink
} from "./smoke-helpers";

test.describe("entity and civic detail smoke", () => {
  // Fixture-mode-only: tests below assert synthetic provenance, names, and IDs
  // that only resolve under the fixture-backend. Live-mode coverage of the
  // Stage 7 completed sections lives in the 'live mode' describe block below
  // so we don't false-fail real-DB runs on fixture-specific text. See bug
  // live-mode-spec-fixture-mismatch.
  test.skip(SMOKE_USE_LIVE_API, "fixture-only — live coverage in entity/civic live-mode block");

  test("/person/[id] renders SSR detail presentation", async ({ page }: { page: any }) => {
    // Page-load error capture moved to the live-mode block: under fixture mode
    // the synthetic backend does not implement the candidate-finance-sections
    // endpoint, so the SSR loader logs a 404 and a console.error fires before
    // the page is fully assembled. Asserting clean page load belongs to the
    // live-backed run where the real API serves all section endpoints.
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
    await expect(page.getByRole("heading", { name: "Officeholding timeline" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Candidacies" })).toBeVisible();
    await expect(page.getByRole("heading", { name: SMOKE_PERSON_CAMPAIGN_FINANCE_HEADING })).toBeVisible();
    // Stage 7 deep finance/IE panel coverage (Linked committees, Donors and
    // vendors, Outside Spending) is asserted in the live-mode describe block
    // below — the fixture-backend stub returns "Campaign-finance sections
    // are temporarily unavailable" for the person finance bundle, so those
    // panels never render under fixture-mode coverage.
    await expect(page.getByRole("heading", { name: "Identifiers" })).toBeVisible();
    await expect(page.getByTestId("entity-metric-identifiers")).toContainText("1");
    await expect(page.getByTestId("entity-metric-er-matches")).toContainText("0");
    await expect(page.getByTestId("entity-metric-graph-relationships")).toContainText("2");
    await expect(page.getByText("Loading...")).toHaveCount(0);
    // ER matches and graph relationships are inside a closed <details> disclosure
    const disclosure = page.getByRole("group", { name: "Entity internals" });
    await expect(disclosure).toHaveCount(1);
    await expect(page.getByText(SMOKE_TECHNICAL_DISCLOSURE_SUMMARY)).toBeVisible();
    await expect(page.getByTestId(SMOKE_ENTITY_PORTRAIT_IMAGE_TEST_ID)).toBeVisible();
    await expect(page.getByTestId(SMOKE_ENTITY_PORTRAIT_SILHOUETTE_TEST_ID)).toHaveCount(0);
  });

  test("/person/[id] with portrait null renders shared silhouette fallback", async ({ page }: { page: any }) => {
    await page.goto(`/person/${SMOKE_PERSON_NO_PORTRAIT_ID}`);

    await expect(page.getByRole("heading", { name: SMOKE_PERSON_NO_PORTRAIT_CANONICAL_NAME })).toBeVisible();
    await expect(page.getByTestId(SMOKE_ENTITY_PORTRAIT_SILHOUETTE_TEST_ID)).toBeVisible();
    await expect(page.getByTestId(SMOKE_ENTITY_PORTRAIT_IMAGE_TEST_ID)).toHaveCount(0);
  });

  test("/person/[id] missing portrait field renders shared silhouette fallback", async ({ page }: { page: any }) => {
    await page.goto(`/person/${SMOKE_PERSON_MISSING_PORTRAIT_FIELD_ID}`);

    await expect(page.getByRole("heading", { name: SMOKE_PERSON_MISSING_PORTRAIT_CANONICAL_NAME })).toBeVisible();
    await expect(page.getByTestId(SMOKE_ENTITY_PORTRAIT_SILHOUETTE_TEST_ID)).toBeVisible();
    await expect(page.getByTestId(SMOKE_ENTITY_PORTRAIT_IMAGE_TEST_ID)).toHaveCount(0);
  });

  test("/person/[id] for Durham roster member renders roster-sourced portrait image", async ({
    page
  }: {
    page: any;
  }) => {
    await page.goto(`/person/${SMOKE_ROSTER_DURHAM_PERSON_ID}`);

    await expect(
      page.getByRole("heading", { name: SMOKE_ROSTER_DURHAM_PERSON_CANONICAL_NAME })
    ).toBeVisible();
    const portrait = page.getByTestId(SMOKE_ENTITY_PORTRAIT_IMAGE_TEST_ID);
    await expect(portrait).toBeVisible();
    await expect(portrait).toHaveAttribute("src", SMOKE_ROSTER_DURHAM_PORTRAIT_URL);
    await expect(page.getByTestId(SMOKE_ENTITY_PORTRAIT_SILHOUETTE_TEST_ID)).toHaveCount(0);
  });

  test("/person/[id] for NC House roster member renders roster-sourced portrait image", async ({
    page
  }: {
    page: any;
  }) => {
    await page.goto(`/person/${SMOKE_ROSTER_NC_HOUSE_PERSON_ID}`);

    await expect(
      page.getByRole("heading", { name: SMOKE_ROSTER_NC_HOUSE_PERSON_CANONICAL_NAME })
    ).toBeVisible();
    const portrait = page.getByTestId(SMOKE_ENTITY_PORTRAIT_IMAGE_TEST_ID);
    await expect(portrait).toBeVisible();
    await expect(portrait).toHaveAttribute("src", SMOKE_ROSTER_NC_HOUSE_PORTRAIT_URL);
    await expect(page.getByTestId(SMOKE_ENTITY_PORTRAIT_SILHOUETTE_TEST_ID)).toHaveCount(0);
  });

  test("/person/[id] graph keyboard navigation works with arrow, enter, and escape", async ({
    page
  }: {
    page: any;
  }) => {
    await page.goto(`/person/${SMOKE_PERSON_ID}`);

    // Open the Entity internals disclosure
    await page.getByText(SMOKE_TECHNICAL_DISCLOSURE_SUMMARY).click();

    // Tab from the disclosure summary to reach the graph container
    await page.keyboard.press("Tab");
    // The graph container should be focused — verify via its role
    const graphContainer = page.getByRole("img", { name: /Graph of/ });
    await expect(graphContainer).toBeFocused();

    // ArrowRight selects the first navigable (non-subject) node
    await page.keyboard.press("ArrowRight");
    const status = page.getByRole("status");
    await expect(status).not.toBeEmpty();

    // ArrowRight again advances to the next node (the routable org neighbor)
    await page.keyboard.press("ArrowRight");
    await expect(status).toContainText(SMOKE_PERSON_GRAPH_ORG_NAME);
    await expect(status).toContainText("press Enter to open");

    // ArrowLeft moves back to the previous node
    await page.keyboard.press("ArrowLeft");
    await expect(status).not.toBeEmpty();

    // Advance forward again to the routable org node for Enter test
    await page.keyboard.press("ArrowRight");
    await expect(status).toContainText(SMOKE_PERSON_GRAPH_ORG_NAME);

    await page.keyboard.press("Enter");
    await page.waitForURL(`/org/${SMOKE_ORG_ID}`);
    await expect(page).toHaveURL(`/org/${SMOKE_ORG_ID}`);

    // Navigate back to test Escape
    await page.goto(`/person/${SMOKE_PERSON_ID}`);
    await page.getByText(SMOKE_TECHNICAL_DISCLOSURE_SUMMARY).click();
    await page.keyboard.press("Tab");
    await expect(graphContainer).toBeFocused();

    await page.keyboard.press("ArrowRight");
    await expect(status).not.toBeEmpty();

    await page.keyboard.press("Escape");
    await expect(status).toBeEmpty();
    // Should still be on the person page (not navigated away)
    await expect(page).toHaveURL(`/person/${SMOKE_PERSON_ID}`);
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
    await expect(page.getByTestId("entity-metric-identifiers")).toContainText("1");
    await expect(page.getByTestId("entity-metric-er-matches")).toContainText("0");
    await expect(page.getByTestId("entity-metric-graph-relationships")).toContainText("1");
    await expect(page.getByText("Loading...")).toHaveCount(0);
    // ER/graph are inside closed <details> — only disclosure summary is visible
    const disclosure = page.getByRole("group", { name: "Entity internals" });
    await expect(disclosure).toHaveCount(1);
    await expect(page.getByText(SMOKE_TECHNICAL_DISCLOSURE_SUMMARY)).toBeVisible();
  });

  test("/office/[id] renders office detail with officeholder and breadcrumb", async ({ page }: { page: any }) => {
    const pageLoadErrors = capturePageLoadErrors(page);
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
    await expect(page.getByRole("heading", { name: "Current holder" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Current officeholders" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Officeholding timeline" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Recent contests" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "District map context" })).toBeVisible();
    await expect(page.getByRole("link", { name: SMOKE_OFFICE_OFFICEHOLDER_NAME, exact: true })).toHaveAttribute(
      "href",
      `/person/${SMOKE_PERSON_ID}`
    );
    await expect(page.getByRole("link", { name: SMOKE_OFFICE_RECENT_CONTEST_NAME })).toHaveAttribute(
      "href",
      `/contest/${SMOKE_CONTEST_ID}`
    );
    await expect(
      page.getByRole("link", { name: `View officeholding detail for ${SMOKE_OFFICE_OFFICEHOLDER_NAME}` })
    ).toHaveAttribute(
      "href",
      `/officeholding/${SMOKE_OFFICE_OFFICEHOLDER_ID}`
    );
    await pageLoadErrors.assertNoErrors();
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
    const coverageWarning = page.getByRole("note", { name: "Data coverage warning" });
    await expect(coverageWarning).toBeVisible();
    await expect(coverageWarning).toHaveClass(/caveat-banner/);
    await expect(coverageWarning).toContainText(SMOKE_OFFICE_INCOMPLETE_DATA_WARNING);
    await expect(page.getByText(SMOKE_TRUST_LAST_PULLED_UNAVAILABLE)).toBeVisible();
    await expect(page.getByText(SMOKE_TRUST_EMPTY_MESSAGE)).toBeVisible();
    await assertBreadcrumbNav(page);
    await assertBreadcrumbJsonLd(page);
  });

  // Civic detail routes: contest, candidacy, officeholding
  // These routes are detail-only (link-navigable from person/office pages).
  // Backend search supports contest and candidate lookups; candidacy/officeholding remain detail routes.

  test("/contest/[id] renders contest detail with candidacy list and breadcrumb", async ({ page }: { page: any }) => {
    const pageLoadErrors = capturePageLoadErrors(page);
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
    await expect(page.getByRole("heading", { name: "Results" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Candidacies" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Candidate finance and outside spending" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "District map context" })).toBeVisible();
    await expect(page.getByRole("link", { name: "View office record" })).toHaveAttribute(
      "href",
      `/office/${SMOKE_OFFICE_ID}`
    );
    await expect(page.getByRole("link", { name: SMOKE_CONTEST_WINNER_NAME })).toHaveAttribute(
      "href",
      `/person/${SMOKE_PERSON_ID}`
    );
    await expect(page.getByRole("link", { name: SMOKE_CONTEST_FINANCE_LINK_NAME })).toHaveAttribute(
      "href",
      `/candidate/${SMOKE_CANDIDATE_ID}`
    );
    await expect(page.getByRole("link", { name: SMOKE_CANDIDACY_PERSON_NAME, exact: true })).toHaveAttribute(
      "href",
      `/person/${SMOKE_PERSON_ID}`
    );
    await expect(
      page.getByRole("link", { name: `View candidacy detail for ${SMOKE_CANDIDACY_PERSON_NAME}` })
    ).toHaveAttribute(
      "href",
      `/candidacy/${SMOKE_CANDIDACY_ID}`
    );
    await expect(page.getByText(SMOKE_TRUST_ADVISORY)).toBeVisible();
    await expect(page.getByText(SMOKE_PROVENANCE_LAST_PULLED)).toHaveCount(1);
    await assertBreadcrumbNav(page);
    await assertBreadcrumbJsonLd(page);
    await pageLoadErrors.assertNoErrors();
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
    await expect(page.getByRole("link", { name: "View contest record" })).toHaveAttribute(
      "href",
      `/contest/${SMOKE_CONTEST_ID}`
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
    await expect(page.getByRole("link", { name: "View office record" })).toHaveAttribute(
      "href",
      `/office/${SMOKE_OFFICE_ID}`
    );
    await expect(page.getByRole("heading", { name: "Officeholding facts" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Key metrics" })).toBeVisible();
    await expect(page.getByText(SMOKE_TRUST_ADVISORY)).toBeVisible();
    await expect(page.getByText(SMOKE_PROVENANCE_LAST_PULLED)).toHaveCount(1);
    await assertBreadcrumbNav(page);
    await assertBreadcrumbJsonLd(page);
  });
});

// Stage 7 live-mode coverage: assert structural section headings the upstream
// stages (2/3/5) wired up against the real DB-backed records. Operators
// override SMOKE_PERSON_ID, SMOKE_CONTEST_ID, SMOKE_OFFICE_ID via env so the
// same constants point at known-populated live records. We deliberately
// avoid asserting fixture-only names/provenance/IDs here so live runs do not
// false-fail on text that only the fixture-backend serves.
test.describe("entity and civic detail smoke (live mode)", () => {
  test.skip(!SMOKE_USE_LIVE_API, "live-mode only — set SMOKE_USE_LIVE_API=1");

  test("/person/[id] renders Stage 2 completed sections against live data", async ({ page }: { page: any }) => {
    const pageLoadErrors = capturePageLoadErrors(page);
    await page.goto(`/person/${SMOKE_PERSON_ID}`);

    await expect(page.getByRole("heading", { name: "Key metrics" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Officeholding timeline" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Candidacies" })).toBeVisible();
    await expect(page.getByRole("heading", { name: SMOKE_PERSON_CAMPAIGN_FINANCE_HEADING })).toBeVisible();
    await expect(page.getByRole("heading", { name: SMOKE_PERSON_LINKED_COMMITTEES_HEADING })).toBeVisible();
    await expect(page.getByRole("heading", { name: SMOKE_PERSON_DONORS_AND_VENDORS_HEADING })).toBeVisible();
    await expect(page.getByRole("heading", { name: SMOKE_PERSON_OUTSIDE_SPENDING_HEADING })).toBeVisible();
    await assertBreadcrumbNav(page);
    await pageLoadErrors.assertNoErrors();
  });

  test("/contest/[id] renders Stage 3 completed sections against live data", async ({ page }: { page: any }) => {
    const pageLoadErrors = capturePageLoadErrors(page);
    await page.goto(`/contest/${SMOKE_CONTEST_ID}`);

    await expect(page.getByRole("heading", { name: "Contest facts" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Key metrics" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Results" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Candidacies" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Candidate finance and outside spending" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "District map context" })).toBeVisible();
    await expect(page.getByRole("link", { name: /View candidacy detail for/ }).first()).toBeVisible();
    await assertBreadcrumbNav(page);
    await pageLoadErrors.assertNoErrors();
  });

  test("/office/[id] renders Stage 5 completed sections against live data", async ({ page }: { page: any }) => {
    const pageLoadErrors = capturePageLoadErrors(page);
    await page.goto(`/office/${SMOKE_OFFICE_ID}`);

    await expect(page.getByRole("heading", { name: "Key metrics" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Current holder" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Current officeholders" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Officeholding timeline" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Recent contests" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "District map context" })).toBeVisible();
    await expect(page.getByRole("link", { name: /View officeholding detail for/ }).first()).toBeVisible();
    const recentContestsRegion = page.getByRole("region", { name: "Recent contests" });
    await expect(recentContestsRegion.getByRole("link", { name: /\d{4}/ }).first()).toBeVisible();
    await assertBreadcrumbNav(page);
    await pageLoadErrors.assertNoErrors();
  });
});
