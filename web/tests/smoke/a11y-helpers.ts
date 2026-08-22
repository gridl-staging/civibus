import { expect } from "playwright/test";
import type { Page } from "playwright";

import { APP_SHELL } from "../../src/lib/config/app";
import {
  SMOKE_CAMPAIGN_FINANCE_IN_PROVENANCE_SOURCE_NAME,
  SMOKE_CANDIDATES_FIRST_PAGE_LABEL,
  SMOKE_CANDIDATES_FIRST_PAGE_LABEL_LIVE,
  SMOKE_CANDIDATE_LIST_CONTEXT,
  SMOKE_CANDIDATE_NAME,
  SMOKE_COMMITTEES_FIRST_PAGE_LABEL,
  SMOKE_COMMITTEES_FIRST_PAGE_LABEL_LIVE,
  SMOKE_COMMITTEE_LIST_CONTEXT,
  SMOKE_COMMITTEE_NAME,
  SMOKE_COMMITTEE_SLUG,
  SMOKE_CONGRESS_LEADER_NAME,
  SMOKE_HOME_BODY,
  SMOKE_HOME_HEADING,
  SMOKE_HOME_PRIMARY_ACTION,
  SMOKE_HOME_PRIMARY_ACTION_HREF,
  SMOKE_METHODOLOGY_SECTION_BODY,
  SMOKE_PERSON_CANONICAL_NAME,
  SMOKE_PERSON_ID,
  SMOKE_PERSON_MONEY_AT_GLANCE_HEADING,
  SMOKE_PUBLIC_API_ENDPOINTS,
  SMOKE_PUBLIC_API_HEADING,
  SMOKE_SEARCH_QUERY,
  SMOKE_SEARCH_RESULT_NAME,
  SMOKE_USE_LIVE_API
} from "./fixtures";
import {
  LINE_SERIES_MARK_SELECTOR,
  chartRegion,
  expectHtmlBarListRender,
  expectRealChartRender
} from "./smoke-helpers";

const COMMITTEE_CASH_ON_HAND_CHART_LABEL = "Cash on hand trend by filing period";
// HorizontalBarChart's frame testId. The old aria-labelled svg section is gone:
// the component's one visual encoding is a ranked HTML bar list (civibus-3a3).
const PERSON_SIZE_BUCKETS_FRAME_TEST_ID = "person-size-buckets";
const TRANSPARENT_GIF = Buffer.from("R0lGODlhAQABAAAAACw=", "base64");

export type AccessibilityScanDestination = {
  name: string;
  path: string;
  assertContent: (page: Page) => Promise<void>;
};

type ContentAssertion = (page: Page) => Promise<void>;

export async function stubExternalImages(page: Page): Promise<void> {
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const isExternalHttp = url.protocol.startsWith("http") && !["127.0.0.1", "localhost"].includes(url.hostname);
    if (request.resourceType() === "image" && isExternalHttp) {
      await route.fulfill({
        status: 200,
        contentType: "image/gif",
        body: TRANSPARENT_GIF
      });
      return;
    }

    await route.continue();
  });
}

async function expectVisibleRows(page: Page, testId: string): Promise<void> {
  const rows = page.getByTestId(testId);
  await expect(rows.first()).toBeVisible();
  expect(await rows.count()).toBeGreaterThan(0);
}

async function expectHomeContent(page: Page): Promise<void> {
  await expect(page.getByRole("heading", { name: SMOKE_HOME_HEADING })).toBeVisible();
  await expect(page.getByText(SMOKE_HOME_BODY)).toBeVisible();
  await expect(page.getByRole("link", { name: SMOKE_HOME_PRIMARY_ACTION, exact: true })).toHaveAttribute(
    "href",
    SMOKE_HOME_PRIMARY_ACTION_HREF
  );
}

async function expectSearchContent(page: Page): Promise<void> {
  await expect(page.getByRole("heading", { name: "Search" })).toBeVisible();
  await expect(page.getByLabel("Query")).toBeVisible();
  await expect(page.getByRole("link", { name: SMOKE_SEARCH_RESULT_NAME })).toBeVisible();
}

// The live seed writes two candidates and two committees (civibus-8lu), so the
// first-page labels are mode-dependent.
const candidatesFirstPageLabel = SMOKE_USE_LIVE_API
  ? SMOKE_CANDIDATES_FIRST_PAGE_LABEL_LIVE
  : SMOKE_CANDIDATES_FIRST_PAGE_LABEL;
const committeesFirstPageLabel = SMOKE_USE_LIVE_API
  ? SMOKE_COMMITTEES_FIRST_PAGE_LABEL_LIVE
  : SMOKE_COMMITTEES_FIRST_PAGE_LABEL;

