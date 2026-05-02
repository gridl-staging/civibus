import { expect, test } from "playwright/test";

import {
  SMOKE_ENTITY_PORTRAIT_IMAGE_TEST_ID,
  SMOKE_ENTITY_PORTRAIT_SILHOUETTE_TEST_ID,
  SMOKE_ROSTER_DURHAM_PERSON_CANONICAL_NAME,
  SMOKE_ROSTER_DURHAM_PERSON_ID,
  SMOKE_ROSTER_DURHAM_PORTRAIT_URL,
  SMOKE_ROSTER_NC_HOUSE_PERSON_CANONICAL_NAME,
  SMOKE_ROSTER_NC_HOUSE_PERSON_ID,
  SMOKE_ROSTER_NC_HOUSE_PORTRAIT_URL
} from "./fixtures";

test.describe("NC roster pilot person portraits", () => {
  test("/person/[id] for Durham roster member renders roster-sourced portrait image", async ({
    page
  }: {
    page: any;
  }) => {
    await page.goto(`/person/${SMOKE_ROSTER_DURHAM_PERSON_ID}`);

    await expect(
      page.getByRole("heading", { name: SMOKE_ROSTER_DURHAM_PERSON_CANONICAL_NAME })
    ).toBeVisible();
    const portrait = page.getByTestId(SMOKE_ENTITY_PORTRAIT_IMAGE_TEST_ID);
    await expect(portrait).toBeVisible();
    await expect(portrait).toHaveAttribute("src", SMOKE_ROSTER_DURHAM_PORTRAIT_URL);
    await expect(page.getByTestId(SMOKE_ENTITY_PORTRAIT_SILHOUETTE_TEST_ID)).toHaveCount(0);
  });

  test("/person/[id] for NC House roster member renders roster-sourced portrait image", async ({
    page
  }: {
    page: any;
  }) => {
    await page.goto(`/person/${SMOKE_ROSTER_NC_HOUSE_PERSON_ID}`);

    await expect(
      page.getByRole("heading", { name: SMOKE_ROSTER_NC_HOUSE_PERSON_CANONICAL_NAME })
    ).toBeVisible();
    const portrait = page.getByTestId(SMOKE_ENTITY_PORTRAIT_IMAGE_TEST_ID);
    await expect(portrait).toBeVisible();
    await expect(portrait).toHaveAttribute("src", SMOKE_ROSTER_NC_HOUSE_PORTRAIT_URL);
    await expect(page.getByTestId(SMOKE_ENTITY_PORTRAIT_SILHOUETTE_TEST_ID)).toHaveCount(0);
  });
});
