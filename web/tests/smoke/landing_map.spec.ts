import { expect, test } from "playwright/test";

import {
  SMOKE_HOME_DESCRIPTION,
  SMOKE_HOME_TITLE,
  SMOKE_LANDING_MAP_HEADING,
  SMOKE_LANDING_MAP_SUPPORTED_STATE_CODE,
  SMOKE_LANDING_MAP_SUPPORTED_STATE_NAME,
  SMOKE_LANDING_MAP_UNSUPPORTED_LABEL,
  SMOKE_LANDING_MAP_UNSUPPORTED_STATE_NAME,
  SMOKE_LANDING_MAP_WARNING_TEXT
} from "./fixtures";
import { assertSeoHead } from "./smoke-helpers";

test.describe("landing map smoke", () => {
  test("/ renders supported state link, disabled unsupported region, and warning copy", async ({
    page
  }: {
    page: any;
  }) => {
    await page.goto("/");

    await assertSeoHead(page, {
      title: SMOKE_HOME_TITLE,
      description: SMOKE_HOME_DESCRIPTION,
      ogType: "website",
      jsonLdCount: 1
    });

    await expect(
      page.getByRole("heading", { name: SMOKE_LANDING_MAP_HEADING })
    ).toBeVisible();

    const supportedLink = page.getByRole("link", {
      name: SMOKE_LANDING_MAP_SUPPORTED_STATE_NAME
    });
    await expect(supportedLink).toBeVisible();
    await expect(supportedLink).toHaveAttribute(
      "href",
      `/state/${SMOKE_LANDING_MAP_SUPPORTED_STATE_CODE}`
    );

    await expect(
      page.getByRole("link", { name: SMOKE_LANDING_MAP_UNSUPPORTED_STATE_NAME })
    ).toHaveCount(0);

    const unsupportedRegion = page.getByText(
      `${SMOKE_LANDING_MAP_UNSUPPORTED_STATE_NAME} — ${SMOKE_LANDING_MAP_UNSUPPORTED_LABEL}`
    );
    await expect(unsupportedRegion).toBeVisible();
    await expect(unsupportedRegion).toHaveAttribute("aria-disabled", "true");

    await expect(page.getByText(SMOKE_LANDING_MAP_WARNING_TEXT)).toBeVisible();
  });
});
