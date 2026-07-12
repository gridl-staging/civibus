import { expect, test } from "playwright/test";

import { capturePageLoadErrors } from "./smoke-helpers";

const MIN_FINANCE_CHART_HEIGHT_PX = 250;
const CONTRIBUTION_INSIGHTS_CHART_LABELS = [
  /Donations over time for/,
  /Donation count by size bucket for/,
  /Dollars by size bucket for/,
  /Fundraising geography for/
] as const;

async function expectFinanceChartHasStableHeight(page: any): Promise<void> {
  const chartRegion = page.getByLabel(/Finance chart for/).first();
  await expect(chartRegion).toBeVisible({ timeout: 20_000 });
  const chartBox = await chartRegion.boundingBox();
  expect(chartBox?.height ?? 0).toBeGreaterThanOrEqual(MIN_FINANCE_CHART_HEIGHT_PX);
}

async function expectContributionInsightsChartsHaveStableHeight(page: any): Promise<void> {
  for (const chartLabel of CONTRIBUTION_INSIGHTS_CHART_LABELS) {
    const chartRegion = page.getByLabel(chartLabel).first();
    await expect(chartRegion).toBeVisible({ timeout: 20_000 });
    const chartBox = await chartRegion.boundingBox();
    expect(chartBox?.height ?? 0).toBeGreaterThanOrEqual(MIN_FINANCE_CHART_HEIGHT_PX);
  }
}

// Post-deploy smoke for a LIVE deployment (SMOKE_MODE=production +
// SMOKE_BASE_URL). Read-only by design: no seeding, no fixture backend —
// it asserts against whatever real data the deployment serves, so every
// assertion is structural (headings, testids, "at least one member")
// rather than pinned to a named politician who may leave office.
const isProductionSmokeMode = (process.env.SMOKE_MODE ?? "local") === "production";
const PERSON_CAMPAIGN_FINANCE_HEADING = "Campaign finance";
const PERSON_OUTSIDE_SPENDING_HEADING = "Outside Spending";

