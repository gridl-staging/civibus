import { expect, test } from "playwright/test";
import type { Page, Request } from "playwright";

import {
  SMOKE_PUBLIC_API_CSV_HEADER,
  SMOKE_PUBLIC_API_ENDPOINTS,
  SMOKE_PUBLIC_API_FOOTER_LINK,
  SMOKE_PUBLIC_API_HEADING,
  SMOKE_PUBLIC_API_MIGRATION_HEADING,
  SMOKE_PUBLIC_API_REFERENCE_LINKS,
  SMOKE_PUBLIC_API_ROUTE_PATH,
  SMOKE_PUBLIC_API_SAMPLE_JSON_VALUE
} from "./fixtures";

test.describe("public API smoke", () => {
  test("renders the static developers reference without live data", async ({ page }: { page: Page }) => {
    const unexpectedApiRequests: string[] = [];
    page.on("request", (networkRequest: Request) => {
      const requestUrl = new URL(networkRequest.url());
      if (requestUrl.pathname.startsWith("/api/")) {
        unexpectedApiRequests.push(`${networkRequest.method()} ${requestUrl.pathname}`);
      }
    });

    await page.goto("/developers");

    const main = page.getByRole("main");
    await expect(main.getByRole("heading", { name: SMOKE_PUBLIC_API_HEADING })).toBeVisible();

    for (const endpoint of SMOKE_PUBLIC_API_ENDPOINTS) {
      await expect(main.getByRole("heading", { name: endpoint, exact: true })).toBeVisible();
    }

    await expect(main.getByRole("heading", { name: SMOKE_PUBLIC_API_MIGRATION_HEADING })).toBeVisible();
    await expect(main.getByText(SMOKE_PUBLIC_API_SAMPLE_JSON_VALUE)).toBeVisible();
    await expect(main.getByText(SMOKE_PUBLIC_API_CSV_HEADER)).toBeVisible();

    for (const referenceLink of SMOKE_PUBLIC_API_REFERENCE_LINKS) {
      await expect(main.getByRole("link", { name: referenceLink })).toHaveAttribute("href", referenceLink);
    }

    await expect(
      page.getByRole("contentinfo").getByRole("link", { name: SMOKE_PUBLIC_API_FOOTER_LINK, exact: true })
    ).toHaveAttribute("href", SMOKE_PUBLIC_API_ROUTE_PATH);

    expect(unexpectedApiRequests).toEqual([]);
  });
});
