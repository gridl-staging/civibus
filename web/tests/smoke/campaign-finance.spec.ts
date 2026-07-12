import { expect, test } from "playwright/test";

import {
  SMOKE_CANDIDATE_LIST_CONTEXT,
  SMOKE_CANDIDATE_COMMITTEE_LINK_TEXT,
  SMOKE_CANDIDATES_FIRST_PAGE_LABEL,
  SMOKE_CANDIDATES_SECOND_PAGE_LABEL,
  SMOKE_CANDIDATE_DATA_THROUGH,
  SMOKE_CANDIDATE_DESCRIPTION,
  SMOKE_CANDIDATE_DEVIATION_L10_WARNING,
  SMOKE_CANDIDATE_EMPTY_L10_WARNING,
  SMOKE_CANDIDATE_AL_FRESHNESS_WARNING,
  SMOKE_CANDIDATE_GA_FRESHNESS_WARNING,
  SMOKE_CANDIDATE_ID,
  SMOKE_AL_CANDIDATE_DESCRIPTION,
  SMOKE_AL_CANDIDATE_ID,
  SMOKE_AL_CANDIDATE_TITLE,
  SMOKE_CANDIDATE_NAME,
  SMOKE_CANDIDATE_NET_TOTAL,
  SMOKE_CANDIDATE_OPPOSE_TOTAL,
  SMOKE_CANDIDATE_OUTSIDE_SPENDING_EMPTY,
  SMOKE_CANDIDATE_PERSON_LINK_TEXT,
  SMOKE_CANDIDATE_SLUG,
  SMOKE_CANDIDATE_SUPPORT_TOTAL,
  SMOKE_CANDIDATE_TITLE,
  SMOKE_CANDIDATE_TOTAL_RAISED,
  SMOKE_CANDIDATE_TOTAL_SPENT,
  SMOKE_CANDIDATES_DESCRIPTION,
  SMOKE_CANDIDATES_TITLE,
  SMOKE_COMMITTEE_CONTRIBUTOR_ORG_LINK_TEXT,
  SMOKE_COMMITTEE_CONTRIBUTOR_PERSON_LINK_TEXT,
  SMOKE_COMMITTEE_DESCRIPTION,
  SMOKE_COMMITTEE_EMPTY_STATE,
  SMOKE_COMMITTEE_LIST_CONTEXT,
  SMOKE_COMMITTEE_FILING_ROW_LABEL,
  SMOKE_COMMITTEE_FILING_SUMMARY_EMPTY_STATE,
  SMOKE_COMMITTEE_ID,
  SMOKE_COMMITTEE_IE_COUNT_LABEL,
  SMOKE_COMMITTEE_IE_OPPOSE_TOTAL,
  SMOKE_COMMITTEE_IE_OUTLIER_NOTE,
  SMOKE_COMMITTEE_IE_SOURCE_NAME,
  SMOKE_COMMITTEE_IE_SOURCE_RECORD_KEY,
  SMOKE_COMMITTEE_IE_SOURCE_URL,
  SMOKE_COMMITTEE_IE_SUPPORT_TOTAL,
  SMOKE_COMMITTEE_IE_TARGET_NAME,
  SMOKE_COMMITTEE_NAME,
  SMOKE_COMMITTEE_NET_TOTAL,
  SMOKE_COMMITTEE_ORG_LINK_TEXT,
  SMOKE_COMMITTEE_OUTSIDE_SPENDING_EMPTY,
  SMOKE_COMMITTEE_RECIPIENT_CANDIDATE_LINK_TEXT,
  SMOKE_COMMITTEE_RECIPIENT_COMMITTEE_LINK_TEXT,
  SMOKE_COMMITTEE_SLUG,
  SMOKE_COMMITTEE_TITLE,
  SMOKE_COMMITTEE_TOTAL_RAISED,
  SMOKE_COMMITTEE_TOTAL_SPENT,
  SMOKE_COMMITTEES_DESCRIPTION,
  SMOKE_COMMITTEES_FIRST_PAGE_LABEL,
  SMOKE_COMMITTEES_SECOND_PAGE_LABEL,
  SMOKE_COMMITTEES_TITLE,
  SMOKE_CAMPAIGN_FINANCE_IN_PROVENANCE_SOURCE_NAME,
  SMOKE_CAMPAIGN_FINANCE_AL_PROVENANCE_SOURCE_NAME,
  SMOKE_CAMPAIGN_FINANCE_GA_PROVENANCE_SOURCE_NAME,
  SMOKE_GA_CANDIDATE_DESCRIPTION,
  SMOKE_GA_CANDIDATE_ID,
  SMOKE_GA_CANDIDATE_TITLE,
  SMOKE_EMPTY_CANDIDATE_DESCRIPTION,
  SMOKE_EMPTY_CANDIDATE_ID,
  SMOKE_EMPTY_CANDIDATE_TITLE,
  SMOKE_DEVIANT_CANDIDATE_DESCRIPTION,
  SMOKE_DEVIANT_CANDIDATE_ID,
  SMOKE_DEVIANT_CANDIDATE_TITLE,
  SMOKE_EMPTY_COMMITTEE_DESCRIPTION,
  SMOKE_EMPTY_COMMITTEE_ID,
  SMOKE_EMPTY_COMMITTEE_TITLE,
  SMOKE_IE_COMMITTEE_A_ID,
  SMOKE_IE_COMMITTEE_A_NAME,
  SMOKE_IE_TRANSACTION_DISSEMINATION_DATE,
  SMOKE_ORG_ID,
  SMOKE_PHL_FRESHNESS_WARNING,
  SMOKE_PHL_COMMITTEE_DESCRIPTION,
  SMOKE_PHL_COMMITTEE_ID,
  SMOKE_PHL_COMMITTEE_NAME,
  SMOKE_PHL_COMMITTEE_TITLE,
  SMOKE_PHL_PROVENANCE_SOURCE_NAME,
  SMOKE_PERSON_ID,
  SMOKE_PROVENANCE_LAST_PULLED,
  SMOKE_TRUST_ADVISORY,
  SMOKE_TRUST_EMPTY_MESSAGE,
  SMOKE_TRUST_LAST_PULLED_UNAVAILABLE,
  SMOKE_USE_LIVE_API
} from "./fixtures";
import {
  capturePageLoadErrors,
  assertBreadcrumbJsonLd,
  assertBreadcrumbNav,
  assertSeoHead
} from "./smoke-helpers";