async function expectCandidatesContent(page: Page): Promise<void> {
  await expect(page.getByRole("heading", { name: "Candidates" })).toBeVisible();
  await expectVisibleRows(page, "candidate-result-row");
  await expect(page.getByRole("link", { name: SMOKE_CANDIDATE_NAME })).toBeVisible();
  await expect(page.getByText(SMOKE_CANDIDATE_LIST_CONTEXT)).toBeVisible();
  await expect(page.getByText(candidatesFirstPageLabel)).toBeVisible();
}

async function expectCommitteesContent(page: Page): Promise<void> {
  await expect(page.getByRole("heading", { name: "Committees" })).toBeVisible();
  await expectVisibleRows(page, "committee-result-row");
  await expect(page.getByRole("link", { name: SMOKE_COMMITTEE_NAME })).toBeVisible();
  await expect(page.getByText(SMOKE_COMMITTEE_LIST_CONTEXT)).toBeVisible();
  await expect(page.getByText(committeesFirstPageLabel)).toBeVisible();
}

async function expectCongressContent(page: Page): Promise<void> {
  await expect(page.getByRole("heading", { name: "Congress" })).toBeVisible();
  await expect(page.getByTestId("congress-result-count")).toHaveText("3 members");
  await expect(page.getByRole("link", { name: SMOKE_CONGRESS_LEADER_NAME, exact: true })).toBeVisible();
}

async function expectDevelopersContent(page: Page): Promise<void> {
  const main = page.getByRole("main");
  await expect(main.getByRole("heading", { name: SMOKE_PUBLIC_API_HEADING })).toBeVisible();
  await expect(main.getByRole("heading", { name: SMOKE_PUBLIC_API_ENDPOINTS[0], exact: true })).toBeVisible();
}

async function expectMethodologyContent(page: Page): Promise<void> {
  await expect(page.getByRole("heading", { level: 2, name: "Methodology", exact: true })).toBeVisible();
  await expect(page.getByText(SMOKE_METHODOLOGY_SECTION_BODY)).toBeVisible();
}

async function expectPersonDetailContent(page: Page): Promise<void> {
  await expect(page.getByRole("heading", { name: SMOKE_PERSON_CANONICAL_NAME })).toBeVisible();
  await expect(page.getByRole("heading", { name: SMOKE_PERSON_MONEY_AT_GLANCE_HEADING })).toBeVisible();
  await expectHtmlBarListRender(page.getByTestId("person-receipt-composition"));
  await expectHtmlBarListRender(page.getByTestId(PERSON_SIZE_BUCKETS_FRAME_TEST_ID));
}

async function expectCommitteeDetailContent(page: Page): Promise<void> {
  await expect(page.getByRole("heading", { name: SMOKE_COMMITTEE_NAME })).toBeVisible();
  await expect(page.getByText(SMOKE_CAMPAIGN_FINANCE_IN_PROVENANCE_SOURCE_NAME)).toBeVisible();
  const chart = await chartRegion(page, COMMITTEE_CASH_ON_HAND_CHART_LABEL);
  await expect(chart).toBeVisible();
  await expectRealChartRender(chart, LINE_SERIES_MARK_SELECTOR);
}

const shellContentAssertionsByHref = new Map<string, ContentAssertion>([
  ["/", expectHomeContent],
  ["/search", expectSearchContent],
  ["/candidates", expectCandidatesContent],
  ["/committees", expectCommitteesContent],
  ["/congress", expectCongressContent],
  ["/developers", expectDevelopersContent],
  ["/methodology", expectMethodologyContent]
]);

function scanPathForShellHref(href: string): string {
  if (href === "/search") {
    return `${href}?q=${SMOKE_SEARCH_QUERY}&entity_type=org`;
  }
  return href;
}

function shellDestinations(): AccessibilityScanDestination[] {
  return APP_SHELL.shellNavigation.map((destination) => {
    const assertContent = shellContentAssertionsByHref.get(destination.href);
    if (assertContent === undefined) {
      throw new Error(`Missing accessibility smoke content assertion for ${destination.href}`);
    }
    return {
      name: destination.label,
      path: scanPathForShellHref(destination.href),
      assertContent
    };
  });
}

export const ACCESSIBILITY_SCAN_DESTINATIONS: AccessibilityScanDestination[] = [
  ...shellDestinations(),
  {
    name: "Person detail",
    path: `/person/${SMOKE_PERSON_ID}`,
    assertContent: expectPersonDetailContent
  },
  {
    name: "Committee detail",
    path: `/committee/${SMOKE_COMMITTEE_SLUG}`,
    assertContent: expectCommitteeDetailContent
  }
];
