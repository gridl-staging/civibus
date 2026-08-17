// @vitest-environment jsdom
import "$lib/client_test_environment";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mount, unmount } from "svelte";
import type { EntityDetailPageBundle } from "$lib/server/api/entity-detail";
import type { PersonCandidateFinanceSection } from "$lib/server/api/campaign-finance-detail";
import DetailPage from "./DetailPage.svelte";
import { buildPersonDetailFixture } from "./detail_page_test_fixtures";

let mountedComponents: Record<string, unknown>[] = [];

/**
 * A linked finance section whose every deferred sub-resource rejects, so each
 * degradable section boundary in DetailPage renders its `{:catch}` fallback.
 */
function buildRejectedFinanceSection(): PersonCandidateFinanceSection {
  const rejected = () => Promise.reject(new Error("section resource unavailable"));
  return {
    candidate: {
      id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
      name: "Candidate One",
      slug: "candidate-one",
      slug_is_unique: true,
      identity_is_safe: true
    },
    summary: rejected(),
    ieSummary: rejected(),
    ieTransactions: rejected(),
    donorVendorTransactions: rejected()
  } as unknown as PersonCandidateFinanceSection;
}

afterEach(async () => {
  for (const component of mountedComponents) {
    await unmount(component);
  }
  mountedComponents = [];
  document.body.innerHTML = "";
});

describe("entity detail page client rendering", () => {
  it("renders the labeled finance fallback while identity and bio remain visible", async () => {
    const target = document.createElement("div");
    document.body.append(target);
    const data: EntityDetailPageBundle = {
      entityType: "person",
      detail: buildPersonDetailFixture({
        bio_text: "Jane Doe is serving her third term in office.",
        bio_source_url: "https://www.ncleg.gov/Members/Biography/H/57",
        bio_license: "licensed",
        bio_pulled_at: "2026-04-29T14:30:00Z"
      }),
      personFinanceSections: Promise.reject(new Error("finance sections unavailable"))
    };

    const component = mount(DetailPage, { target, props: { data } });
    mountedComponents.push(component as Record<string, unknown>);

    const unavailableCopy = "Campaign-finance sections are temporarily unavailable.";
    await vi.waitFor(() => expect(target.textContent).toContain(unavailableCopy));
    const unavailableNotice = Array.from(target.querySelectorAll("p")).find(
      (notice) => notice.textContent === unavailableCopy
    );

    expect(unavailableNotice?.getAttribute("data-testid")).toBe("person-finance-unavailable");
    expect(target.textContent).toContain("Jane Doe");
    expect(target.textContent).toContain("Jane Doe is serving her third term in office.");
  });

  it("renders each spec-owned section fallback while identity and bio stay visible", async () => {
    const target = document.createElement("div");
    document.body.append(target);
    const data: EntityDetailPageBundle = {
      entityType: "person",
      detail: buildPersonDetailFixture({
        bio_text: "Jane Doe is serving her third term in office.",
        bio_source_url: "https://www.ncleg.gov/Members/Biography/H/57",
        bio_license: "licensed",
        bio_pulled_at: "2026-04-29T14:30:00Z"
      }),
      // personMoneyHeadline omitted (null) so the page-wide money-at-glance
      // summary renders and its rejected summary drives the money-summary catch.
      personFinanceSections: Promise.resolve([buildRejectedFinanceSection()]),
      personContributionInsights: Promise.reject(new Error("insights unavailable")),
      personTopDonors: Promise.resolve([]),
      personTopEmployers: Promise.resolve([])
    };

    const component = mount(DetailPage, { target, props: { data } });
    mountedComponents.push(component as Record<string, unknown>);

    const expectedFallbacks: Record<string, string> = {
      "person-money-summary-unavailable": "Selected-cycle money summary is temporarily unavailable.",
      "person-insights-unavailable": "Contribution insights are temporarily unavailable.",
      "person-linked-committees-unavailable": "Linked committees are temporarily unavailable.",
      "person-donor-vendor-unavailable": "Donor/vendor transactions are temporarily unavailable.",
      "person-outside-spending-unavailable": "Outside-spending data is temporarily unavailable."
    };

    for (const [testId, copy] of Object.entries(expectedFallbacks)) {
      await vi.waitFor(() => {
        const notice = target.querySelector(`[data-testid="${testId}"]`);
        expect(notice?.textContent).toBe(copy);
      });
    }

    expect(target.textContent).toContain("Jane Doe");
    expect(target.textContent).toContain("Jane Doe is serving her third term in office.");
  });
});