test.describe("campaign finance smoke", () => {
  // Fixture-mode-only: tests below assert synthetic provenance, names, and
  // IDs (e.g., "Acme Corp", "Citizens for Civibus", FEC source name) that
  // only resolve under the fixture-backend. Live coverage of Stage 7
  // committee completed sections lives in the 'live mode' describe block
  // below. See bug live-mode-spec-fixture-mismatch.
  test.skip(SMOKE_USE_LIVE_API, "fixture-only — live coverage in campaign finance live-mode block");

  test("/candidates renders index page links, SEO tags, and pagination controls", async ({ page }: { page: any }) => {
    await page.goto("/candidates");

    await expect(page).toHaveTitle(SMOKE_CANDIDATES_TITLE);
    await expect(page.locator('meta[name="description"]')).toHaveAttribute(
      "content",
      SMOKE_CANDIDATES_DESCRIPTION
    );
    await assertSeoHead(page, {
      title: SMOKE_CANDIDATES_TITLE,
      description: SMOKE_CANDIDATES_DESCRIPTION,
      ogType: "website",
      jsonLdCount: 0
    });
    await expect(page.getByRole("heading", { name: "Candidates" })).toBeVisible();
    await expect(page.getByRole("link", { name: SMOKE_CANDIDATE_NAME })).toHaveAttribute(
      "href",
      `/candidate/${SMOKE_CANDIDATE_SLUG}`
    );
    await expect(page.getByText(SMOKE_CANDIDATE_LIST_CONTEXT)).toBeVisible();
    await expect(page.getByText(SMOKE_CANDIDATES_FIRST_PAGE_LABEL)).toBeVisible();
    await expect(page.getByRole("link", { name: "Next" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Previous" })).toHaveCount(0);

    await page.goto("/candidates?offset=1&limit=1");

    const candidatesSecondPage = new URL(page.url());
    const candidatesCanonical = `${candidatesSecondPage.origin}/candidates`;
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", candidatesCanonical);
    await expect(page.getByText(SMOKE_CANDIDATES_SECOND_PAGE_LABEL)).toBeVisible();
    await expect(page.getByRole("link", { name: "Previous" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Next" })).toHaveCount(0);
  });

  test("/candidates filter form applies query params and clear filters restores the default browse state", async ({
    page
  }: {
    page: any;
  }) => {
    await page.goto("/candidates");

    await page.getByLabel("State").selectOption("GA");
    await page.getByLabel("Office").selectOption("S");
    await page.getByRole("button", { name: "Apply filters" }).click();

    await expect(page).toHaveURL(/\/candidates\?state=GA&office=S&limit=1$/);
    await expect(page.getByText("No candidates found for the selected filters.")).toBeVisible();
    await expect(page.getByRole("link", { name: SMOKE_CANDIDATE_NAME })).toHaveCount(0);

    await page.getByRole("link", { name: "Clear filters" }).click();

    await expect(page).toHaveURL(/\/candidates\?limit=1$/);
    await expect(page.getByRole("link", { name: SMOKE_CANDIDATE_NAME })).toBeVisible();
    await expect(page.getByText(SMOKE_CANDIDATES_FIRST_PAGE_LABEL)).toBeVisible();
  });

  test("/committees renders index page links, SEO tags, and pagination controls", async ({ page }: { page: any }) => {
    await page.goto("/committees");

    await expect(page).toHaveTitle(SMOKE_COMMITTEES_TITLE);
    await expect(page.locator('meta[name="description"]')).toHaveAttribute(
      "content",
      SMOKE_COMMITTEES_DESCRIPTION
    );
    await assertSeoHead(page, {
      title: SMOKE_COMMITTEES_TITLE,
      description: SMOKE_COMMITTEES_DESCRIPTION,
      ogType: "website",
      jsonLdCount: 0
    });
    await expect(page.getByRole("heading", { name: "Committees" })).toBeVisible();
    await expect(page.getByRole("link", { name: SMOKE_COMMITTEE_NAME })).toHaveAttribute(
      "href",
      `/committee/${SMOKE_COMMITTEE_SLUG}`
    );
    await expect(page.getByText(SMOKE_COMMITTEE_LIST_CONTEXT)).toBeVisible();
    await expect(page.getByText(SMOKE_COMMITTEES_FIRST_PAGE_LABEL)).toBeVisible();
    await expect(page.getByRole("link", { name: "Next" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Previous" })).toHaveCount(0);

    await page.goto("/committees?offset=1&limit=1");

    const committeesSecondPage = new URL(page.url());
    const committeesCanonical = `${committeesSecondPage.origin}/committees`;
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", committeesCanonical);
    await expect(page.getByText(SMOKE_COMMITTEES_SECOND_PAGE_LABEL)).toBeVisible();
    await expect(page.getByRole("link", { name: "Previous" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Next" })).toHaveCount(0);
  });

  test("/committees filter form applies query params and clear filters restores the default browse state", async ({
    page
  }: {
    page: any;
  }) => {
    await page.goto("/committees");

    await page.getByLabel("State").selectOption("GA");
    await page.getByLabel("Committee type").selectOption("P");
    await page.getByRole("button", { name: "Apply filters" }).click();

    await expect(page).toHaveURL(/\/committees\?state=GA&committee_type=P&limit=1$/);
    await expect(page.getByText("No committees found for the selected filters.")).toBeVisible();
    await expect(page.getByRole("link", { name: SMOKE_COMMITTEE_NAME })).toHaveCount(0);

    await page.getByRole("link", { name: "Clear filters" }).click();

    await expect(page).toHaveURL(/\/committees\?limit=1$/);
    await expect(page.getByRole("link", { name: SMOKE_COMMITTEE_NAME })).toBeVisible();
    await expect(page.getByText(SMOKE_COMMITTEES_FIRST_PAGE_LABEL)).toBeVisible();
  });

  test("/committee/[id] renders committee detail and committee-only transactions", async ({ page }: { page: any }) => {
    // Stage 7 deep panel coverage (Receipt split, Top donors/vendors, Spend
    // categories, Cash-on-hand trend, Recent transactions) and the
    // page-load-error gate live in the live-mode describe block. The fixture
    // backend does not return the receipts/spend/top-donor/top-vendor
    // aggregates that drive those panels, so the headings never render in
    // fixture mode and page-load errors fire from the missing endpoints.
    await page.goto(`/committee/${SMOKE_COMMITTEE_SLUG}`);

    await expect(page).toHaveTitle(SMOKE_COMMITTEE_TITLE);
    await expect(page).toHaveURL(new RegExp(`/committee/${SMOKE_COMMITTEE_SLUG}$`));
    await expect(page.locator('meta[name="description"]')).toHaveAttribute(
      "content",
      SMOKE_COMMITTEE_DESCRIPTION
    );
    await assertSeoHead(page, {
      title: SMOKE_COMMITTEE_TITLE,
      description: SMOKE_COMMITTEE_DESCRIPTION,
      ogType: "website",
      jsonLdCount: 1
    });
    await expect(page.getByRole("heading", { name: SMOKE_COMMITTEE_NAME })).toBeVisible();
    await expect(page.getByText(SMOKE_CAMPAIGN_FINANCE_IN_PROVENANCE_SOURCE_NAME)).toBeVisible();
    await expect(page.getByText(SMOKE_PROVENANCE_LAST_PULLED)).toHaveCount(1);
    // IN freshness banner retired 2026-04-26 after the IN re-verdict to
    // weekly-or-better; see docs/reference/research/in_freshness_recheck_2026_04_26.md.
    // Negative-assertion left in place as defense-in-depth so a typo'd map
    // re-entry can't silently resurrect the retired copy on the live page.
    await expect(
      page.getByText("Indiana bulk campaign finance data refreshes less often than weekly")
    ).toHaveCount(0);
    await expect(page.getByText(SMOKE_TRUST_ADVISORY)).toBeVisible();
    await expect(page.getByRole("link", { name: SMOKE_COMMITTEE_ORG_LINK_TEXT })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Outside Spending" })).toBeVisible();
    const committeeOutsideSpending = page.getByTestId("committee-outside-spending");
    await expect(
      committeeOutsideSpending.getByRole("definition").filter({ hasText: SMOKE_COMMITTEE_IE_SUPPORT_TOTAL })
    ).toBeVisible();
    await expect(
      committeeOutsideSpending.getByRole("definition").filter({ hasText: SMOKE_COMMITTEE_IE_OPPOSE_TOTAL })
    ).toBeVisible();
    await expect(
      committeeOutsideSpending.getByRole("definition").filter({ hasText: SMOKE_COMMITTEE_IE_COUNT_LABEL })
    ).toBeVisible();
    await expect(committeeOutsideSpending.getByText(SMOKE_COMMITTEE_IE_OUTLIER_NOTE)).toBeVisible();
    const committeeOutsideSpendingTargets = page.getByTestId("committee-outside-spending-targets");
    await expect(
      committeeOutsideSpendingTargets.getByRole("link", { name: SMOKE_COMMITTEE_IE_TARGET_NAME })
    ).toHaveAttribute("href", `/person/${SMOKE_PERSON_ID}`);
    const committeeOutsideSpendingSources = page.getByTestId("committee-outside-spending-sources");
    await expect(
      committeeOutsideSpendingSources.getByRole("link", { name: SMOKE_COMMITTEE_IE_SOURCE_NAME })
    ).toHaveAttribute("href", SMOKE_COMMITTEE_IE_SOURCE_URL);
    await expect(committeeOutsideSpendingSources.getByText(SMOKE_COMMITTEE_IE_SOURCE_RECORD_KEY)).toBeVisible();
    await expect(page.getByRole("heading", { name: "Fundraising summary" })).toBeVisible();
    const committeeFundraisingSummary = page.getByRole("region", { name: "Fundraising summary" });
    await expect(committeeFundraisingSummary.getByText(SMOKE_COMMITTEE_TOTAL_RAISED)).toBeVisible();
    await expect(committeeFundraisingSummary.getByText(SMOKE_COMMITTEE_TOTAL_SPENT)).toBeVisible();
    await expect(committeeFundraisingSummary.getByText(SMOKE_COMMITTEE_NET_TOTAL)).toBeVisible();
    await expect(page.getByRole("heading", { name: "Filing-period breakdown" })).toBeVisible();
    await expect(page.getByRole("cell", { name: SMOKE_COMMITTEE_FILING_ROW_LABEL })).toBeVisible();
    await expect(page.getByTestId("committee-transactions-scroll").getByRole("cell", { name: "125.00" })).toBeVisible();
    await expect(page.getByRole("link", { name: SMOKE_COMMITTEE_RECIPIENT_CANDIDATE_LINK_TEXT })).toHaveAttribute(
      "href",
      `/candidate/${SMOKE_CANDIDATE_ID}`
    );
    await expect(page.getByRole("link", { name: SMOKE_COMMITTEE_RECIPIENT_COMMITTEE_LINK_TEXT })).toHaveAttribute(
      "href",
      `/committee/${SMOKE_COMMITTEE_SLUG}`
    );
    await expect(page.getByRole("link", { name: SMOKE_COMMITTEE_CONTRIBUTOR_PERSON_LINK_TEXT })).toHaveAttribute(
      "href",
      `/person/${SMOKE_PERSON_ID}`
    );
    await expect(page.getByRole("link", { name: SMOKE_COMMITTEE_CONTRIBUTOR_ORG_LINK_TEXT })).toHaveAttribute(
      "href",
      `/org/${SMOKE_ORG_ID}`
    );
    await assertBreadcrumbNav(page);
    await assertBreadcrumbJsonLd(page);
  });

  test("/committee/[id] PHL fixture renders freshness note on committee detail", async ({ page }: { page: any }) => {
    await page.goto(`/committee/${SMOKE_PHL_COMMITTEE_ID}`);

    await expect(page).toHaveTitle(SMOKE_PHL_COMMITTEE_TITLE);
    await expect(page).toHaveURL(new RegExp(`/committee/${SMOKE_PHL_COMMITTEE_ID}$`));
    await expect(page.locator('meta[name="description"]')).toHaveAttribute(
      "content",
      SMOKE_PHL_COMMITTEE_DESCRIPTION
    );
    await assertSeoHead(page, {
      title: SMOKE_PHL_COMMITTEE_TITLE,
      description: SMOKE_PHL_COMMITTEE_DESCRIPTION,
      ogType: "website",
      jsonLdCount: 1
    });
    await expect(page.getByRole("heading", { name: SMOKE_PHL_COMMITTEE_NAME })).toBeVisible();
    await expect(page.getByText(SMOKE_PHL_PROVENANCE_SOURCE_NAME)).toBeVisible();
    await expect(page.getByText(SMOKE_PHL_FRESHNESS_WARNING)).toBeVisible();
    await expect(page.getByText(SMOKE_TRUST_ADVISORY)).toBeVisible();
    const fundraisingSummary = page.getByRole("region", { name: "Fundraising summary" });
    await expect(fundraisingSummary.getByText("$2,100.00")).toBeVisible();
    await expect(page.getByTestId("committee-transactions-scroll").getByRole("cell", { name: "2100.00" })).toBeVisible();
  });

  test("/candidate/[id] renders candidate detail with fundraising summary and committee breakdown", async ({ page }: { page: any }) => {
    await page.goto(`/candidate/${SMOKE_CANDIDATE_ID}`);

    await expect(page).toHaveURL(new RegExp(`/candidate/${SMOKE_CANDIDATE_SLUG}$`));
    await expect(page).toHaveTitle(SMOKE_CANDIDATE_TITLE);
    await expect(page.locator('meta[name="description"]')).toHaveAttribute(
      "content",
      SMOKE_CANDIDATE_DESCRIPTION
    );
    await assertSeoHead(page, {
      title: SMOKE_CANDIDATE_TITLE,
      description: SMOKE_CANDIDATE_DESCRIPTION,
      ogType: "profile",
      jsonLdCount: 1
    });
    await expect(page.getByRole("heading", { name: SMOKE_CANDIDATE_NAME })).toBeVisible();
    await expect(page.getByRole("link", { name: SMOKE_CANDIDATE_PERSON_LINK_TEXT })).toHaveAttribute(
      "href",
      `/person/${SMOKE_PERSON_ID}`
    );
    await expect(page.getByRole("link", { name: SMOKE_CANDIDATE_COMMITTEE_LINK_TEXT })).toHaveAttribute(
      "href",
      `/committee/${SMOKE_COMMITTEE_ID}`
    );
    await expect(page.getByText(SMOKE_CAMPAIGN_FINANCE_IN_PROVENANCE_SOURCE_NAME)).toBeVisible();
    await expect(page.getByText(SMOKE_PROVENANCE_LAST_PULLED)).toHaveCount(1);
    await expect(page.getByText(SMOKE_TRUST_ADVISORY)).toBeVisible();
    await expect(page.getByRole("heading", { name: "Outside Spending" })).toBeVisible();
    await expect(
      page.getByText("Outside spending is independent and not controlled by the candidate committee.")
    ).toBeVisible();
    await expect(page.getByRole("heading", { name: "Support spending" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Oppose spending" })).toBeVisible();
    await expect(page.getByText(SMOKE_CANDIDATE_SUPPORT_TOTAL)).toBeVisible();
    await expect(page.getByText(SMOKE_CANDIDATE_OPPOSE_TOTAL)).toBeVisible();
    await expect(page.getByRole("link", { name: SMOKE_IE_COMMITTEE_A_NAME }).first()).toHaveAttribute(
      "href",
      `/committee/${SMOKE_IE_COMMITTEE_A_ID}`
    );
    await expect(page.getByTestId("outside-spending-transactions-scroll").getByRole("cell", { name: SMOKE_IE_TRANSACTION_DISSEMINATION_DATE })).toBeVisible();

    await expect(page.getByRole("heading", { name: "Fundraising summary" })).toBeVisible();
    const candidateFundraisingSummary = page.getByRole("region", { name: "Fundraising summary" });
    await expect(candidateFundraisingSummary.getByText(SMOKE_CANDIDATE_TOTAL_RAISED)).toBeVisible();
    await expect(candidateFundraisingSummary.getByText(SMOKE_CANDIDATE_TOTAL_SPENT)).toBeVisible();
    await expect(candidateFundraisingSummary.getByText(SMOKE_CANDIDATE_NET_TOTAL)).toBeVisible();

    await expect(page.getByRole("heading", { name: "Committee breakdown" })).toBeVisible();
    await expect(page.getByRole("link", { name: SMOKE_COMMITTEE_NAME })).toHaveAttribute(
      "href",
      `/committee/${SMOKE_COMMITTEE_SLUG}`
    );
    const committeeBreakdownRegion = page.getByRole("region", { name: "Committee breakdown" });
    await expect(committeeBreakdownRegion.getByText(SMOKE_CANDIDATE_DATA_THROUGH)).toBeVisible();
    await assertBreadcrumbNav(page);
    await assertBreadcrumbJsonLd(page);
  });

  test("/committee/[id] empty fixture shows transaction empty state with shared provenance empty copy", async ({
    page
  }: {
    page: any;
  }) => {
    await page.goto(`/committee/${SMOKE_EMPTY_COMMITTEE_ID}`);

    await expect(page).toHaveTitle(SMOKE_EMPTY_COMMITTEE_TITLE);
    await expect(page.locator('meta[name="description"]')).toHaveAttribute(
      "content",
      SMOKE_EMPTY_COMMITTEE_DESCRIPTION
    );
    await assertSeoHead(page, {
      title: SMOKE_EMPTY_COMMITTEE_TITLE,
      description: SMOKE_EMPTY_COMMITTEE_DESCRIPTION,
      ogType: "website",
      jsonLdCount: 1
    });
    const fundraisingSummary = page.getByRole("region", { name: "Fundraising summary" });
    await expect(fundraisingSummary).toBeVisible();
    await expect(fundraisingSummary.getByText("$0.00")).toHaveCount(3);
    await expect(page.getByRole("heading", { name: "Filing-period breakdown" })).toBeVisible();
    await expect(page.getByText(SMOKE_COMMITTEE_FILING_SUMMARY_EMPTY_STATE)).toBeVisible();
    await expect(page.getByText(SMOKE_COMMITTEE_OUTSIDE_SPENDING_EMPTY)).toBeVisible();
    await expect(page.getByText(SMOKE_COMMITTEE_EMPTY_STATE)).toBeVisible();
    await expect(page.getByText(SMOKE_TRUST_LAST_PULLED_UNAVAILABLE)).toBeVisible();
    await expect(page.getByText(SMOKE_TRUST_EMPTY_MESSAGE)).toBeVisible();
    await assertBreadcrumbNav(page);
    await assertBreadcrumbJsonLd(page);
  });

  test("/candidate/[id] empty fixture shows provenance empty state, empty fundraising, and unresolved link placeholders", async ({
    page
  }: {
    page: any;
  }) => {
    await page.goto(`/candidate/${SMOKE_EMPTY_CANDIDATE_ID}`);

    await expect(page).toHaveTitle(SMOKE_EMPTY_CANDIDATE_TITLE);
    await expect(page.locator('meta[name="description"]')).toHaveAttribute(
      "content",
      SMOKE_EMPTY_CANDIDATE_DESCRIPTION
    );
    await assertSeoHead(page, {
      title: SMOKE_EMPTY_CANDIDATE_TITLE,
      description: SMOKE_EMPTY_CANDIDATE_DESCRIPTION,
      ogType: "profile",
      jsonLdCount: 1
    });
    await expect(page.getByText("Canonical person")).toBeVisible();
    await expect(page.getByText("Principal committee")).toBeVisible();
    await expect(page.getByRole("link", { name: /Person record/ })).toHaveCount(0);
    await expect(page.getByRole("link", { name: /Committee record/ })).toHaveCount(0);
    await expect(page.getByText(SMOKE_TRUST_LAST_PULLED_UNAVAILABLE)).toBeVisible();
    await expect(page.getByText(SMOKE_TRUST_EMPTY_MESSAGE)).toBeVisible();
    await expect(page.getByText(SMOKE_CANDIDATE_OUTSIDE_SPENDING_EMPTY)).toBeVisible();
    const coverageWarning = page.getByRole("note", { name: "Data coverage warning" });
    await expect(coverageWarning).toBeVisible();
    await expect(coverageWarning).toHaveClass(/caveat-banner/);
    await expect(coverageWarning).toContainText(SMOKE_CANDIDATE_EMPTY_L10_WARNING);
    await expect(coverageWarning.getByRole("link", { name: "See methodology." })).toHaveAttribute(
      "href",
      "/methodology"
    );

    await expect(page.getByRole("heading", { name: "Fundraising summary" })).toBeVisible();
    const emptyCandidateFundraisingSummary = page.getByRole("region", { name: "Fundraising summary" });
    await expect(emptyCandidateFundraisingSummary.getByText("$0.00")).toHaveCount(3);
    await expect(page.getByRole("heading", { name: "Committee breakdown" })).toHaveCount(0);
    await assertBreadcrumbNav(page);
    await assertBreadcrumbJsonLd(page);
  });

  test("/candidate/[id] Alabama fixture shows a jurisdiction freshness warning", async ({ page }: { page: any }) => {
    await page.goto(`/candidate/${SMOKE_AL_CANDIDATE_ID}`);

    await expect(page).toHaveTitle(SMOKE_AL_CANDIDATE_TITLE);
    await expect(page.locator('meta[name="description"]')).toHaveAttribute(
      "content",
      SMOKE_AL_CANDIDATE_DESCRIPTION
    );
    await expect(page.getByText(SMOKE_CAMPAIGN_FINANCE_AL_PROVENANCE_SOURCE_NAME)).toBeVisible();
    await expect(page.getByText(SMOKE_CANDIDATE_AL_FRESHNESS_WARNING)).toBeVisible();
  });

  test("/candidate/[id] Georgia fixture shows a jurisdiction freshness warning", async ({ page }: { page: any }) => {
    await page.goto(`/candidate/${SMOKE_GA_CANDIDATE_ID}`);

    await expect(page).toHaveTitle(SMOKE_GA_CANDIDATE_TITLE);
    await expect(page.locator('meta[name="description"]')).toHaveAttribute(
      "content",
      SMOKE_GA_CANDIDATE_DESCRIPTION
    );
    await expect(page.getByText(SMOKE_CAMPAIGN_FINANCE_GA_PROVENANCE_SOURCE_NAME)).toBeVisible();
    await expect(page.getByText(SMOKE_CANDIDATE_GA_FRESHNESS_WARNING)).toBeVisible();
  });

  test("/candidate/[id] deviant fixture shows an L10 anchor-deviation warning", async ({ page }: { page: any }) => {
    await page.goto(`/candidate/${SMOKE_DEVIANT_CANDIDATE_ID}`);

    await expect(page).toHaveTitle(SMOKE_DEVIANT_CANDIDATE_TITLE);
    await expect(page.locator('meta[name="description"]')).toHaveAttribute(
      "content",
      SMOKE_DEVIANT_CANDIDATE_DESCRIPTION
    );
    const coverageWarning = page.getByRole("note", { name: "Data coverage warning" });
    await expect(coverageWarning).toBeVisible();
    await expect(coverageWarning).toHaveClass(/caveat-banner/);
    await expect(coverageWarning).toContainText(SMOKE_CANDIDATE_DEVIATION_L10_WARNING);
    await expect(coverageWarning.getByRole("link", { name: "See methodology." })).toHaveAttribute(
      "href",
      "/methodology"
    );
  });
});

test.describe("sitemap.xml fixture detail URLs", () => {
  // Detail URL assertions remain fixture-only because they depend on the
  // synthetic fixture seed and fixture-only IDs/slugs.
  test.skip(SMOKE_USE_LIVE_API, "fixture-only — sitemap detail URLs reflect fixture seed");

  test("contains fixture-specific candidate and committee detail URLs", async ({ page }: { page: any }) => {
    const response = (await page.goto("/sitemap.xml"))!;
    const xml = await response.text();

    // Slug-based detail URL from fixture (pat-candidate has slug_is_unique: true).
    expect(xml).toContain(`/candidate/${SMOKE_CANDIDATE_SLUG}</loc>`);

    // UUID-based detail URL for slug_is_unique: false fixture.
    expect(xml).toContain(`/candidate/${SMOKE_EMPTY_CANDIDATE_ID}</loc>`);

    // Committee slug-based detail URL.
    expect(xml).toContain(`/committee/${SMOKE_COMMITTEE_SLUG}</loc>`);

    // Committee UUID-based detail URL (slug_is_unique: false).
    expect(xml).toContain(`/committee/${SMOKE_EMPTY_COMMITTEE_ID}</loc>`);
  });
});

// Stage 7 live-mode coverage: assert structural section headings the upstream
// stage 4 wired up against real DB-backed committee records. Operators
// override SMOKE_COMMITTEE_SLUG via env so the same constant points at a
// known-populated live committee. Fixture-specific text (donor names,
// provenance source name, IN freshness banner) is intentionally not asserted
// here so live runs don't false-fail on fixture-only content.
test.describe("campaign finance smoke (live mode)", () => {
  test.skip(!SMOKE_USE_LIVE_API, "live-mode only — set SMOKE_USE_LIVE_API=1");

  test("/committee/[slug] renders Stage 4 completed sections against live data", async ({ page }: { page: any }) => {
    const pageLoadErrors = capturePageLoadErrors(page);
    await page.goto(`/committee/${SMOKE_COMMITTEE_SLUG}`);

    await expect(page.getByRole("heading", { name: "Fundraising summary" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Receipt split" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Top donors" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Top vendors" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Spend categories" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Cash-on-hand trend" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Filing-period breakdown" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Recent transactions" })).toBeVisible();
    await expect(page.getByText(SMOKE_TRUST_ADVISORY)).toBeVisible();
    const fundraisingSummary = page.getByRole("region", { name: "Fundraising summary" });
    const renderedAmounts: string[] = await fundraisingSummary.getByText(/\$[\d,]+\.\d{2}/).allTextContents();
    const hasPositiveAmount = renderedAmounts.some((amount: string) => {
      const normalizedAmount = amount.replaceAll(",", "").replace("$", "");
      const parsedAmount = Number.parseFloat(normalizedAmount);
      return Number.isFinite(parsedAmount) && parsedAmount > 0;
    });
    expect(hasPositiveAmount).toBe(true);
    await assertBreadcrumbNav(page);
    await assertBreadcrumbJsonLd(page);
    await pageLoadErrors.assertNoErrors();
  });
});
