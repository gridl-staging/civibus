import { expect, test } from "playwright/test";

import {
  SMOKE_USE_LIVE_API,
  discoverLiveLouisianaCommitteeRoute,
  seedLiveStage6CommitteeSmoke
} from "./fixtures";
import { capturePageLoadErrors } from "./smoke-helpers";

// Stage 6 truthfulness smoke: exercises the real backend against the seeded
// (or live) MIKE JOHNSON FOR LOUISIANA committee to prove the committee
// detail page (a) surfaces the official positive FEC totals even when
// itemized transactions are zero (the false-$0 gap this stage closes),
// (b) renders the per-cycle history, and (c) links back to the linked
// candidate. Fixture discovery/seeding lives in fixtures.ts.
test.describe("committee truthfulness (live mode)", () => {
  test.skip(!SMOKE_USE_LIVE_API, "live-mode only — set SMOKE_USE_LIVE_API=1");

  let cleanup: (() => Promise<void>) | null = null;

  test.beforeAll(async () => {
    cleanup = await seedLiveStage6CommitteeSmoke();
  });

  test.afterAll(async () => {
    if (cleanup !== null) {
      await cleanup();
      cleanup = null;
    }
  });

  test("committee detail exposes official FEC totals, cycle history, and linked candidate", async ({
    page
  }: {
    page: any;
  }) => {
    const pageLoadErrors = capturePageLoadErrors(page);
    const discovery = await discoverLiveLouisianaCommitteeRoute(page);

    await page.goto(discovery.committeePath);

    await expect(page.getByRole("heading", { name: "Key metrics" })).toBeVisible();
    const keyMetricsRegion = page.getByTestId("key-metrics");
    await expect(keyMetricsRegion).toContainText(discovery.expectedTotalRaisedText);
    await expect(keyMetricsRegion).not.toContainText(/Total raised[^$]*\$0\.00/);

    await expect(page.getByText(discovery.expectedSummarySourceLabel)).toBeVisible();
    await expect(page.getByText(discovery.expectedItemizedCoverageNote)).toBeVisible();

    await expect(page.getByRole("heading", { name: "Per-cycle history" })).toBeVisible();
    const cycleHistoryRegion = page.getByTestId("committee-cycle-summaries-scroll");
    await expect(cycleHistoryRegion).toContainText(discovery.expectedCycleLabel);

    const linkedCandidatesRegion = page.getByTestId("committee-linked-candidates");
    await expect(linkedCandidatesRegion).toBeVisible();
    await expect(
      linkedCandidatesRegion.getByRole("link", { name: discovery.expectedLinkedCandidateName })
    ).toBeVisible();

    await expect(page.getByRole("heading", { name: "Outside Spending" })).toBeVisible();
    const outsideSpendingRegion = page.getByTestId("committee-outside-spending");
    await expect(outsideSpendingRegion).toBeVisible();
    const expectedOutsideSpendingText =
      discovery.expectedOutsideSpendingEmptyText ?? discovery.expectedOutsideSpendingTargetName;
    expect(expectedOutsideSpendingText).not.toBeNull();
    await expect(outsideSpendingRegion.getByText(expectedOutsideSpendingText as string)).toBeVisible();

    await pageLoadErrors.assertNoErrors();
  });
});
