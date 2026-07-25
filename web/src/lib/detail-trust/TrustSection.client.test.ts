// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { mount, unmount } from "svelte";
import { buildTrustSection } from "./presentation";
import TrustSection from "./TrustSection.svelte";
import {
  COMMITTEE_CANONICAL_DATA_WITH_DUPLICATE_FEC_SOURCES,
  COMMITTEE_CANONICAL_DATA_WITH_SAME_KEY_DISTINCT_SOURCES
} from "$lib/campaign-finance-detail/route-render.test-fixtures";

let mountedComponents: Record<string, unknown>[] = [];

afterEach(async () => {
  for (const component of mountedComponents) {
    await unmount(component);
  }
  mountedComponents = [];
  document.body.innerHTML = "";
});

function mountTrustSectionWithRows(
  sources: typeof COMMITTEE_CANONICAL_DATA_WITH_DUPLICATE_FEC_SOURCES.detail.sources
) {
  const target = document.createElement("div");
  document.body.append(target);
  const trustSection = buildTrustSection(sources);

  const component = mount(TrustSection, {
    target,
    props: {
      trustSection
    }
  });
  mountedComponents.push(component as Record<string, unknown>);

  return { target, trustSection };
}

describe("TrustSection client keyed-row regression (prod run 30159110547)", () => {
  it("mounts byte-identical duplicate FEC provenance rows without a Svelte duplicate-key throw", async () => {
    expect(COMMITTEE_CANONICAL_DATA_WITH_DUPLICATE_FEC_SOURCES.detail.sources).toHaveLength(2);

    const { target, trustSection } = mountTrustSectionWithRows(
      COMMITTEE_CANONICAL_DATA_WITH_DUPLICATE_FEC_SOURCES.detail.sources
    );

    expect(trustSection.rows.map((row) => row.sourceRecordKey)).toEqual(
      expect.arrayContaining(["cm:2026:C00718866"])
    );
    expect(target.textContent).toContain("Source record ID: cm:2026:C00718866");
  });

  it("preserves distinct same-record-key provenance rows while keeping Svelte keys collision-free", async () => {
    const { target, trustSection } = mountTrustSectionWithRows(
      COMMITTEE_CANONICAL_DATA_WITH_SAME_KEY_DISTINCT_SOURCES.detail.sources
    );

    expect(trustSection.rows).toHaveLength(2);
    expect(trustSection.rows.map((row) => row.recordUrl)).toEqual([
      "https://www.fec.gov/data/committee/C00718866/",
      "https://www.fec.gov/data/committee/C00718866/?amended=1"
    ]);
    expect(target.innerHTML).toContain('href="https://www.fec.gov/data/committee/C00718866/"');
    expect(target.innerHTML).toContain('href="https://www.fec.gov/data/committee/C00718866/?amended=1"');
    expect(target.textContent).toContain("FEC (amended filing)");
  });
});