test.describe("production deployment smoke (read-only)", () => {
  test.skip(!isProductionSmokeMode, "production-mode only — set SMOKE_MODE=production and SMOKE_BASE_URL");

  test("congress directory renders real members and links to a person page with finance panels", async ({
    page
  }: {
    page: any;
  }) => {
    const pageLoadErrors = capturePageLoadErrors(page);

    // Load-and-verify: the directory must render real member rows from the
    // live DB, not just the page shell (guards response-shape mismatches).
    await page.goto("/congress");
    await expect(page.getByRole("heading", { name: "Congress" })).toBeVisible();

    const firstMemberRow = page.getByTestId("congress-member-row-0");
    await expect(firstMemberRow).toBeVisible();

    // The federal-first dataset holds 500+ seated members; a directory
    // rendering far fewer means a partial/wrong data load, not a UI bug.
    const resultCount = await page.getByTestId("congress-result-count").textContent();
    const renderedCount = Number.parseInt(resultCount ?? "0", 10);
    expect(renderedCount).toBeGreaterThanOrEqual(500);

    // Portrait enrichment is live (>90% coverage floor): at least one real
    // portrait image must render in the directory, not only fallbacks.
    await expect(page.getByTestId("entity-portrait-image").first()).toBeVisible();

    // Act as a human: click the first member's name link and verify the
    // person page shows that member with money + outside-spending panels.
    const memberLink = firstMemberRow.getByRole("link");
    const memberName = (await memberLink.textContent())?.trim() ?? "";
    expect(memberName.length).toBeGreaterThan(0);
    await memberLink.click();

    await expect(page.getByRole("heading", { name: memberName })).toBeVisible();
    await expect(
      page.getByRole("heading", { name: PERSON_CAMPAIGN_FINANCE_HEADING })
    ).toBeVisible();
    await expectFinanceChartHasStableHeight(page);
    await expect(page.getByRole("heading", { name: "Fundraising detail" })).toBeVisible({
      timeout: 20_000
    });
    await expectContributionInsightsChartsHaveStableHeight(page);
    // exact: true matters — while the streamed finance section loads, its
    // SkeletonPanel renders a transient <h3>Outside spending</h3> that a
    // case-insensitive locator also matches (strict-mode violation). The
    // stable post-load heading is the panel's <h4>Outside Spending</h4>.
    // The generous timeout covers cold-cache streamed SSR on the live DB.
    await expect(
      page.getByRole("heading", { name: PERSON_OUTSIDE_SPENDING_HEADING, exact: true })
    ).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole("heading", { name: "Graph relationships" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Entity-resolution matches" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Officeholding timeline" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Candidacies" })).toHaveCount(0);
    await expect(page.getByRole("group", { name: "Entity internals" })).toHaveCount(0);
    await pageLoadErrors.assertNoErrors();
  });

  test("person page loads without client-side errors", async ({ page }: { page: any }) => {
    const pageLoadErrors = capturePageLoadErrors(page);
    await page.goto("/congress");
    await page.getByTestId("congress-member-row-0").getByRole("link").click();
    await expect(
      page.getByRole("heading", { name: PERSON_CAMPAIGN_FINANCE_HEADING })
    ).toBeVisible({ timeout: 20_000 });
    await expectFinanceChartHasStableHeight(page);
    await expect(page.getByRole("heading", { name: "Fundraising detail" })).toBeVisible({
      timeout: 20_000
    });
    await expectContributionInsightsChartsHaveStableHeight(page);
    await expect(page.getByRole("heading", { name: "Graph relationships" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Entity-resolution matches" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Officeholding timeline" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Candidacies" })).toHaveCount(0);
    await expect(page.getByRole("group", { name: "Entity internals" })).toHaveCount(0);

    await pageLoadErrors.assertNoErrors();
  });

  test("committee detail exposes official totals, cycle history, and linked candidates in production", async ({
    page
  }: {
    page: any;
  }) => {
    const pageLoadErrors = capturePageLoadErrors(page);

    // Discover a real committee route by clicking through the public
    // /committees list rather than hard-coding a UUID/slug: this keeps the
    // assertion resilient to production deploys that reseed IDs.
    await page.goto("/committees");
    await expect(page.getByRole("heading", { name: "Committees" })).toBeVisible();
    const firstCommitteeLink = page.getByRole("heading", { level: 3 }).first().getByRole("link");
    await expect(firstCommitteeLink).toBeVisible();
    await firstCommitteeLink.click();

    // On the committee detail page: the key-metrics card must show a source
    // label (either "Official FEC committee summary" or "Derived from itemized
    // transactions") plus the itemized coverage note that starts every note
    // with the same prefix. Both prove the false-$0 fix is deployed.
    await expect(page.getByRole("heading", { name: "Key metrics" })).toBeVisible({ timeout: 20_000 });
    const keyMetrics = page.getByTestId("key-metrics");
    await expect(keyMetrics).toContainText(/\$[\d,]+\.\d{2}/);
    await expect(
      page.getByText(/^Official FEC committee summary$|^Derived from itemized transactions$/).first()
    ).toBeVisible();
    await expect(page.getByText(/^Itemized transactions loaded: /).first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "Per-cycle history" })).toBeVisible();

    await pageLoadErrors.assertNoErrors();
  });

  test("committee detail linked candidates navigate to a candidate page in production", async ({
    page
  }: {
    page: any;
  }) => {
    const pageLoadErrors = capturePageLoadErrors(page);

    // Federal candidates always have a principal committee, and that committee
    // always carries a linked_candidates entry for the candidate itself.
    // Discovering the committee via /congress -> member -> principal committee
    // guarantees the linked-candidates section renders, so the navigation
    // assertion can be unconditional (no test-time conditionals).
    await page.goto("/congress");
    await page.getByTestId("congress-member-row-0").getByRole("link").click();
    await expect(
      page.getByRole("heading", { name: PERSON_CAMPAIGN_FINANCE_HEADING })
    ).toBeVisible({ timeout: 20_000 });

    const principalCommitteeLink = page
      .getByRole("main")
      .getByRole("link", { name: /Committee record/ })
      .first();
    await expect(principalCommitteeLink).toBeVisible({ timeout: 20_000 });
    await principalCommitteeLink.click();

    const linkedCandidates = page.getByTestId("committee-linked-candidates");
    await expect(linkedCandidates).toBeVisible({ timeout: 20_000 });
    const firstLinkedCandidate = linkedCandidates.getByRole("link").first();
    await expect(firstLinkedCandidate).toBeVisible();
    await firstLinkedCandidate.click();
    await expect(page).toHaveURL(/\/candidate\//);

    await pageLoadErrors.assertNoErrors();
  });

  test("search finds a member from the live directory", async ({ page }: { page: any }) => {
    const pageLoadErrors = capturePageLoadErrors(page);

    // Arrange: read a real member name off the live directory first, so the
    // search assertion is self-consistent with whatever data is deployed.
    await page.goto("/congress");
    const memberLink = page.getByTestId("congress-member-row-0").getByRole("link");
    const memberName = (await memberLink.textContent())?.trim() ?? "";
    expect(memberName.length).toBeGreaterThan(0);
    const lastName = memberName.split(",")[0]?.trim() ?? memberName;
    expect(lastName.length).toBeGreaterThan(0);

    // Act: exercise the actual /search page (Stage 2/3 owner) with the last
    // name of a real seated member. Structural assertions only — production
    // data drifts, so we cannot pin the member's party or district here.
    await page.goto(`/search?q=${encodeURIComponent(lastName)}`);
    await expect(page.getByRole("heading", { name: "Search" })).toBeVisible();

    const firstResult = page
      .getByTestId("search-results-region")
      .getByRole("listitem")
      .nth(0);
    await expect(firstResult).toBeVisible();
    // Officeholder-first ranking: the top hit for a seated member's last name
    // must be their Person entity, not a candidate/committee row.
    await expect(firstResult.getByRole("link", { name: memberName })).toBeVisible();
    await expect(firstResult.getByText("Person", { exact: true })).toBeVisible();
    // Stage 3 context line renders `office_name · state · party` for current
    // federal officeholders, joined by the ` · ` separator; asserting the
    // separator is present is a structural proof the enrichment reached the
    // UI without pinning the specific office/state/party (which drifts).
    await expect(firstResult).toContainText(" · ");

    await pageLoadErrors.assertNoErrors();
  });
});
