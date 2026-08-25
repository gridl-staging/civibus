import type { ContestDetailResponse } from "$lib/civic-detail/contract";
import { createEmptyFeatureCollection } from "$lib/server/api/civic-geometry";
import { render } from "svelte/server";
import { expect, it, vi } from "vitest";
import {
  buildSmokeCongressionalDistrictGeometry,
  smokeFixtures
} from "../../../../tests/smoke/fixture-data";
import type { PageData } from "./$types";
import ContestPage from "./+page.svelte";

vi.mock("$env/dynamic/public", () => ({
  env: {
    PUBLIC_ORIGIN: "https://civibus.test"
  }
}));

vi.mock("$app/stores", () => ({
  page: {
    subscribe(run: (value: { url: URL }) => void): () => void {
      run({ url: new URL(`https://civibus.test/contest/${smokeFixtures.contest.detail.id}`) });
      return () => {};
    }
  },
  navigating: {
    subscribe(run: (value: null) => void): () => void {
      run(null);
      return () => {};
    }
  }
}));

it("shows and highlights the selected congressional district on its contest page", () => {
  const contest = smokeFixtures.contest.detail as unknown as ContestDetailResponse;
  const congressionalDistrictGeometry = buildSmokeCongressionalDistrictGeometry();
  const data = {
    contest,
    geometryByLevel: {
      state: createEmptyFeatureCollection(),
      county: createEmptyFeatureCollection(),
      congressional_district: congressionalDistrictGeometry
    },
    contestCandidateMoney: smokeFixtures.contest.candidateMoney,
    contestSelectedCycle: smokeFixtures.contest.candidateMoney.selected_cycle
  } as unknown as PageData;

  const rendered = render(ContestPage, { props: { data } });

  expect(rendered.body).toContain("District map context");
  expect(rendered.body).toContain('data-layer-id="nc_congressional_districts"');
  expect(rendered.body).toContain(`data-feature-id="${contest.electoral_division_id}"`);
  expect(rendered.body).toMatch(/class="[^"]*region-map__feature--highlighted[^"]*"/);
});
