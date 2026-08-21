/**
 * Person -> contest click-through via the Races panel (civibus-i80).
 *
 * The aug21 person->race lane (batman/aug21_person_race, civibus-x8b/7qj)
 * added `candidacies` to the person payload and a Races panel to the person
 * page: section data-testid="person-races", one data-testid="person-race-row"
 * per candidacy, contest name linking /contest/[id] (person_detail.md, Layout
 * item 5). No fixture modeled a person WITH candidacies, so the panel never
 * rendered in fixture mode and the reverse leg of the race-discovery chain
 * had no click-through proof.
 *
 * EXPECTED RED BEFORE batman/aug21_person_race MERGES: this lane's tree does
 * not contain the Races panel UI, so the person-races visibility assertion
 * fails here by design (recorded 2026-08-21: "person-races ... element(s) not
 * found" on batman/aug21_gate_reliability alone). Proven green on a scratch
 * merge with batman/aug21_person_race before commit — see civibus-i80.
 */
import { expect, test } from "playwright/test";
import type { Page } from "playwright";

import {
  SMOKE_CONTEST_ID,
  SMOKE_CONTEST_NAME,
  SMOKE_PERSON_NO_PORTRAIT_ID
} from "./fixtures";
import { capturePageLoadErrors } from "./smoke-helpers";

test("person Races panel links to the contest its candidacy names", async ({
  page
}: {
  page: Page;
}) => {
  const pageLoadErrors = capturePageLoadErrors(page);
  await page.goto(`/person/${SMOKE_PERSON_NO_PORTRAIT_ID}`);

  const racesPanel = page.getByTestId("person-races");
  await expect(racesPanel).toBeVisible();
  const firstRaceRow = racesPanel.getByTestId("person-race-row").first();
  const contestLink = firstRaceRow.getByRole("link", { name: SMOKE_CONTEST_NAME, exact: true });
  await expect(contestLink).toHaveAttribute("href", `/contest/${SMOKE_CONTEST_ID}`);
  const contestLinkText = ((await contestLink.textContent()) ?? "").trim();
  await contestLink.click();

  // The same link-text == destination-heading invariant the deploy gate uses
  // elsewhere: the row must land on the contest it named.
  await expect(page).toHaveURL(`/contest/${SMOKE_CONTEST_ID}`);
  await expect(page.getByRole("heading", { name: contestLinkText, exact: true })).toBeVisible();
  await pageLoadErrors.assertNoErrors();
});
