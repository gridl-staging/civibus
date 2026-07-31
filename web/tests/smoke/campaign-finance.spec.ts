import { expect, test } from "playwright/test";

import {
  SMOKE_CANDIDATE_LIST_CONTEXT,
  SMOKE_CANDIDATE_CASH_ON_HAND,
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
  SMOKE_BACKEND_FAILURE_CANDIDATE_ID,
  SMOKE_BACKEND_FAILURE_CANDIDATE_TITLE,
  SMOKE_AL_CANDIDATE_DESCRIPTION,
  SMOKE_AL_CANDIDATE_ID,
  SMOKE_AL_CANDIDATE_TITLE,
  SMOKE_CANDIDATE_NAME,
  SMOKE_CANDIDATE_OPPOSE_TOTAL,
  SMOKE_CANDIDATE_PERSON_LINK_TEXT,
  SMOKE_CANDIDATE_SLUG,
  SMOKE_OUT_OF_CYCLE_CANDIDATE_ID,
  SMOKE_OUT_OF_CYCLE_CANDIDATE_NAME,
  SMOKE_OUT_OF_CYCLE_CANDIDATE_SLUG,
  SMOKE_OUT_OF_CYCLE_CANDIDATE_TITLE,
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
  SMOKE_CONGRESS_NO_MONEY_PERSON_ID,
  SMOKE_CONGRESS_SECOND_PERSON_ID,
  SMOKE_CAMPAIGN_FINANCE_IN_PROVENANCE_SOURCE_NAME,
  SMOKE_CAMPAIGN_FINANCE_AL_PROVENANCE_SOURCE_NAME,
  SMOKE_CAMPAIGN_FINANCE_GA_PROVENANCE_SOURCE_NAME,
  SMOKE_CALENDAR_ROUTE_PATH,
  SMOKE_GA_CANDIDATE_DESCRIPTION,
  SMOKE_GA_CANDIDATE_ID,
  SMOKE_GA_CANDIDATE_TITLE,
  SMOKE_COVERAGE_ROUTE_PATH,
  SMOKE_DATA_SOURCES_ROUTE_PATH,
  SMOKE_EMPTY_CANDIDATE_DESCRIPTION,
  SMOKE_EMPTY_CANDIDATE_ID,
  SMOKE_EMPTY_CANDIDATE_SLUG,
  SMOKE_EMPTY_CANDIDATE_TITLE,
  SMOKE_LOADED_ZERO_CANDIDATE_ID,
  SMOKE_LOADED_ZERO_CANDIDATE_SLUG,
  SMOKE_LOADED_ZERO_CANDIDATE_TITLE,
  SMOKE_DEVIANT_CANDIDATE_DESCRIPTION,
  SMOKE_DEVIANT_CANDIDATE_ID,
  SMOKE_DEVIANT_CANDIDATE_TITLE,
  SMOKE_EMPTY_COMMITTEE_DESCRIPTION,
  SMOKE_EMPTY_COMMITTEE_ID,
  SMOKE_EMPTY_COMMITTEE_TITLE,
  SMOKE_FILING_ID,
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
  SMOKE_ELECTION_ROUTE_PATH,
  SMOKE_USE_LIVE_API,
  SMOKE_COMMITTEE_REQUEST_COUNTER_KEYS,
  resetSmokeCommitteeRequestCounts,
  fetchSmokeCommitteeRequestCounts,
  SMOKE_FILINGS_PAGED_COMMITTEE_ID,
  SMOKE_FILINGS_HIGH_TOTAL_COMMITTEE_ID,
  SMOKE_FILINGS_PAGE_1_FIRST_ROW_LABEL,
  SMOKE_FILINGS_PAGE_1_LAST_ROW_LABEL,
  SMOKE_FILINGS_PAGE_2_FIRST_ROW_LABEL,
  SMOKE_FILINGS_PAGE_2_LAST_ROW_LABEL,
  SMOKE_FILINGS_PAGE_1_LABEL,
  SMOKE_FILINGS_PAGE_2_LABEL,
  SMOKE_FILINGS_HIGH_TOTAL_LABEL
} from "./fixtures";
import {
  capturePageLoadErrors,
  assertBreadcrumbJsonLd,
  assertBreadcrumbNav,
  assertRobotsHead,
  assertSeoHead,
  expectNoBackendFailureStates
} from "./smoke-helpers";

