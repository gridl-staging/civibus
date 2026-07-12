import { expect, test } from "playwright/test";

import {
  seedLiveCongressDirectorySmoke,
  SMOKE_CONTEST_FINANCE_LINK_NAME,
  SMOKE_CONTEST_WINNER_NAME,
  SMOKE_CONGRESS_PERSON_ID,
  SMOKE_OFFICE_RECENT_CONTEST_NAME,
  SMOKE_PERSON_APPROXIMATE_GEOGRAPHY_NOTE,
  SMOKE_PERSON_CAMPAIGN_FINANCE_HEADING,
  SMOKE_PERSON_CAREER_TOTAL,
  SMOKE_PERSON_CAREER_TOTAL_LABEL,
  SMOKE_PERSON_CYCLE_TOTAL,
  SMOKE_PERSON_CYCLE_TOTAL_LABEL,
  SMOKE_PERSON_DONATION_COUNT_BY_SIZE_HEADING,
  SMOKE_PERSON_DOLLARS_BY_SIZE_HEADING,
  SMOKE_PERSON_DONATIONS_OVER_TIME_HEADING,
  SMOKE_PERSON_DONORS_AND_VENDORS_HEADING,
  SMOKE_PERSON_FUNDRAISING_DETAIL_HEADING,
  SMOKE_PERSON_FUNDRAISING_GEOGRAPHY_HEADING,
  SMOKE_PERSON_LINKED_COMMITTEES_HEADING,
  SMOKE_PERSON_OUTSIDE_SPENDING_HEADING,
  SMOKE_PERSON_DISTRICT_SHARE_HEADLINE,
  SMOKE_PERSON_DISTRICT_SHARE_SUMMARY,
  SMOKE_PERSON_SMALL_DOLLAR_HEADLINE,
  SMOKE_PERSON_TOP_EMPLOYER_DISCLAIMER,
  SMOKE_PERSON_TOP_EMPLOYER_METHODOLOGY,
  SMOKE_PERSON_TOP_EMPLOYER_ONE_NAME,
  SMOKE_PERSON_TOP_EMPLOYER_ONE_TOTAL,
  SMOKE_PERSON_TOP_EMPLOYER_TWO_NAME,
  SMOKE_PERSON_TOP_EMPLOYER_TWO_TOTAL,
  SMOKE_PERSON_TOP_EMPLOYERS_HEADING,
  SMOKE_PERSON_TOP_DONOR_ONE_NAME,
  SMOKE_PERSON_TOP_DONOR_ONE_TOTAL,
  SMOKE_PERSON_TOP_DONOR_TWO_NAME,
  SMOKE_PERSON_TOP_DONOR_TWO_TOTAL,
  SMOKE_PERSON_TOP_DONORS_HEADING,
  SMOKE_PERSON_TOP_SPENDER_NAME,
  SMOKE_PERSON_TOP_SPENDER_TOTAL,
  SMOKE_PERSON_TOP_SPENDERS_HEADING,
  SMOKE_PERSON_UNITEMIZED_BUCKET_LABEL,
  SMOKE_PERSON_UNITEMIZED_EXCLUSION_NOTE,
  SMOKE_CANDIDACY_DESCRIPTION,
  SMOKE_CANDIDATE_NAME,
  SMOKE_CANDIDATE_SLUG,
  SMOKE_CANDIDACY_ID,
  SMOKE_CANDIDACY_PERSON_NAME,
  SMOKE_CANDIDACY_TITLE,
  SMOKE_ENTITY_PORTRAIT_INITIALS_TEST_ID,
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

const MIN_FINANCE_CHART_HEIGHT_PX = 250;
const LIVE_PERSON_ID = process.env.SMOKE_PERSON_ID === undefined ? SMOKE_CONGRESS_PERSON_ID : SMOKE_PERSON_ID;
const SHOULD_SEED_LIVE_PERSON_SMOKE = process.env.SMOKE_PERSON_ID === undefined;
const SHOULD_RUN_LIVE_CONTEST_SMOKE = process.env.SMOKE_CONTEST_ID !== undefined;
const SHOULD_RUN_LIVE_OFFICE_SMOKE = process.env.SMOKE_OFFICE_ID !== undefined;

async function expectFinanceChartHasStableHeight(page: any, chartName: string | RegExp): Promise<void> {
  const chartRegion = page.getByLabel(chartName).first();
  await expect(chartRegion).toBeVisible();
  const chartBox = await chartRegion.boundingBox();
  expect(chartBox?.height ?? 0).toBeGreaterThanOrEqual(MIN_FINANCE_CHART_HEIGHT_PX);
}

async function seedLivePersonSmokeIfNeeded(): Promise<() => Promise<void>> {
  if (SHOULD_SEED_LIVE_PERSON_SMOKE) {
    return seedLiveCongressDirectorySmoke();
  }
  return async () => undefined;
}

test.describe("entity and civic detail smoke", () => {
  // Fixture-mode-only: tests below assert synthetic provenance, names, and IDs
  // that only resolve under the fixture-backend. Live-mode coverage of the
  // Stage 7 completed sections lives in the 'live mode' describe block below
  // so we don't false-fail real-DB runs on fixture-specific text. See bug
  // live-mode-spec-fixture-mismatch.
  test.skip(SMOKE_USE_LIVE_API, "fixture-only — live coverage in entity/civic live-mode block");

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
    await expect(page.getByRole("heading", { name: SMOKE_PERSON_CAMPAIGN_FINANCE_HEADING }).first()).toBeVisible();
    await expectFinanceChartHasStableHeight(page, `Finance chart for ${SMOKE_PERSON_CANONICAL_NAME}`);
    await expect(page.getByRole("heading", { name: SMOKE_PERSON_FUNDRAISING_DETAIL_HEADING })).toBeVisible();
    await expect(page.getByText(SMOKE_PERSON_SMALL_DOLLAR_HEADLINE, { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Individual contribution totals" })).toBeVisible();
    const contributionTotalsSummary = page.getByTestId("person-contribution-total-summary");
    await expect(contributionTotalsSummary.getByText(SMOKE_PERSON_CYCLE_TOTAL, { exact: true })).toBeVisible();
    await expect(contributionTotalsSummary.getByText(SMOKE_PERSON_CAREER_TOTAL, { exact: true })).toHaveCount(0);
    await page
      .getByRole("group", { name: "Contribution totals view" })
      .getByRole("button", { name: SMOKE_PERSON_CAREER_TOTAL_LABEL })
      .click();
    await expect(contributionTotalsSummary.getByText(SMOKE_PERSON_CAREER_TOTAL, { exact: true })).toBeVisible();
    await expectFinanceChartHasStableHeight(page, `Donations over time for ${SMOKE_PERSON_CANONICAL_NAME}`);
    await expectFinanceChartHasStableHeight(page, `Donation count by size bucket for ${SMOKE_PERSON_CANONICAL_NAME}`);
    await expectFinanceChartHasStableHeight(page, `Dollars by size bucket for ${SMOKE_PERSON_CANONICAL_NAME}`);
    await expectFinanceChartHasStableHeight(page, `Fundraising geography for ${SMOKE_PERSON_CANONICAL_NAME}`);
    await expect(page.getByRole("heading", { name: SMOKE_PERSON_DONATIONS_OVER_TIME_HEADING })).toBeVisible();
    await expect(page.getByRole("heading", { name: SMOKE_PERSON_DONATION_COUNT_BY_SIZE_HEADING })).toBeVisible();
    await expect(page.getByRole("heading", { name: SMOKE_PERSON_DOLLARS_BY_SIZE_HEADING })).toBeVisible();
    await expect(page.getByRole("heading", { name: SMOKE_PERSON_FUNDRAISING_GEOGRAPHY_HEADING })).toBeVisible();
    await expect(page.getByText(SMOKE_PERSON_DISTRICT_SHARE_HEADLINE, { exact: true })).toBeVisible();
    await expect(page.getByText(SMOKE_PERSON_DISTRICT_SHARE_SUMMARY, { exact: true })).toBeVisible();
    await expect(page.getByText(SMOKE_PERSON_APPROXIMATE_GEOGRAPHY_NOTE, { exact: true })).toBeVisible();
    await expect(page.getByText(SMOKE_PERSON_UNITEMIZED_BUCKET_LABEL, { exact: true }).first()).toBeVisible();
    await expect(page.getByText(SMOKE_PERSON_UNITEMIZED_EXCLUSION_NOTE)).toBeVisible();
    await expect(page.getByRole("heading", { name: SMOKE_PERSON_TOP_DONORS_HEADING })).toBeVisible();
    const topDonorRows = page.getByTestId("person-top-donors-scroll").getByRole("row");
    await expect(topDonorRows.nth(1)).toContainText(SMOKE_PERSON_TOP_DONOR_ONE_NAME);
    await expect(topDonorRows.nth(1)).toContainText(SMOKE_PERSON_TOP_DONOR_ONE_TOTAL);
    await expect(topDonorRows.nth(2)).toContainText(SMOKE_PERSON_TOP_DONOR_TWO_NAME);
    await expect(topDonorRows.nth(2)).toContainText(SMOKE_PERSON_TOP_DONOR_TWO_TOTAL);
    await expect(page.getByRole("heading", { name: SMOKE_PERSON_TOP_EMPLOYERS_HEADING })).toBeVisible();
    await expect(page.getByText(SMOKE_PERSON_TOP_EMPLOYER_DISCLAIMER, { exact: true })).toBeVisible();
    await expect(page.getByText(SMOKE_PERSON_TOP_EMPLOYER_METHODOLOGY, { exact: true })).toBeVisible();
    const topEmployerRows = page.getByTestId("person-top-employers-scroll").getByRole("row");
    await expect(topEmployerRows.nth(1)).toContainText(SMOKE_PERSON_TOP_EMPLOYER_ONE_NAME);
    await expect(topEmployerRows.nth(1)).toContainText(SMOKE_PERSON_TOP_EMPLOYER_ONE_TOTAL);
    await expect(topEmployerRows.nth(2)).toContainText(SMOKE_PERSON_TOP_EMPLOYER_TWO_NAME);
    await expect(topEmployerRows.nth(2)).toContainText(SMOKE_PERSON_TOP_EMPLOYER_TWO_TOTAL);
    await expect(page.getByRole("heading", { name: SMOKE_PERSON_LINKED_COMMITTEES_HEADING })).toBeVisible();
    await expect(page.getByRole("heading", { name: SMOKE_PERSON_DONORS_AND_VENDORS_HEADING })).toBeVisible();
    await expect(
      page.getByRole("heading", { name: SMOKE_PERSON_OUTSIDE_SPENDING_HEADING, exact: true })
    ).toBeVisible();
    await expectFinanceChartHasStableHeight(page, `Outside spending chart for ${SMOKE_CANDIDATE_NAME}`);
    await expect(page.getByRole("heading", { name: SMOKE_PERSON_TOP_SPENDERS_HEADING })).toBeVisible();
    const topSpenderRows = page.getByTestId("person-ie-top-spenders-scroll").getByRole("row");
    await expect(topSpenderRows.nth(1)).toContainText(SMOKE_PERSON_TOP_SPENDER_NAME);
    await expect(topSpenderRows.nth(1)).toContainText(SMOKE_PERSON_TOP_SPENDER_TOTAL);
    await expect(page.getByRole("heading", { name: "Identifiers" })).toBeVisible();
    await expect(page.getByTestId("entity-metric-identifiers")).toContainText("1");
    await expect(page.getByRole("heading", { name: "Officeholding timeline" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Candidacies" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Graph relationships" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Entity-resolution matches" })).toHaveCount(0);
    await expect(page.getByText("Loading...")).toHaveCount(0);
    await expect(page.getByRole("group", { name: "Entity internals" })).toHaveCount(0);
    await expect(page.getByTestId(SMOKE_ENTITY_PORTRAIT_IMAGE_TEST_ID)).toBeVisible();
    await expect(page.getByTestId(SMOKE_ENTITY_PORTRAIT_SILHOUETTE_TEST_ID)).toHaveCount(0);
  });

  test("/person/[id] with portrait null renders shared fallback avatar", async ({ page }: { page: any }) => {
    await page.goto(`/person/${SMOKE_PERSON_NO_PORTRAIT_ID}`);

    await expect(page.getByRole("heading", { name: SMOKE_PERSON_NO_PORTRAIT_CANONICAL_NAME })).toBeVisible();
    await expect(page.getByTestId(SMOKE_ENTITY_PORTRAIT_INITIALS_TEST_ID)).toBeVisible();
    await expect(page.getByTestId(SMOKE_ENTITY_PORTRAIT_INITIALS_TEST_ID)).toContainText("JP");
    await expect(page.getByTestId(SMOKE_ENTITY_PORTRAIT_IMAGE_TEST_ID)).toHaveCount(0);
    await expect(page.getByTestId(SMOKE_ENTITY_PORTRAIT_SILHOUETTE_TEST_ID)).toHaveCount(0);
  });

  test("/person/[id] missing portrait field renders shared fallback avatar", async ({ page }: { page: any }) => {
    await page.goto(`/person/${SMOKE_PERSON_MISSING_PORTRAIT_FIELD_ID}`);

    await expect(page.getByRole("heading", { name: SMOKE_PERSON_MISSING_PORTRAIT_CANONICAL_NAME })).toBeVisible();
    await expect(page.getByTestId(SMOKE_ENTITY_PORTRAIT_INITIALS_TEST_ID)).toBeVisible();
    await expect(page.getByTestId(SMOKE_ENTITY_PORTRAIT_INITIALS_TEST_ID)).toContainText("AP");
    await expect(page.getByTestId(SMOKE_ENTITY_PORTRAIT_IMAGE_TEST_ID)).toHaveCount(0);
    await expect(page.getByTestId(SMOKE_ENTITY_PORTRAIT_SILHOUETTE_TEST_ID)).toHaveCount(0);
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

  test("/org/[id] renders public detail via /v1/org", async ({
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
    await expect(page.getByRole("heading", { name: "Graph relationships" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Entity-resolution matches" })).toHaveCount(0);
    await expect(page.getByText("Loading...")).toHaveCount(0);
    await expect(page.getByRole("group", { name: "Entity internals" })).toHaveCount(0);
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
    await expect(
      page.getByRole("link", { name: SMOKE_OFFICE_OFFICEHOLDER_NAME, exact: true }).first()
    ).toHaveAttribute("href", `/person/${SMOKE_PERSON_ID}`);
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
    const resultsPanel = page.getByTestId("contest-results-panel");
    await expect(resultsPanel).toBeVisible();
    await expect(resultsPanel.getByRole("heading", { name: "Results", exact: true })).toBeVisible();
    await expect(resultsPanel.getByText("Winner", { exact: true })).toBeVisible();
    await expect(
      resultsPanel.getByRole("link", { name: SMOKE_CONTEST_WINNER_NAME, exact: true })
    ).toHaveAttribute("href", `/person/${SMOKE_PERSON_ID}`);

    const candidaciesRow = page.getByRole("row", {
      name: new RegExp(
        `${SMOKE_CANDIDACY_PERSON_NAME} View candidacy detail for ${SMOKE_CANDIDACY_PERSON_NAME}`
      )
    });
    await expect(
      candidaciesRow.getByRole("link", { name: SMOKE_CANDIDACY_PERSON_NAME, exact: true })
    ).toHaveAttribute("href", `/person/${SMOKE_PERSON_ID}`);
    const financeCardHeading = page.getByRole("heading", {
      name: SMOKE_CANDIDACY_PERSON_NAME,
      level: 4
    });
    await expect(
      financeCardHeading.getByRole("link", { name: SMOKE_CANDIDACY_PERSON_NAME, exact: true })
    ).toHaveAttribute("href", `/candidate/${SMOKE_CANDIDATE_SLUG}`);
    await expect(page.getByRole("link", { name: SMOKE_CONTEST_FINANCE_LINK_NAME })).toHaveCount(0);
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
// stages (2/3/5) wired up against real DB-backed records. Operators can
// override SMOKE_PERSON_ID, SMOKE_CONTEST_ID, SMOKE_OFFICE_ID via env so the
// same constants point at known-populated live records. Without an override,
// the person-detail smoke seeds the existing Congress fixture into the live DB.
// We deliberately avoid asserting fixture-only names/provenance/IDs here so
// live runs do not false-fail on text that only the fixture-backend serves.
test.describe.serial("entity and civic detail smoke (live mode)", () => {
  test.skip(!SMOKE_USE_LIVE_API, "live-mode only — set SMOKE_USE_LIVE_API=1");

  let cleanupLivePersonSmoke: (() => Promise<void>) | null = null;

  test.beforeAll(async () => {
    cleanupLivePersonSmoke = await seedLivePersonSmokeIfNeeded();
  });

  test.afterAll(async () => {
    await cleanupLivePersonSmoke?.();
  });

  test("/person/[id] renders public profile sections against live data", async ({ page }: { page: any }) => {
    const pageLoadErrors = capturePageLoadErrors(page);

    await page.goto(`/person/${LIVE_PERSON_ID}`);

    await expect(page.getByRole("heading", { name: "Key metrics" })).toBeVisible();
    await expect(page.getByRole("heading", { name: SMOKE_PERSON_CAMPAIGN_FINANCE_HEADING }).first()).toBeVisible();
    await expect(page.getByRole("heading", { name: SMOKE_PERSON_FUNDRAISING_DETAIL_HEADING })).toBeVisible();
    await expectFinanceChartHasStableHeight(page, /Donations over time for/);
    await expectFinanceChartHasStableHeight(page, /Donation count by size bucket for/);
    await expectFinanceChartHasStableHeight(page, /Dollars by size bucket for/);
    await expectFinanceChartHasStableHeight(page, /Fundraising geography for/);
    await expect(page.getByText(SMOKE_PERSON_UNITEMIZED_BUCKET_LABEL, { exact: true }).first()).toBeVisible();
    await expect(page.getByText(SMOKE_PERSON_UNITEMIZED_EXCLUSION_NOTE)).toBeVisible();
    await expect(page.getByText(SMOKE_PERSON_SMALL_DOLLAR_HEADLINE, { exact: true })).toBeVisible();
    await expect(page.getByText(SMOKE_PERSON_DISTRICT_SHARE_HEADLINE, { exact: true })).toBeVisible();
    await expect(page.getByText(SMOKE_PERSON_APPROXIMATE_GEOGRAPHY_NOTE, { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Individual contribution totals" })).toBeVisible();
    const contributionTotalsSummary = page.getByTestId("person-contribution-total-summary");
    await expect(contributionTotalsSummary.getByText(SMOKE_PERSON_CYCLE_TOTAL, { exact: true })).toBeVisible();
    await page
      .getByRole("group", { name: "Contribution totals view" })
      .getByRole("button", { name: SMOKE_PERSON_CAREER_TOTAL_LABEL })
      .click();
    await expect(contributionTotalsSummary.getByText(SMOKE_PERSON_CAREER_TOTAL, { exact: true })).toBeVisible();
    await page
      .getByRole("group", { name: "Contribution totals view" })
      .getByRole("button", { name: SMOKE_PERSON_CYCLE_TOTAL_LABEL })
      .click();
    await expect(contributionTotalsSummary.getByText(SMOKE_PERSON_CYCLE_TOTAL, { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: SMOKE_PERSON_TOP_DONORS_HEADING })).toBeVisible();
    const topDonorRows = page.getByTestId("person-top-donors-scroll").getByRole("row");
    await expect(topDonorRows.nth(1)).toContainText(SMOKE_PERSON_TOP_DONOR_ONE_NAME);
    await expect(topDonorRows.nth(2)).toContainText(SMOKE_PERSON_TOP_DONOR_TWO_NAME);
    await expect(page.getByRole("heading", { name: SMOKE_PERSON_TOP_EMPLOYERS_HEADING })).toBeVisible();
    const topEmployerRows = page.getByTestId("person-top-employers-scroll").getByRole("row");
    await expect(topEmployerRows.nth(1)).toContainText(SMOKE_PERSON_TOP_EMPLOYER_ONE_NAME);
    await expect(topEmployerRows.nth(2)).toContainText(SMOKE_PERSON_TOP_EMPLOYER_TWO_NAME);
    await expect(page.getByRole("heading", { name: "Officeholding timeline" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Candidacies" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Graph relationships" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Entity-resolution matches" })).toHaveCount(0);
    await expect(page.getByRole("group", { name: "Entity internals" })).toHaveCount(0);
    await assertBreadcrumbNav(page);
    await pageLoadErrors.assertNoErrors();
  });

  test("/contest/[id] renders Stage 3 completed sections against live data", async ({ page }: { page: any }) => {
    test.skip(
      !SHOULD_RUN_LIVE_CONTEST_SMOKE,
      "live contest smoke requires SMOKE_CONTEST_ID for a known-populated live record"
    );
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
    test.skip(
      !SHOULD_RUN_LIVE_OFFICE_SMOKE,
      "live office smoke requires SMOKE_OFFICE_ID for a known-populated live record"
    );
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
