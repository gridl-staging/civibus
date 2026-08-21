/**
 * Fixture twins for the production deploy gate's blind spots (aug21 handoff §1,
 * civibus-7o7). Three defect classes only ever failed in production, at ~8
 * minutes per attempt, because no fixture could reach them:
 *
 * 1. An identity-UNSAFE candidate ordered FIRST in a committee's linked
 *    candidates — the gate's old `link text == h2` invariant cannot hold for
 *    that row by spec design (civibus-7o7).
 * 2. An identity-SAFE candidate stored under a raw ALL-CAPS FEC name — every
 *    fixture name was mixed-case, so the raw-vs-formatted class
 *    (formatCandidatePublicName) passed vacuously until production rendered
 *    `OSSOFF, T. JONATHAN` (deploy attempt #1).
 * 3. A >20-result paged search set — fixture sets were single-result, so the
 *    "N results shown." pagination wording was unreachable locally (deploy
 *    attempt #2).
 *
 * Production coverage of the same journeys is owned by production_deploy.spec.ts
 * (which shares expectCandidateDetailMatchesLinkedName) and
 * primary_nav_nonempty.spec.ts (production search wording). This file is where
 * the arrangements are deterministic, so the classes stay red-provable locally.
 */
import { expect, test } from "playwright/test";
import type { Page } from "playwright";

import {
  SMOKE_ALLCAPS_CANDIDATE_FORMATTED_NAME,
  SMOKE_ALLCAPS_CANDIDATE_RAW_NAME,
  SMOKE_AUDITED_MALFORMED_CANDIDATE_RAW_NAME,
  SMOKE_IDENTITY_JOURNEY_COMMITTEE_ID,
  SMOKE_IDENTITY_JOURNEY_COMMITTEE_NAME,
  SMOKE_PAGED_SEARCH_FIRST_PAGE_STATUS,
  SMOKE_PAGED_SEARCH_QUERY,
  SMOKE_PAGED_SEARCH_SECOND_PAGE_STATUS,
  SMOKE_PAGED_SEARCH_TOTAL_ORG_COUNT
} from "./fixtures";
import { capturePageLoadErrors, expectCandidateDetailMatchesLinkedName } from "./smoke-helpers";

const DESTINATION_BUDGET_MS = 10_000;

function linkedCandidateLinks(page: Page) {
  return page.getByTestId("committee-linked-candidates").getByRole("link");
}

async function openIdentityJourneyCommittee(page: Page): Promise<void> {
  await page.goto(`/committee/${SMOKE_IDENTITY_JOURNEY_COMMITTEE_ID}`);
  await expect(
    page.getByRole("heading", { level: 2, name: SMOKE_IDENTITY_JOURNEY_COMMITTEE_NAME, exact: true })
  ).toBeVisible();
  await expect(linkedCandidateLinks(page)).toHaveCount(2);
}

test("unsafe-first linked candidate still lands on its own record (civibus-7o7)", async ({
  page
}: {
  page: Page;
}) => {
  const pageLoadErrors = capturePageLoadErrors(page);
  await openIdentityJourneyCommittee(page);

  // The unsafe row renders the raw FEC filing string in the list — the
  // neutral-identity contract's Browse scope. If a surface ever formats it,
  // this exact assertion goes red (the inverse bug of deploy attempt #1).
  const firstLink = linkedCandidateLinks(page).first();
  await expect(firstLink).toHaveText(SMOKE_AUDITED_MALFORMED_CANDIDATE_RAW_NAME);
  const firstLinkText = ((await firstLink.textContent()) ?? "").trim();
  await firstLink.click();

  // Red-first proof recorded 2026-08-21: with the pre-civibus-7o7 gate logic
  // (unconditional exact link-text == h2) this journey failed here with
  // `heading "212 N HALF  W. JOHN, RODNEY HOWARD MR." not found` — the page
  // renders the neutral "Candidate record" h2, by spec design. The shared
  // branched assertion below is the remedy the deploy gate now inherits.
  await expectCandidateDetailMatchesLinkedName(page, firstLinkText, DESTINATION_BUDGET_MS);
  // The unsafe arm's neutral heading is the page's actual h2 — pin it so this
  // test can never quietly drift onto the safe arm.
  await expect(
    page.getByRole("heading", { level: 2, name: "Candidate record", exact: true })
  ).toBeVisible();
  await pageLoadErrors.assertNoErrors();
});

test("all-caps-filed SAFE candidate renders formatted in the list and on its detail page", async ({
  page
}: {
  page: Page;
}) => {
  const pageLoadErrors = capturePageLoadErrors(page);
  await openIdentityJourneyCommittee(page);

  const linkedCandidates = page.getByTestId("committee-linked-candidates");
  // The identity-gated owner must have formatted the raw ALL-CAPS filing for
  // this safe identity. Both directions pinned: formatted present, raw absent.
  await expect(
    linkedCandidates.getByText(SMOKE_ALLCAPS_CANDIDATE_RAW_NAME, { exact: true })
  ).toHaveCount(0);
  const safeLink = linkedCandidates.getByRole("link", {
    name: SMOKE_ALLCAPS_CANDIDATE_FORMATTED_NAME,
    exact: true
  });
  await expect(safeLink).toBeVisible();
  await safeLink.click();

  await expectCandidateDetailMatchesLinkedName(
    page,
    SMOKE_ALLCAPS_CANDIDATE_FORMATTED_NAME,
    DESTINATION_BUDGET_MS
  );
  await pageLoadErrors.assertNoErrors();
});

test("paged org search says 'shown' on every page that held rows back", async ({
  page
}: {
  page: Page;
}) => {
  const pageLoadErrors = capturePageLoadErrors(page);
  await page.goto(`/search?q=${SMOKE_PAGED_SEARCH_QUERY}&entity_type=org`);

  // Page one: 21 fixture rows, 20 rendered, so the status must use the paged
  // wording. Exact:true — "20 results found." is precisely the healthy-build
  // deploy failure this guards against.
  await expect(page.getByTestId("search-status")).toHaveText(SMOKE_PAGED_SEARCH_FIRST_PAGE_STATUS);
  const resultItems = page.getByTestId("search-results-region").getByRole("listitem");
  await expect(resultItems).toHaveCount(20);

  const pagination = page.getByRole("navigation", { name: "Search results pagination" });
  await pagination.getByRole("link", { name: "Next", exact: true }).click();

  // Page two: offset > 0 keeps the set paged even though only one row renders.
  await expect(page.getByTestId("search-status")).toHaveText(SMOKE_PAGED_SEARCH_SECOND_PAGE_STATUS);
  await expect(resultItems).toHaveCount(SMOKE_PAGED_SEARCH_TOTAL_ORG_COUNT - 20);
  await expect(pagination.getByRole("link", { name: "Previous", exact: true })).toBeVisible();
  await pageLoadErrors.assertNoErrors();
});
