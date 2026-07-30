import { expect, test } from "playwright/test";

import {
  seedLiveDonorLookupSmoke,
  SMOKE_DONOR_LOOKUP_HEADING,
  SMOKE_DONOR_LOOKUP_QUERY,
  SMOKE_DONOR_LOOKUP_RECIPIENT_NAME,
  SMOKE_DONOR_LOOKUP_RESULT_COUNT,
  SMOKE_DONOR_LOOKUP_SCOPE_NOTE,
  SMOKE_DONOR_LOOKUP_SEED_CONTRIBUTOR_NAME,
  SMOKE_DONOR_LOOKUP_SEED_EMPLOYER,
  SMOKE_DONOR_LOOKUP_SEED_PERSON_ID,
  SMOKE_DONOR_LOOKUP_SEED_TOTAL_AMOUNT,
  SMOKE_DONOR_LOOKUP_SEED_ZIP5,
  SMOKE_USE_LIVE_API
} from "./fixtures";
import {
  SMOKE_DONOR_LOOKUP_COMBINED_CITY_A,
  SMOKE_DONOR_LOOKUP_COMBINED_CITY_B,
  SMOKE_DONOR_LOOKUP_COMBINED_CONTRIBUTOR_A,
  SMOKE_DONOR_LOOKUP_COMBINED_CONTRIBUTOR_B,
  SMOKE_DONOR_LOOKUP_COMBINED_COUNT_LABEL,
  SMOKE_DONOR_LOOKUP_COMBINED_EMPLOYER_A,
  SMOKE_DONOR_LOOKUP_CONFIDENCE_LABEL,
  SMOKE_DONOR_LOOKUP_NOT_COMBINED_CONTRIBUTOR,
  SMOKE_DONOR_LOOKUP_PAGINATION_EDIT_QUERY,
  SMOKE_DONOR_LOOKUP_SECOND_CONTRIBUTOR_NAME,
  SMOKE_DONOR_LOOKUP_SECOND_PAGE_RESULT_COUNT
} from "./donor_lookup_fixture";
import { capturePageLoadErrors } from "./smoke-helpers";

