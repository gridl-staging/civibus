import { expect, test } from "playwright/test";

import {
  seedLiveSearchOfficeholderSmoke,
  SMOKE_SEARCH_LIVE_CONTEXT_LINE,
  SMOKE_SEARCH_LIVE_PERSON_NAME,
  SMOKE_SEARCH_LIVE_QUERY,
  SMOKE_USE_LIVE_API
} from "./fixtures";
import { capturePageLoadErrors } from "./smoke-helpers";

test.describe("/search officeholder ranking smoke (live mode)", () => {
  test.skip(!SMOKE_USE_LIVE_API, "live-mode only — set SMOKE_USE_LIVE_API=1");

  test("/search ranks the current federal officeholder person before a same-name committee", async ({
    page
  }: {
    page: any;
  }) => {
    const cleanup = await seedLiveSearchOfficeholderSmoke();
    const pageLoadErrors = capturePageLoadErrors(page);

    try {
      await page.goto(`/search?q=${encodeURIComponent(SMOKE_SEARCH_LIVE_QUERY)}`);

      await expect(page.getByRole("heading", { name: "Search" })).toBeVisible();

      const resultItems = page.getByTestId("search-results-region").getByRole("listitem");
      await expect(resultItems.first()).toBeVisible();

      const firstResult = resultItems.nth(0);
      await expect(firstResult.getByRole("link", { name: SMOKE_SEARCH_LIVE_PERSON_NAME })).toBeVisible();
      await expect(firstResult.getByText("Person", { exact: true })).toBeVisible();
      await expect(firstResult.getByText(SMOKE_SEARCH_LIVE_CONTEXT_LINE)).toBeVisible();

      const committeeResults = resultItems.filter({ hasText: "Committee" });
      await expect(committeeResults.first()).toBeVisible();
      await expect(committeeResults.first().getByRole("link", { name: SMOKE_SEARCH_LIVE_PERSON_NAME })).toBeVisible();

      await pageLoadErrors.assertNoErrors();
    } finally {
      await cleanup();
    }
  });
});
