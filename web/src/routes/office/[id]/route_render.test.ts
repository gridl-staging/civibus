import type { OfficeDetailResponse } from "$lib/civic-detail/contract";
import { createEmptyFeatureCollection } from "$lib/server/api/civic-geometry";
import { render } from "svelte/server";
import { expect, it, vi } from "vitest";
import {
  buildSmokeCongressionalDistrictGeometry,
  smokeFixtures
} from "../../../../tests/smoke/fixture-data";
import type { PageData } from "./$types";
import OfficePage from "./+page.svelte";

vi.mock("$env/dynamic/public", () => ({
  env: {
    PUBLIC_ORIGIN: "https://civibus.test"
  }
}));

vi.mock("$app/stores", () => ({
  page: {
    subscribe(run: (value: { url: URL }) => void): () => void {
      run({ url: new URL(`https://civibus.test/office/${smokeFixtures.office.detail.id}`) });
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

it("shows and highlights the selected congressional district on its office page", () => {
  const office = smokeFixtures.office.detail as unknown as OfficeDetailResponse;
  const congressionalDistrictGeometry = buildSmokeCongressionalDistrictGeometry();
  const data = {
    office,
    geometryByLevel: {
      state: createEmptyFeatureCollection(),
      county: createEmptyFeatureCollection(),
      congressional_district: congressionalDistrictGeometry
    }
  } as unknown as PageData;

  const rendered = render(OfficePage, { props: { data } });

  expect(rendered.body).toContain("District map context");
  expect(rendered.body).toContain('data-layer-id="nc_congressional_districts"');
  expect(rendered.body).toContain(
    `data-feature-id="${office.selected_electoral_division_id}"`
  );
  expect(rendered.body).toMatch(/class="[^"]*region-map__feature--highlighted[^"]*"/);
});