function extractSitemapLocs(xml: string): string[] {
  return [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((match) => match[1]!);
}

function pathSet(paths: Iterable<string>): Set<string> {
  return new Set(paths);
}

async function fetchSitemapShardUnion(page: any): Promise<{ xmlByPath: Map<string, string>; locs: string[] }> {
  const indexResponse = await page.request.get("/sitemap.xml");
  expect(indexResponse.status()).toBe(200);
  expect(indexResponse.headers()["content-type"]).toContain("xml");
  expect(indexResponse.headers()["cache-control"]).toBe("public, max-age=900");
  const indexXml = await indexResponse.text();
  expect(indexXml).toContain('<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">');

  const origin = new URL(indexResponse.url()).origin;
  const shardPaths = extractSitemapLocs(indexXml).map((loc) => {
    const url = new URL(loc);
    expect(url.origin).toBe(origin);
    return url.pathname;
  });
  const xmlByPath = new Map<string, string>();
  const locs: string[] = [];
  for (const shardPath of shardPaths) {
    const response = await page.request.get(shardPath);
    expect(response.status()).toBe(200);
    expect(response.headers()["content-type"]).toContain("xml");
    expect(response.headers()["cache-control"]).toBe("public, max-age=900");
    const xml = await response.text();
    expect(xml).toContain('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">');
    xmlByPath.set(shardPath, xml);
    locs.push(...extractSitemapLocs(xml).map((loc) => new URL(loc).pathname));
  }
  expect(locs).toHaveLength(new Set(locs).size);
  return { xmlByPath, locs };
}

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
    await expect(page.getByRole("link", { name: "Next" })).toBeVisible();
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
    await assertRobotsHead(page, null);
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

  test("/candidate/[id] out-of-cycle official-total fixture remains indexable", async ({
    page
  }: {
    page: any;
  }) => {
    const response = await page.goto(`/candidate/${SMOKE_OUT_OF_CYCLE_CANDIDATE_ID}`);

    expect(response?.status()).toBe(200);
    await expect(page).toHaveURL(new RegExp(`/candidate/${SMOKE_OUT_OF_CYCLE_CANDIDATE_SLUG}$`));
    await expect(page).toHaveTitle(SMOKE_OUT_OF_CYCLE_CANDIDATE_TITLE);
    await assertRobotsHead(page, null);
    await expect(page.getByRole("heading", { name: SMOKE_OUT_OF_CYCLE_CANDIDATE_NAME })).toBeVisible();
    await expect(page.getByText("Earlier-cycle official total")).toBeVisible();
    await expect(page.getByText("$1,234.56")).toBeVisible();
    await expect(
      page.getByText(
        "Official FEC total from 2023-01-01 to 2024-12-31; not part of the 2026 selected-cycle totals."
      )
    ).toBeVisible();
  });

  test("/committee/[id] filing table paginates client-side without refetching the detail bundle", async ({
    page,
    request
  }: {
    page: any;
    request: any;
  }) => {
    const committeeId = SMOKE_FILINGS_PAGED_COMMITTEE_ID;
    await resetSmokeCommitteeRequestCounts(request);

    // Navigate by id and carry an unrelated query param so the Stage 3 first-page
    // href policy (reset filings_offset while preserving other params) is exercised.
    await page.goto(`/committee/${committeeId}?ref=smoke`);
    await expect(page).toHaveURL(new RegExp(`/committee/${committeeId}\\?ref=smoke$`));

    // Checklist-mandated: scope filing row counts strictly to the breakdown table's
    // tbody, never broad document rows.
    // eslint-disable-next-line playwright/no-raw-locators
    const filingRows = page.getByTestId("filing-breakdown-scroll").locator("tbody tr");
    const paginationLabel = page.getByTestId("filing-breakdown-pagination-label");

    // Page 1: exactly 25 rows, newest filing first and 25th newest last, with the
    // recent-window-vs-all-time label, a Next control, no Previous control, and the
    // chronological cash trend still present alongside the paginated table.
    await expect(filingRows).toHaveCount(25);
    await expect(filingRows.first()).toContainText(SMOKE_FILINGS_PAGE_1_FIRST_ROW_LABEL);
    await expect(filingRows.nth(24)).toContainText(SMOKE_FILINGS_PAGE_1_LAST_ROW_LABEL);
    await expect(paginationLabel).toHaveText(SMOKE_FILINGS_PAGE_1_LABEL);
    await expect(page.getByTestId("filing-breakdown-next")).toBeVisible();
    await expect(page.getByTestId("filing-breakdown-prev")).toHaveCount(0);
    await expect(page.getByTestId("committee-cash-on-hand-trend")).toBeVisible();

    // Snapshot the per-committee subresource counts after the initial server render.
    // Every named counter must be present AND positive: a zero would mean that
    // detail-bundle fetch never ran on the initial render, so the unchanged-after-
    // navigation comparison below would prove nothing. Requiring a positive baseline
    // makes the no-refetch proof fail closed against a dropped or client-moved fetch.
    const initialCounts = await fetchSmokeCommitteeRequestCounts(request, committeeId);
    for (const counterKey of SMOKE_COMMITTEE_REQUEST_COUNTER_KEYS) {
      expect(initialCounts).toHaveProperty(counterKey);
      expect(initialCounts[counterKey]).toBeGreaterThan(0);
    }

    // Click Next as a user would: URL gains filings_offset=25 (unrelated param kept),
    // the table shows the short final page, and the controls flip to Previous-only.
    await page.getByTestId("filing-breakdown-next").click();
    await expect(page).toHaveURL(new RegExp(`/committee/${committeeId}\\?ref=smoke&filings_offset=25$`));
    await expect(filingRows).toHaveCount(5);
    await expect(filingRows.first()).toContainText(SMOKE_FILINGS_PAGE_2_FIRST_ROW_LABEL);
    await expect(filingRows.nth(4)).toContainText(SMOKE_FILINGS_PAGE_2_LAST_ROW_LABEL);
    await expect(paginationLabel).toHaveText(SMOKE_FILINGS_PAGE_2_LABEL);
    await expect(page.getByTestId("filing-breakdown-prev")).toBeVisible();
    await expect(page.getByTestId("filing-breakdown-next")).toHaveCount(0);

    // Click Previous: the first-page href resets filings_offset to 0 while preserving
    // the unrelated param, restoring page-1 content and controls.
    await page.getByTestId("filing-breakdown-prev").click();
    await expect(page).toHaveURL(new RegExp(`/committee/${committeeId}\\?ref=smoke&filings_offset=0$`));
    await expect(filingRows).toHaveCount(25);
    await expect(filingRows.first()).toContainText(SMOKE_FILINGS_PAGE_1_FIRST_ROW_LABEL);
    await expect(filingRows.nth(24)).toContainText(SMOKE_FILINGS_PAGE_1_LAST_ROW_LABEL);
    await expect(paginationLabel).toHaveText(SMOKE_FILINGS_PAGE_1_LABEL);
    await expect(page.getByTestId("filing-breakdown-next")).toBeVisible();
    await expect(page.getByTestId("filing-breakdown-prev")).toHaveCount(0);

    // The automated proof that +page.server.ts did not rerun: URL-only filing
    // navigation left every committee detail bundle subresource count unchanged.
    const finalCounts = await fetchSmokeCommitteeRequestCounts(request, committeeId);
    expect(finalCounts).toEqual(initialCounts);
  });

  test("/committee/[id] filing table shows the recent-window-vs-all-time label for a high-total committee", async ({
    page
  }: {
    page: any;
  }) => {
    await page.goto(`/committee/${SMOKE_FILINGS_HIGH_TOTAL_COMMITTEE_ID}`);
    await expect(page).toHaveURL(new RegExp(`/committee/${SMOKE_FILINGS_HIGH_TOTAL_COMMITTEE_ID}$`));

    // Checklist-mandated: scope filing row counts strictly to the breakdown table's
    // tbody, never broad document rows.
    // eslint-disable-next-line playwright/no-raw-locators
    const filingRows = page.getByTestId("filing-breakdown-scroll").locator("tbody tr");
    await expect(filingRows).toHaveCount(25);
    await expect(page.getByTestId("filing-breakdown-pagination-label")).toHaveText(
      SMOKE_FILINGS_HIGH_TOTAL_LABEL
    );
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
    const pageErrors = capturePageLoadErrors(page);
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
    await assertRobotsHead(page, null);
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

    const keyFinancials = page.getByTestId("key-metrics");
    await expect(keyFinancials).toBeVisible();
    await expect(keyFinancials.getByText(SMOKE_CANDIDATE_TOTAL_RAISED)).toBeVisible();
    await expect(keyFinancials.getByText(SMOKE_CANDIDATE_TOTAL_SPENT)).toBeVisible();
    await expect(keyFinancials.getByText(SMOKE_CANDIDATE_CASH_ON_HAND)).toBeVisible();
    await expect(keyFinancials.getByText(SMOKE_CANDIDATE_SUPPORT_TOTAL)).toHaveCount(0);
    await expect(keyFinancials.getByText(SMOKE_CANDIDATE_OPPOSE_TOTAL)).toHaveCount(0);

    const outsideSpending = page.getByTestId("candidate-outside-spending");
    await expect(outsideSpending).toBeVisible();
    await expect(
      outsideSpending.getByText("Outside spending is independent and not controlled by the candidate committee.")
    ).toBeVisible();
    await expect(outsideSpending.getByRole("heading", { name: "Support spending" })).toBeVisible();
    await expect(outsideSpending.getByRole("heading", { name: "Oppose spending" })).toBeVisible();
    await expect(outsideSpending.getByText(SMOKE_CANDIDATE_SUPPORT_TOTAL)).toBeVisible();
    await expect(outsideSpending.getByText(SMOKE_CANDIDATE_OPPOSE_TOTAL)).toBeVisible();
    await expect(outsideSpending.getByRole("link", { name: SMOKE_IE_COMMITTEE_A_NAME }).first()).toHaveAttribute(
      "href",
      `/committee/${SMOKE_IE_COMMITTEE_A_ID}`
    );
    const transactionTable = outsideSpending.getByTestId("outside-spending-transactions-scroll");
    await expect(transactionTable.getByRole("cell", { name: SMOKE_IE_TRANSACTION_DISSEMINATION_DATE })).toBeVisible();
    await expect(transactionTable.getByRole("link", { name: "Source filing" })).toHaveAttribute(
      "href",
      `/v1/filings/${SMOKE_FILING_ID}`
    );

    const candidateFundraisingSummary = page.getByTestId("candidate-fundraising-summary");
    await expect(candidateFundraisingSummary).toBeVisible();
    await expect(candidateFundraisingSummary.getByText(SMOKE_CANDIDATE_TOTAL_RAISED)).toBeVisible();
    await expect(candidateFundraisingSummary.getByText(SMOKE_CANDIDATE_TOTAL_SPENT)).toBeVisible();
    await expect(candidateFundraisingSummary.getByText(SMOKE_CANDIDATE_CASH_ON_HAND)).toBeVisible();
    await expect(candidateFundraisingSummary.getByText(SMOKE_CANDIDATE_SUPPORT_TOTAL)).toHaveCount(0);
    await expect(candidateFundraisingSummary.getByText(SMOKE_CANDIDATE_OPPOSE_TOTAL)).toHaveCount(0);

    const committeeBreakdownRegion = page.getByTestId("candidate-committee-breakdown");
    await expect(committeeBreakdownRegion).toBeVisible();
    await expect(committeeBreakdownRegion.getByRole("link", { name: SMOKE_COMMITTEE_NAME })).toHaveAttribute(
      "href",
      `/committee/${SMOKE_COMMITTEE_SLUG}`
    );
    await expect(committeeBreakdownRegion.getByText(SMOKE_CANDIDATE_DATA_THROUGH)).toBeVisible();
    await expectNoBackendFailureStates(page);
    await pageErrors.assertNoErrors();
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

  test("/candidate/[id] not-loaded fixture shows methodology states without zero fallbacks", async ({
    page
  }: {
    page: any;
  }) => {
    const response = await page.goto(`/candidate/${SMOKE_EMPTY_CANDIDATE_ID}`);

    expect(response?.status()).toBe(200);
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
    await assertRobotsHead(page, "noindex");
    await expect(page.getByText("Canonical person")).toBeVisible();
    await expect(page.getByText("Principal committee")).toBeVisible();
    await expect(page.getByRole("link", { name: /Person record/ })).toHaveCount(0);
    await expect(page.getByRole("link", { name: /Committee record/ })).toHaveCount(0);
    await expect(page.getByText(SMOKE_TRUST_LAST_PULLED_UNAVAILABLE)).toBeVisible();
    await expect(page.getByText(SMOKE_TRUST_EMPTY_MESSAGE)).toBeVisible();
    const coverageWarning = page.getByRole("note", { name: "Data coverage warning" });
    await expect(coverageWarning).toBeVisible();
    await expect(coverageWarning).toHaveClass(/caveat-banner/);
    await expect(coverageWarning).toContainText(SMOKE_CANDIDATE_EMPTY_L10_WARNING);
    await expect(coverageWarning.getByRole("link", { name: "See methodology." })).toHaveAttribute(
      "href",
      "/methodology"
    );

    const keyFinancials = page.getByTestId("key-metrics");
    await expect(
      keyFinancials.getByText("Campaign-finance totals are not yet available for this candidate and cycle.")
    ).toBeVisible();
    await expect(keyFinancials.getByRole("link", { name: "Learn how Civibus reports coverage." })).toHaveAttribute(
      "href",
      "/methodology"
    );

    const outsideSpending = page.getByTestId("candidate-outside-spending");
    await expect(
      outsideSpending.getByText(
        "FEC Schedule E independent-expenditure coverage is not yet available for this candidate and cycle."
      )
    ).toBeVisible();
    await expect(
      outsideSpending.getByRole("link", { name: "Learn how Civibus reports coverage." })
    ).toHaveAttribute("href", "/methodology");

    const fundraisingSummary = page.getByTestId("candidate-fundraising-summary");
    await expect(
      fundraisingSummary.getByText("Fundraising data is not yet available for this candidate and cycle.")
    ).toBeVisible();
    await expect(
      fundraisingSummary.getByRole("link", { name: "Learn how Civibus reports coverage." })
    ).toHaveAttribute("href", "/methodology");

    const committeeBreakdown = page.getByTestId("candidate-committee-breakdown");
    await expect(
      committeeBreakdown.getByText("Committee breakdown is not yet available for this candidate and cycle.")
    ).toBeVisible();
    await expect(
      committeeBreakdown.getByRole("link", { name: "Learn how Civibus reports coverage." })
    ).toHaveAttribute("href", "/methodology");

    await expect(page.getByText("$0.00")).toHaveCount(0);
    await expect(page.getByTestId("top-spenders-scroll")).toHaveCount(0);
    await expect(page.getByTestId("outside-spending-transactions-scroll")).toHaveCount(0);
    await expectNoBackendFailureStates(page);
    await assertBreadcrumbNav(page);
    await assertBreadcrumbJsonLd(page);
  });

  test("/candidate/[id] loaded-zero fixture renders explicit zero activity without detail tables", async ({
    page
  }: {
    page: any;
  }) => {
    const response = await page.goto(`/candidate/${SMOKE_LOADED_ZERO_CANDIDATE_ID}`);

    expect(response?.status()).toBe(200);
    await expect(page).toHaveTitle(SMOKE_LOADED_ZERO_CANDIDATE_TITLE);
    await assertRobotsHead(page, "noindex");

    const keyFinancials = page.getByTestId("key-metrics");
    await expect(
      keyFinancials.getByText("No fundraising activity is reported in loaded filings for this candidate and cycle.")
    ).toBeVisible();
    await expect(keyFinancials.getByText("$0.00")).toHaveCount(2);
    await expect(keyFinancials.getByText("0", { exact: true })).toBeVisible();

    const outsideSpending = page.getByTestId("candidate-outside-spending");
    await expect(
      outsideSpending.getByText(
        "No FEC Schedule E independent expenditures are reported in loaded filings for this candidate and cycle."
      )
    ).toBeVisible();
    await expect(outsideSpending.getByText("$0.00")).toHaveCount(2);
    await expect(outsideSpending.getByText("0 expenditures")).toHaveCount(2);

    const fundraisingSummary = page.getByTestId("candidate-fundraising-summary");
    await expect(
      fundraisingSummary.getByText("No fundraising activity is reported in loaded filings for this candidate and cycle.")
    ).toBeVisible();
    await expect(fundraisingSummary.getByText("$0.00")).toHaveCount(2);

    const committeeBreakdown = page.getByTestId("candidate-committee-breakdown");
    await expect(
      committeeBreakdown.getByText(
        "No authorized committee activity is reported in loaded filings for this candidate and cycle."
      )
    ).toBeVisible();
    await expect(committeeBreakdown.getByRole("heading", { level: 4 })).toHaveCount(0);
    await expect(page.getByTestId("top-spenders-scroll")).toHaveCount(0);
    await expect(page.getByTestId("outside-spending-transactions-scroll")).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Source filing" })).toHaveCount(0);
    await expect(page.getByText(SMOKE_CANDIDATE_TOTAL_RAISED)).toHaveCount(0);
    await expect(page.getByText(SMOKE_CANDIDATE_TOTAL_SPENT)).toHaveCount(0);
    await expect(page.getByText(SMOKE_CANDIDATE_CASH_ON_HAND)).toHaveCount(0);
    await expectNoBackendFailureStates(page);
  });

  test("/candidate/[id] backend-failure fixture renders temporary unavailability without zero fallbacks", async ({
    page
  }: {
    page: any;
  }) => {
    await page.goto(`/candidate/${SMOKE_BACKEND_FAILURE_CANDIDATE_ID}`);

    await expect(page).toHaveTitle(SMOKE_BACKEND_FAILURE_CANDIDATE_TITLE);
    await expect(page.getByTestId("key-metrics")).toContainText(
      "Candidate financial totals are temporarily unavailable."
    );
    await expect(page.getByTestId("candidate-outside-spending")).toContainText(
      "Outside-spending data is temporarily unavailable."
    );
    await expect(page.getByTestId("candidate-fundraising-summary")).toContainText(
      "Candidate fundraising summary is temporarily unavailable."
    );
    await expect(page.getByTestId("candidate-committee-breakdown")).toContainText(
      "Committee breakdown is temporarily unavailable."
    );
    await expect(page.getByText("$0.00")).toHaveCount(0);
    await expect(page.getByTestId("top-spenders-scroll")).toHaveCount(0);
    await expect(page.getByTestId("outside-spending-transactions-scroll")).toHaveCount(0);
    await expect(
      page.getByTestId("candidate-committee-breakdown").getByRole("heading", { level: 4 })
    ).toHaveCount(0);
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

  test("applies candidate money eligibility while preserving thin-page reachability", async ({
    page
  }: {
    page: any;
  }) => {
    const { xmlByPath, locs } = await fetchSitemapShardUnion(page);
    const candidateXml = xmlByPath.get("/sitemap-candidate-0.xml") ?? "";
    const committeeXml = xmlByPath.get("/sitemap-committee-0.xml") ?? "";
    const personXml = xmlByPath.get("/sitemap-person-0.xml") ?? "";
    const staticXml = xmlByPath.get("/sitemap-static.xml") ?? "";
    const expectedPaths = [
      "/",
      "/congress",
      "/candidates",
      "/committees",
      SMOKE_COVERAGE_ROUTE_PATH,
      SMOKE_CALENDAR_ROUTE_PATH,
      SMOKE_DATA_SOURCES_ROUTE_PATH,
      SMOKE_ELECTION_ROUTE_PATH,
      `/candidate/${SMOKE_CANDIDATE_SLUG}`,
      `/candidate/${SMOKE_OUT_OF_CYCLE_CANDIDATE_SLUG}`,
      `/committee/${SMOKE_COMMITTEE_SLUG}`,
      `/committee/${SMOKE_EMPTY_COMMITTEE_ID}`,
      `/person/${SMOKE_PERSON_ID}`,
      `/person/${SMOKE_CONGRESS_SECOND_PERSON_ID}`,
      `/person/${SMOKE_CONGRESS_NO_MONEY_PERSON_ID}`
    ];
    expect(pathSet(locs)).toEqual(pathSet(expectedPaths));
    expect(locs).toHaveLength(expectedPaths.length);

    // Slug-based detail URL from fixture (pat-candidate has slug_is_unique: true).
    expect(locs).toContain(`/candidate/${SMOKE_CANDIDATE_SLUG}`);
    expect(locs).toContain(`/candidate/${SMOKE_OUT_OF_CYCLE_CANDIDATE_SLUG}`);

    expect(locs).not.toContain(`/candidate/${SMOKE_EMPTY_CANDIDATE_SLUG}`);
    expect(locs).not.toContain(`/candidate/${SMOKE_LOADED_ZERO_CANDIDATE_SLUG}`);
    expect(locs).not.toContain(`/candidate/${SMOKE_EMPTY_CANDIDATE_ID}`);
    expect(locs).not.toContain(`/candidate/${SMOKE_LOADED_ZERO_CANDIDATE_ID}`);
    expect(candidateXml).not.toMatch(/<loc>[^<]+\/candidate\/[0-9a-f-]{36}<\/loc>/i);

    const [notLoadedResponse, loadedZeroResponse] = await Promise.all([
      page.request.get(`/candidate/${SMOKE_EMPTY_CANDIDATE_SLUG}`),
      page.request.get(`/candidate/${SMOKE_LOADED_ZERO_CANDIDATE_SLUG}`)
    ]);
    expect(notLoadedResponse.status()).toBe(200);
    expect(loadedZeroResponse.status()).toBe(200);

    // Committee slug-based detail URL.
    expect(locs).toContain(`/committee/${SMOKE_COMMITTEE_SLUG}`);

    // Committee UUID-based detail URL (slug_is_unique: false).
    expect(locs).toContain(`/committee/${SMOKE_EMPTY_COMMITTEE_ID}`);
    expect(pathSet(extractSitemapLocs(candidateXml).map((loc) => new URL(loc).pathname))).toEqual(
      pathSet([`/candidate/${SMOKE_CANDIDATE_SLUG}`, `/candidate/${SMOKE_OUT_OF_CYCLE_CANDIDATE_SLUG}`])
    );
    expect(pathSet(extractSitemapLocs(committeeXml).map((loc) => new URL(loc).pathname))).toEqual(
      pathSet([`/committee/${SMOKE_COMMITTEE_SLUG}`, `/committee/${SMOKE_EMPTY_COMMITTEE_ID}`])
    );
    expect(pathSet(extractSitemapLocs(personXml).map((loc) => new URL(loc).pathname))).toEqual(
      pathSet([
        `/person/${SMOKE_PERSON_ID}`,
        `/person/${SMOKE_CONGRESS_SECOND_PERSON_ID}`,
        `/person/${SMOKE_CONGRESS_NO_MONEY_PERSON_ID}`
      ])
    );
    expect(pathSet(extractSitemapLocs(staticXml).map((loc) => new URL(loc).pathname))).toEqual(
      pathSet([
        "/",
        "/congress",
        "/candidates",
        "/committees",
        SMOKE_COVERAGE_ROUTE_PATH,
        SMOKE_CALENDAR_ROUTE_PATH,
        SMOKE_DATA_SOURCES_ROUTE_PATH,
        SMOKE_ELECTION_ROUTE_PATH
      ])
    );
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
