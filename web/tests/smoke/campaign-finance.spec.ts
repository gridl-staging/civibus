import { expect, test } from "playwright/test";

import {
  SMOKE_CANDIDATE_COMMITTEE_LINK_TEXT,
  SMOKE_CANDIDATE_DATA_THROUGH,
  SMOKE_CANDIDATE_DESCRIPTION,
  SMOKE_CANDIDATE_ID,
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
  SMOKE_COMMITTEE_FILING_ROW_LABEL,
  SMOKE_COMMITTEE_FILING_SUMMARY_EMPTY_STATE,
  SMOKE_COMMITTEE_ID,
  SMOKE_COMMITTEE_NAME,
  SMOKE_COMMITTEE_NET_TOTAL,
  SMOKE_COMMITTEE_ORG_LINK_TEXT,
  SMOKE_COMMITTEE_RECIPIENT_CANDIDATE_LINK_TEXT,
  SMOKE_COMMITTEE_RECIPIENT_COMMITTEE_LINK_TEXT,
  SMOKE_COMMITTEE_SLUG,
  SMOKE_COMMITTEE_TITLE,
  SMOKE_COMMITTEE_TOTAL_RAISED,
  SMOKE_COMMITTEE_TOTAL_SPENT,
  SMOKE_COMMITTEES_DESCRIPTION,
  SMOKE_COMMITTEES_TITLE,
  SMOKE_EMPTY_CANDIDATE_DESCRIPTION,
  SMOKE_EMPTY_CANDIDATE_ID,
  SMOKE_EMPTY_CANDIDATE_TITLE,
  SMOKE_EMPTY_COMMITTEE_DESCRIPTION,
  SMOKE_EMPTY_COMMITTEE_ID,
  SMOKE_EMPTY_COMMITTEE_TITLE,
  SMOKE_IE_COMMITTEE_A_ID,
  SMOKE_IE_COMMITTEE_A_NAME,
  SMOKE_IE_TRANSACTION_DISSEMINATION_DATE,
  SMOKE_ORG_ID,
  SMOKE_PERSON_ID,
  SMOKE_PROVENANCE_LAST_PULLED,
  SMOKE_PROVENANCE_SOURCE_NAME,
  SMOKE_TRUST_ADVISORY,
  SMOKE_TRUST_EMPTY_MESSAGE,
  SMOKE_TRUST_LAST_PULLED_UNAVAILABLE
} from "./fixtures";
import {
  assertBreadcrumbJsonLd,
  assertBreadcrumbNav,
  assertSeoHead
} from "./smoke-helpers";

test.describe("campaign finance smoke", () => {
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
    await expect(page.getByRole("link", { name: "Next" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Previous" })).toHaveCount(0);

    await page.goto("/candidates?offset=1&limit=1");

    const candidatesSecondPage = new URL(page.url());
    const candidatesCanonical = `${candidatesSecondPage.origin}/candidates`;
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", candidatesCanonical);
    await expect(page.getByRole("link", { name: "Previous" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Next" })).toHaveCount(0);
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
    await expect(page.getByRole("link", { name: "Next" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Previous" })).toHaveCount(0);

    await page.goto("/committees?offset=1&limit=1");

    const committeesSecondPage = new URL(page.url());
    const committeesCanonical = `${committeesSecondPage.origin}/committees`;
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", committeesCanonical);
    await expect(page.getByRole("link", { name: "Previous" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Next" })).toHaveCount(0);
  });

  test("/committee/[id] renders committee detail and committee-only transactions", async ({ page }: { page: any }) => {
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
    await expect(page.getByText(SMOKE_PROVENANCE_SOURCE_NAME)).toBeVisible();
    await expect(page.getByText(SMOKE_PROVENANCE_LAST_PULLED)).toHaveCount(1);
    await expect(page.getByText(SMOKE_TRUST_ADVISORY)).toBeVisible();
    await expect(page.getByRole("link", { name: SMOKE_COMMITTEE_ORG_LINK_TEXT })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Fundraising summary" })).toBeVisible();
    const committeeFundraisingSummary = page.getByRole("region", { name: "Fundraising summary" });
    await expect(committeeFundraisingSummary.getByText(SMOKE_COMMITTEE_TOTAL_RAISED)).toBeVisible();
    await expect(committeeFundraisingSummary.getByText(SMOKE_COMMITTEE_TOTAL_SPENT)).toBeVisible();
    await expect(committeeFundraisingSummary.getByText(SMOKE_COMMITTEE_NET_TOTAL)).toBeVisible();
    await expect(page.getByRole("heading", { name: "Filing-period breakdown" })).toBeVisible();
    await expect(page.getByRole("cell", { name: SMOKE_COMMITTEE_FILING_ROW_LABEL })).toBeVisible();
    await expect(page.getByText("amount: 125.00")).toBeVisible();
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
    await expect(page.getByText(SMOKE_PROVENANCE_SOURCE_NAME)).toBeVisible();
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
    await expect(page.getByText(`dissemination date: ${SMOKE_IE_TRANSACTION_DISSEMINATION_DATE}`)).toBeVisible();

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

    await expect(page.getByRole("heading", { name: "Fundraising summary" })).toBeVisible();
    const emptyCandidateFundraisingSummary = page.getByRole("region", { name: "Fundraising summary" });
    await expect(emptyCandidateFundraisingSummary.getByText("$0.00")).toHaveCount(3);
    await expect(page.getByRole("heading", { name: "Committee breakdown" })).toHaveCount(0);
    await assertBreadcrumbNav(page);
    await assertBreadcrumbJsonLd(page);
  });
});

test.describe("sitemap.xml", () => {
  test("returns valid sitemap XML with static and detail URLs", async ({ page }: { page: any }) => {
    const response = (await page.goto("/sitemap.xml"))!;

    expect(response.status()).toBe(200);
    expect(response.headers()["content-type"]).toContain("xml");

    const xml = await response.text();

    // Valid XML structure
    expect(xml).toContain('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">');

    // Static pages
    expect(xml).toContain("<url><loc>");
    expect(xml).toContain(`<loc>${new URL("/", response.url()).href}</loc>`);
    expect(xml).toMatch(/<loc>[^<]*\/candidates<\/loc>/);
    expect(xml).toMatch(/<loc>[^<]*\/committees<\/loc>/);

    // Slug-based detail URL from fixture (pat-candidate has slug_is_unique: true)
    expect(xml).toContain(`/candidate/${SMOKE_CANDIDATE_SLUG}</loc>`);

    // UUID-based detail URL for slug_is_unique: false fixture
    expect(xml).toContain(`/candidate/${SMOKE_EMPTY_CANDIDATE_ID}</loc>`);

    // Committee slug-based detail URL
    expect(xml).toContain(`/committee/${SMOKE_COMMITTEE_SLUG}</loc>`);

    // Committee UUID-based detail URL (slug_is_unique: false)
    expect(xml).toContain(`/committee/${SMOKE_EMPTY_COMMITTEE_ID}</loc>`);
  });
});