test.describe("donor lookup smoke (fixture mode)", () => {
  test.skip(SMOKE_USE_LIVE_API, "fixture-mode only");

  test("/donors resynchronizes URL-owned query after same-query pagination", async ({
    page
  }: {
    page: any;
  }) => {
    const pageLoadErrors = capturePageLoadErrors(page);

    await page.goto(`/donors?q=${SMOKE_DONOR_LOOKUP_QUERY}&by=name&limit=1&offset=0`);

    const queryInput = page.getByLabel("Query");
    await expect(page.getByRole("heading", { name: SMOKE_DONOR_LOOKUP_HEADING })).toBeVisible();
    await expect(queryInput).toHaveValue(SMOKE_DONOR_LOOKUP_QUERY);
    await expect(page.getByTestId("donor-result-count")).toHaveText(SMOKE_DONOR_LOOKUP_RESULT_COUNT);
    await expect(page.getByTestId("donor-result-row")).toContainText(SMOKE_DONOR_LOOKUP_SEED_CONTRIBUTOR_NAME);

    await queryInput.fill(SMOKE_DONOR_LOOKUP_PAGINATION_EDIT_QUERY);
    await page.getByRole("link", { name: "Next" }).click();

    await expect(page).toHaveURL(/\/donors\?[^#]*offset=1/);
    const currentUrl = new URL(page.url());
    expect(currentUrl.pathname).toBe("/donors");
    expect(currentUrl.searchParams.get("q")).toBe(SMOKE_DONOR_LOOKUP_QUERY);
    expect(currentUrl.searchParams.get("by")).toBe("name");
    expect(currentUrl.searchParams.get("limit")).toBe("1");
    expect(currentUrl.searchParams.get("offset")).toBe("1");
    await expect(queryInput).toHaveValue(SMOKE_DONOR_LOOKUP_QUERY);
    await expect(page.getByTestId("donor-result-count")).toHaveText(SMOKE_DONOR_LOOKUP_SECOND_PAGE_RESULT_COUNT);
    await expect(page.getByTestId("donor-result-row")).toContainText(SMOKE_DONOR_LOOKUP_SECOND_CONTRIBUTOR_NAME);
    await pageLoadErrors.assertNoErrors();
  });

  test("/donors renders fixture-backed donor identity disclosure", async ({
    page
  }: {
    page: any;
  }) => {
    const pageLoadErrors = capturePageLoadErrors(page);

    await page.goto(`/donors?q=${SMOKE_DONOR_LOOKUP_QUERY}&by=name&limit=1&offset=0`);

    const stableUrl = page.url();
    const disclosure = page.getByTestId("donor-identity-disclosure");
    const disclosureSummary = page.getByLabel(
      `${SMOKE_DONOR_LOOKUP_SEED_CONTRIBUTOR_NAME}, ${SMOKE_DONOR_LOOKUP_COMBINED_COUNT_LABEL}`
    );
    await expect(disclosure).toBeVisible();
    await expect(disclosure).toHaveAttribute("open", "");
    await expect(disclosureSummary).toContainText(SMOKE_DONOR_LOOKUP_COMBINED_COUNT_LABEL);
    await expect(disclosureSummary).toContainText(SMOKE_DONOR_LOOKUP_CONFIDENCE_LABEL);

    const combinedRecords = page.getByTestId("donor-identity-underlying-record");
    await expect(combinedRecords).toHaveCount(2);
    await expect(combinedRecords.nth(0)).toContainText(SMOKE_DONOR_LOOKUP_COMBINED_CONTRIBUTOR_A);
    await expect(combinedRecords.nth(0)).toContainText(SMOKE_DONOR_LOOKUP_COMBINED_EMPLOYER_A);
    await expect(combinedRecords.nth(0)).toContainText(SMOKE_DONOR_LOOKUP_COMBINED_CITY_A);
    await expect(combinedRecords.nth(1)).toContainText(SMOKE_DONOR_LOOKUP_COMBINED_CONTRIBUTOR_B);
    await expect(combinedRecords.nth(1)).toContainText(SMOKE_DONOR_LOOKUP_COMBINED_CITY_B);
    await expect(page.getByTestId("donor-identity-combined-records")).not.toContainText(
      SMOKE_DONOR_LOOKUP_NOT_COMBINED_CONTRIBUTOR
    );

    const filingLinks = page.getByTestId("donor-identity-underlying-filing");
    await expect(filingLinks).toHaveCount(2);
    await expect(
      combinedRecords.nth(0).getByRole("link", {
        name: `Source filing for ${SMOKE_DONOR_LOOKUP_COMBINED_CONTRIBUTOR_A}`
      })
    ).toBeVisible();
    await expect(
      combinedRecords.nth(1).getByRole("link", {
        name: `Source filing for ${SMOKE_DONOR_LOOKUP_COMBINED_CONTRIBUTOR_B}`
      })
    ).toBeVisible();
    for (const filingLink of await filingLinks.all()) {
      const filingHref = await filingLink.getAttribute("href");
      expect(filingHref).toMatch(/^https:\/\/docquery\.fec\.gov\/cgi-bin\/fecimg\/\?\d+$/);
    }

    const notCombinedCandidates = page.getByTestId("donor-identity-not-combined-candidate");
    await expect(notCombinedCandidates).toHaveCount(1);
    await expect(notCombinedCandidates).toContainText(SMOKE_DONOR_LOOKUP_NOT_COMBINED_CONTRIBUTOR);
    await expect(notCombinedCandidates).not.toContainText(SMOKE_DONOR_LOOKUP_COMBINED_CONTRIBUTOR_A);
    await expect(
      notCombinedCandidates.getByRole("link", {
        name: `Source filing for ${SMOKE_DONOR_LOOKUP_NOT_COMBINED_CONTRIBUTOR}`
      })
    ).toBeVisible();
    await expect(page.getByTestId("donor-identity-correction-combined")).toBeDisabled();
    await expect(page.getByTestId("donor-identity-correction-candidate")).toBeDisabled();
    await expect(page.getByText("Correction submission is not yet available")).toHaveCount(2);

    await disclosureSummary.click();
    expect(page.url()).toBe(stableUrl);
    await pageLoadErrors.assertNoErrors();
  });

  test("/donors renders unavailable identity evidence states from unsafe fixture links", async ({
    page
  }: {
    page: any;
  }) => {
    const pageLoadErrors = capturePageLoadErrors(page);

    await page.goto(`/donors?q=${SMOKE_DONOR_LOOKUP_QUERY}&by=name&limit=1&offset=1`);

    await expect(page.getByTestId("donor-result-row")).toContainText(SMOKE_DONOR_LOOKUP_SECOND_CONTRIBUTOR_NAME);
    await expect(page.getByTestId("donor-identity-evidence-unavailable")).toBeVisible();
    await expect(page.getByTestId("donor-candidate-evidence-unavailable")).toBeVisible();
    await pageLoadErrors.assertNoErrors();
  });
});

test.describe("donor lookup smoke (live mode)", () => {
  test.skip(!SMOKE_USE_LIVE_API, "live-mode only — set SMOKE_USE_LIVE_API=1");

  test("/donors searches seeded donor activity and links to recipient person", async ({
    page
  }: {
    page: any;
  }) => {
    const cleanup = await seedLiveDonorLookupSmoke();
    const pageLoadErrors = capturePageLoadErrors(page);

    try {
      await page.goto("/donors");

      await expect(page.getByRole("heading", { name: SMOKE_DONOR_LOOKUP_HEADING })).toBeVisible();
      await expect(page.getByTestId("donor-scope-note")).toContainText(SMOKE_DONOR_LOOKUP_SCOPE_NOTE);
      await expect(page.getByTestId("donor-search-input")).toBeVisible();
      await expect(page.getByTestId("donor-search-by")).toBeVisible();
      await expect(page.getByTestId("donor-search-status")).toBeVisible();

      await page.getByTestId("donor-search-input").fill(SMOKE_DONOR_LOOKUP_QUERY);
      await page.getByTestId("donor-search-by").selectOption("name");
      await page.getByRole("button", { name: "Search" }).click();

      await expect(page).toHaveURL(/\/donors\?/);
      const currentUrl = new URL(page.url());
      expect(currentUrl.pathname).toBe("/donors");
      expect(currentUrl.searchParams.get("q")).toBe(SMOKE_DONOR_LOOKUP_QUERY);
      expect(currentUrl.searchParams.get("by")).toBe("name");

      await expect(page.getByTestId("donor-result-count")).toHaveText(SMOKE_DONOR_LOOKUP_RESULT_COUNT);
      const resultRow = page.getByTestId("donor-result-row").filter({
        hasText: SMOKE_DONOR_LOOKUP_SEED_CONTRIBUTOR_NAME
      });
      await expect(resultRow).toContainText(SMOKE_DONOR_LOOKUP_SEED_EMPLOYER);
      await expect(resultRow).toContainText(SMOKE_DONOR_LOOKUP_SEED_ZIP5);
      await expect(resultRow).toContainText(SMOKE_DONOR_LOOKUP_SEED_TOTAL_AMOUNT);
      await expect(resultRow).toContainText(SMOKE_DONOR_LOOKUP_RECIPIENT_NAME);

      await resultRow.getByRole("link", { name: SMOKE_DONOR_LOOKUP_RECIPIENT_NAME }).click();

      await expect(page).toHaveURL(`/person/${SMOKE_DONOR_LOOKUP_SEED_PERSON_ID}`);
      await expect(
        page.getByRole("heading", { level: 2, name: SMOKE_DONOR_LOOKUP_RECIPIENT_NAME, exact: true })
      ).toBeVisible();
      await pageLoadErrors.assertNoErrors();
    } finally {
      await cleanup();
    }
  });
});
