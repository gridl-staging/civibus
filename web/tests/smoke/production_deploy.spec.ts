import { expect, test } from "playwright/test";

import {
  capturePageLoadErrors,
  chartRegion,
  expectActionToVisibleContentWithinBudget,
  expectCampaignFinanceKeyMetricsReady,
  expectNoBackendFailureStates,
  expectNoPartyCommitteeInLinkedCommittees,
  parseRenderedMoneyLabel
} from "./smoke-helpers";

const MIN_FINANCE_CHART_HEIGHT_PX = 250;
// Every finance chart on the person page. These are data-dependent: the
// receipt-source-composition chart shows a truthful "components not loaded yet"
// state for members whose committee-summary breakdown is not loaded (true for
// every member on prod today), and the itemized insight charts are empty for a
// member with no itemized rows. /congress is now money-sorted (LB4), so row 0 is
// an arbitrary top fundraiser whose data shape we cannot assume.
const FINANCE_CHART_LABELS = [
  "Receipt source composition by dollars",
  "Monthly contribution columns",
  "Itemized contribution-size buckets bar chart",
  "Geography dollar share by contributor location"
] as const;

// Guard that IF a finance chart renders it is not collapsed -- without demanding
// that any specific chart render, because chart presence depends on live data
// (see FINANCE_CHART_LABELS). Deep chart honesty (paints, bounded ticks, no
// overflow) is owned by production_finance_visuals.spec.ts on a pinned person
// known to have itemized data; this deploy smoke only proves the click-through
// reaches a working finance panel. Pair every call with
// expectNoBackendFailureStates so an outage can never masquerade as "no data".
async function expectRenderedFinanceChartsNotCollapsed(page: any): Promise<void> {
  for (const chartLabel of FINANCE_CHART_LABELS) {
    const region = await chartRegion(page, chartLabel);
    if ((await region.count()) === 0 || !(await region.isVisible())) {
      continue;
    }
    const chartBox = await region.boundingBox();
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
const PERF_BUDGET_MS = 8000;
const MONEY_PLAUSIBILITY_CEILING_DOLLARS = 2_000_000_000;
const PINNED_HIGH_VOLUME_COMMITTEE_PATH = "/committee/jon-ossoff-for-senate";
// Must match the component's exact rendered text. DetailPage.svelte renders
// <h4 id="person-outside-spending">Outside spending</h4> (sentence case) and has
// since the module was built; the prior title-case "Outside Spending" here never
// matched with exact:true and only ever "passed" because earlier steps failed
// first.
const PERSON_OUTSIDE_SPENDING_HEADING = "Outside spending";
const CONGRESS_MEMBER_PROFILE_LINK_TEST_ID = "congress-member-profile-link";
const CONGRESS_MEMBER_ROW_0_TEST_ID = "congress-member-row-0";
const PERSON_ROUTE_HREF_PATTERN = /^\/person\/[^/?#]+$/;

type DonorRecipientSelection = {
  recipientHref: string;
  recipientLink: any;
  recipientName: string;
  resultRow: any;
};

function memberProfileLink(row: any): any {
  return row.getByTestId(CONGRESS_MEMBER_PROFILE_LINK_TEST_ID);
}

function extractRouteId(href: string, routePrefix: "/person" | "/candidate"): string {
  const path = new URL(href, "https://civibus.local").pathname;
  const expectedPrefix = `${routePrefix}/`;
  expect(path.startsWith(expectedPrefix)).toBe(true);

  const id = decodeURIComponent(path.slice(expectedPrefix.length));
  expect(id.length).toBeGreaterThan(0);
  expect(id.includes("/")).toBe(false);
  return id;
}

async function personRecipientLinkInRow(resultRow: any): Promise<DonorRecipientSelection | null> {
  const links = await resultRow.getByRole("link").all();
  for (const recipientLink of links) {
    if (!(await recipientLink.isVisible())) {
      continue;
    }
    const recipientHref = await recipientLink.getAttribute("href");
    if (!recipientHref || !PERSON_ROUTE_HREF_PATTERN.test(recipientHref)) {
      continue;
    }
    const recipientName = ((await recipientLink.textContent()) ?? "").trim();
    if (recipientName.length === 0) {
      continue;
    }
    return { recipientHref, recipientLink, recipientName, resultRow };
  }
  return null;
}

async function donorResultWithPersonRecipient(page: any): Promise<DonorRecipientSelection> {
  const resultRows = page.getByTestId("donor-result-row");
  await expect(resultRows.first()).toBeVisible({ timeout: 20_000 });

  for (const resultRow of await resultRows.all()) {
    const selection = await personRecipientLinkInRow(resultRow);
    if (selection) {
      return selection;
    }
  }

  throw new Error("Expected at least one donor result row with a /person/<id> recipient link");
}

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
    await page.goto("/congress?sort=total_raised");
    await expect(page.getByRole("heading", { name: "Congress" })).toBeVisible();

    const firstMemberRow = page.getByTestId(CONGRESS_MEMBER_ROW_0_TEST_ID);
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
    const memberLink = memberProfileLink(firstMemberRow);
    const memberName = (await memberLink.textContent())?.trim() ?? "";
    expect(memberName.length).toBeGreaterThan(0);
    await expect(memberLink).toHaveAttribute("href", /^\/person\/[^/?#]+/);
    const memberHref = await memberLink.getAttribute("href");
    const personId = extractRouteId(memberHref as string, "/person");
    const totalRaisedLabel = firstMemberRow.getByTestId(`comparison-end-label-${personId}`);
    await expect(totalRaisedLabel).toBeVisible();
    const totalRaisedDollars = parseRenderedMoneyLabel((await totalRaisedLabel.textContent()) ?? "");
    expect(totalRaisedDollars).toBeGreaterThan(0);
    expect(totalRaisedDollars).toBeLessThan(MONEY_PLAUSIBILITY_CEILING_DOLLARS);
    await memberLink.click();

    await expect(page.getByRole("heading", { name: memberName })).toBeVisible();
    await expect(
      page.getByRole("heading", { name: PERSON_CAMPAIGN_FINANCE_HEADING })
    ).toBeVisible();
    await expect(page.getByRole("heading", { name: "Fundraising detail" })).toBeVisible({
      timeout: 20_000
    });
    // Settle the streamed money panels, then prove the finance panel is not
    // silently in a backend-failure state before checking chart honesty.
    await expectNoBackendFailureStates(page);
    await expectNoPartyCommitteeInLinkedCommittees(page);
    await expectRenderedFinanceChartsNotCollapsed(page);
    // The panel settled above (expectNoBackendFailureStates waits out the
    // SkeletonPanel), so only the stable <h4>Outside spending</h4> remains;
    // exact:true pins it to that heading and not the "Outside spending details"
    // CTA link. The generous timeout covers cold-cache streamed SSR on the live DB.
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
    await memberProfileLink(page.getByTestId(CONGRESS_MEMBER_ROW_0_TEST_ID)).click();
    await expect(
      page.getByRole("heading", { name: PERSON_CAMPAIGN_FINANCE_HEADING })
    ).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole("heading", { name: "Fundraising detail" })).toBeVisible({
      timeout: 20_000
    });
    await expectNoBackendFailureStates(page);
    await expectRenderedFinanceChartsNotCollapsed(page);
    await expect(page.getByRole("heading", { name: "Graph relationships" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Entity-resolution matches" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Officeholding timeline" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Candidacies" })).toHaveCount(0);
    await expect(page.getByRole("group", { name: "Entity internals" })).toHaveCount(0);

    await pageLoadErrors.assertNoErrors();
  });

  test("donor lookup returns live results and links to recipient finance", async ({
    page
  }: {
    page: any;
  }) => {
    // The donor query has a documented ~19.45s cold path before the recipient page load.
    test.setTimeout(60_000);
    const pageLoadErrors = capturePageLoadErrors(page);
    // Intentionally non-empty in production's 16,050,580-row cf.transaction table.
    const donorQuery = "smith";

    await page.goto("/donors");
    await expect(page.getByRole("heading", { name: "Donor Lookup", exact: true })).toBeVisible();
    await expect(page.getByTestId("donor-scope-note")).toBeVisible();

    const queryInput = page.getByLabel("Query");
    await expect(queryInput).toHaveValue("");
    await page.getByLabel("Search by").selectOption("name");
    await queryInput.fill(donorQuery);
    await expect(queryInput).toHaveValue(donorQuery);
    await page.getByRole("button", { name: "Search", exact: true }).click();

    await page.waitForURL(
      (url: URL) =>
        url.pathname === "/donors" &&
        url.searchParams.get("q") === donorQuery &&
        url.searchParams.get("by") === "name"
    );

    const { recipientHref, recipientLink, recipientName, resultRow } =
      await donorResultWithPersonRecipient(page);
    await expect(resultRow).toBeVisible();
    await expectNoBackendFailureStates(page);

    const contributorName = (
      (await resultRow.getByRole("cell").first().textContent()) ?? ""
    ).trim();
    expect(contributorName.length).toBeGreaterThan(0);
    await expect(resultRow).toContainText(/\$(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{2})?/);

    await expect(recipientLink).toBeVisible();
    await expect(recipientLink).toHaveAttribute("href", PERSON_ROUTE_HREF_PATTERN);
    expect(recipientName.length).toBeGreaterThan(0);

    await recipientLink.click();
    await page.waitForURL((url: URL) => url.pathname === recipientHref);
    expect(new URL(page.url()).pathname).toBe(recipientHref);
    await expect(
      page.getByRole("heading", { name: PERSON_CAMPAIGN_FINANCE_HEADING })
    ).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole("heading", { name: "Fundraising detail" })).toBeVisible({
      timeout: 20_000
    });
    await expectNoBackendFailureStates(page);
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

    await expectActionToVisibleContentWithinBudget({
      label: "/congress",
      budgetMs: PERF_BUDGET_MS,
      action: async () => {
        await page.goto("/congress");
      },
      visibleContent: async () => {
        await expect(page.getByTestId(CONGRESS_MEMBER_ROW_0_TEST_ID)).toBeVisible({
          timeout: PERF_BUDGET_MS
        });
      }
    });

    await expectActionToVisibleContentWithinBudget({
      label: PINNED_HIGH_VOLUME_COMMITTEE_PATH,
      budgetMs: PERF_BUDGET_MS,
      action: async () => {
        await page.goto(PINNED_HIGH_VOLUME_COMMITTEE_PATH);
      },
      visibleContent: async () => {
        await expectCampaignFinanceKeyMetricsReady(page, PERF_BUDGET_MS);
        await expect(page.getByTestId("committee-linked-candidates")).toBeVisible({
          timeout: PERF_BUDGET_MS
        });
      }
    });

    const linkedCandidates = page.getByTestId("committee-linked-candidates");
    const firstLinkedCandidate = linkedCandidates.getByRole("link").first();
    await expect(firstLinkedCandidate).toBeVisible();
    const candidateName = ((await firstLinkedCandidate.textContent()) ?? "").trim();
    expect(candidateName.length).toBeGreaterThan(0);

    await expectActionToVisibleContentWithinBudget({
      label: "linked candidate page",
      budgetMs: PERF_BUDGET_MS,
      action: async () => {
        await firstLinkedCandidate.click();
      },
      visibleContent: async () => {
        await expect(page).toHaveURL(/\/candidate\//, { timeout: PERF_BUDGET_MS });
        await expect(page.getByRole("heading", { name: candidateName })).toBeVisible({
          timeout: PERF_BUDGET_MS
        });
        await expectCampaignFinanceKeyMetricsReady(page, PERF_BUDGET_MS);
      }
    });

    await pageLoadErrors.assertNoErrors();
  });

  test("search finds a member from the live directory", async ({ page }: { page: any }) => {
    const pageLoadErrors = capturePageLoadErrors(page);

    // Arrange: read a real member name off the live directory first, so the
    // search assertion is self-consistent with whatever data is deployed.
    await page.goto("/congress");
    const memberLink = memberProfileLink(page.getByTestId(CONGRESS_MEMBER_ROW_0_TEST_ID));
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
