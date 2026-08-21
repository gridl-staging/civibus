/**
 * Person-page resilience journey (civibus-e7v): the degradation contract of
 * docs/reference/screen_specs/person_detail.md (### Error), proven in a real
 * browser against the real API and database.
 *
 * The journey poisons a DEDICATED specimen at the civibus-ga8-diagnosed seam —
 * a stored value that is schema-legal at the column but illegal at the response
 * contract (NaN in cf.candidate.total_receipts), which turns the candidate
 * summary subresource into a 500 while /v1/person stays valid — and asserts the
 * person page stays HTTP 200 with bio/office content while exactly the failed
 * sections render their explicit unavailable notices. This is the browser-level
 * guard that did not exist when production person pages 500ed: no journey
 * visited a person page under partial backend failure.
 *
 * The specimen is seeded AT SPEC TIME and referenced by no other spec (the
 * contract test below enforces that by grepping web/tests/smoke/), so the
 * poisoned window inside the single test body can never be observed by another
 * journey even though the live database is shared.
 */
import { expect, test } from "playwright/test";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { SMOKE_USE_LIVE_API } from "./fixtures";
import {
  cleanUpLivePersonResilienceSmoke,
  poisonLivePersonResilienceCandidate,
  restoreLivePersonResilienceCandidate,
  seedLivePersonResilienceSmoke,
  SMOKE_RESILIENCE_PERSON_ID,
  SMOKE_RESILIENCE_PERSON_NAME,
  SMOKE_RESILIENCE_TOTAL_RAISED
} from "./person_resilience_fixture";

// Copy owned by web/src/lib/entity-detail/person-campaign-finance-presentation.ts
// (PERSON_TEMPORARILY_UNAVAILABLE_MESSAGE) and the DetailPage {:catch} arms the
// spec's section-notice table names.
const MONEY_SUMMARY_UNAVAILABLE_COPY = "Selected-cycle money summary is temporarily unavailable.";
const FINANCE_SECTIONS_UNAVAILABLE_COPY = "Campaign-finance sections are temporarily unavailable.";

// Orders THIS file's tests only; playwright.config.ts still runs files fully
// parallel — isolation comes from the dedicated specimen, not from serial mode.
test.describe.configure({ mode: "serial" });

test.describe("person page resilience (live mode)", () => {
  test.skip(!SMOKE_USE_LIVE_API, "live-mode only — set SMOKE_USE_LIVE_API=1");

  test("a failing finance section degrades to notices while the page stays 200", async ({
    page
  }: {
    page: any;
  }) => {
    // Four fixture subprocess invocations plus five navigations ride this test.
    test.setTimeout(120_000);
    await seedLivePersonResilienceSmoke();
    try {
      try {
        // Load-and-verify BEFORE poisoning: the healthy page must show the
        // office context and the seeded official total, or the degraded
        // assertions below could pass against a page that never worked.
        const healthyResponse = await page.goto(`/person/${SMOKE_RESILIENCE_PERSON_ID}`);
        expect(healthyResponse?.status()).toBe(200);
        await expect(
          page.getByRole("heading", { level: 2, name: SMOKE_RESILIENCE_PERSON_NAME, exact: true })
        ).toBeVisible();
        await expect(page.getByText("Current office", { exact: true })).toBeVisible();
        await expect(page.getByRole("link", { name: "Representative", exact: true })).toBeVisible();
        await expect(
          page.getByText(SMOKE_RESILIENCE_TOTAL_RAISED, { exact: true }).first()
        ).toBeVisible({ timeout: 20_000 });
        await expect(page.getByTestId("person-finance-unavailable")).toHaveCount(0);

        await poisonLivePersonResilienceCandidate();

        // The degradation contract: partial backend failure -> HTTP 200 with
        // bio/office intact, failed sections announcing themselves explicitly.
        const poisonedResponse = await page.goto(`/person/${SMOKE_RESILIENCE_PERSON_ID}`);
        expect(poisonedResponse?.status()).toBe(200);
        await expect(
          page.getByRole("heading", { level: 2, name: SMOKE_RESILIENCE_PERSON_NAME, exact: true })
        ).toBeVisible();
        await expect(page.getByText("Current office", { exact: true })).toBeVisible();
        await expect(page.getByRole("link", { name: "Representative", exact: true })).toBeVisible();
        // The money headline degrades to the spec's unavailable copy…
        await expect(page.getByText(MONEY_SUMMARY_UNAVAILABLE_COPY).first()).toBeVisible({
          timeout: 20_000
        });
        // …and the finance sections degrade at the OUTER boundary — the
        // person_detail.md section-notice table's person-finance-unavailable
        // arm. Observed landed behavior (2026-08-21, this poison): the
        // candidate's summary rejection propagates through the streamed
        // sections payload, so the whole finance panel (not just one
        // subsection) announces itself unavailable while bio/office and the
        // page's 200 stay intact. If a later change tightens degradation to
        // per-subsection notices, this exact-copy assertion goes red and the
        // journey should pin the narrower arm instead.
        await expect(page.getByTestId("person-finance-unavailable")).toHaveText(
          FINANCE_SECTIONS_UNAVAILABLE_COPY
        );
        // No seeded dollar figure may leak through the failed sections: the
        // degraded page must not show stale money beside its own notice.
        await expect(page.getByText(SMOKE_RESILIENCE_TOTAL_RAISED, { exact: true })).toHaveCount(0);
      } finally {
        // Acceptance (c): restore in the finally…
        await restoreLivePersonResilienceCandidate();
      }

      // …proven by a follow-up navigation rendering the healthy page again.
      const restoredResponse = await page.goto(`/person/${SMOKE_RESILIENCE_PERSON_ID}`);
      expect(restoredResponse?.status()).toBe(200);
      await expect(
        page.getByText(SMOKE_RESILIENCE_TOTAL_RAISED, { exact: true }).first()
      ).toBeVisible({ timeout: 20_000 });
      await expect(page.getByTestId("person-finance-unavailable")).toHaveCount(0);
      await expect(page.getByText(MONEY_SUMMARY_UNAVAILABLE_COPY)).toHaveCount(0);
    } finally {
      // The specimen is a current federal officeholder; it must not outlive
      // its journey or every later whole-database assertion (member counts,
      // Showing 1–N labels) drifts.
      await cleanUpLivePersonResilienceSmoke();
    }
  });

  test("no other smoke spec references the dedicated resilience specimen", async () => {
    // The poisoned window is only safe because this spec is the specimen's
    // sole consumer. Grep the smoke tree so a future spec reusing the specimen
    // fails HERE with the reason, instead of flaking on a poisoned read.
    const smokeDirectory = dirname(fileURLToPath(import.meta.url));
    const offendingFiles = readdirSync(smokeDirectory)
      .filter((fileName) => fileName.endsWith(".spec.ts") && fileName !== "person_resilience.spec.ts")
      .filter((fileName) => {
        const contents = readFileSync(join(smokeDirectory, fileName), "utf8");
        return (
          contents.includes("SMOKE_RESILIENCE") || contents.includes(SMOKE_RESILIENCE_PERSON_ID)
        );
      });
    expect(offendingFiles).toEqual([]);
  });
});
