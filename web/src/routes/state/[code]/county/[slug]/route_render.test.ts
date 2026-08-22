import { describe, expect, it } from "vitest";
import { render } from "svelte/server";
import { buildMapLayerVisibilityDefaults, type CivicGeometryLevel } from "$lib/config/app";
import type { CountySummaryLinkedCandidate } from "$lib/campaign-finance-detail/contract";
import { buildTrustSection } from "$lib/detail-trust/presentation";
import type { CivicGeometryFeatureCollection } from "$lib/server/api/civic-geometry";
import CountyPage from "./+page.svelte";

function emptyFeatureCollection(): CivicGeometryFeatureCollection {
  return { type: "FeatureCollection", features: [] };
}

function countyPageData(topLinkedCandidates: CountySummaryLinkedCandidate[]) {
  const geometryByLevel: Record<CivicGeometryLevel, CivicGeometryFeatureCollection> = {
    state: emptyFeatureCollection(),
    county: emptyFeatureCollection(),
    congressional_district: emptyFeatureCollection()
  };

  return {
    stateCode: "NC",
    countySlug: "wake",
    countyName: "Wake",
    pageLevel: "county" as const,
    geometryByLevel,
    layerVisibilityDefaults: buildMapLayerVisibilityDefaults("county"),
    donor_total_cents: 12345,
    transaction_count: 2,
    top_recipient_committees: [
      {
        committee_id: "11111111-1111-4111-8111-111111111111",
        committee_name: "Committee A",
        donor_total_cents: 12000,
        transaction_count: 2
      }
    ],
    top_linked_candidates: topLinkedCandidates,
    trustSection: buildTrustSection([], { includeJurisdictionFreshnessNote: true })
  };
}

function linkedCandidate(
  overrides: Partial<CountySummaryLinkedCandidate> = {}
): CountySummaryLinkedCandidate {
  return {
    candidate_id: "22222222-2222-4222-8222-222222222222",
    candidate_name: "Jordan Candidate",
    donor_total_cents: 12000,
    transaction_count: 2,
    identity_is_safe: true,
    ...overrides
  };
}

// Linked-candidate names come from cf.candidate.name — the raw FEC filing
// string. These tests pin the identity-gated owner (formatCandidatePublicName)
// on the rendered name. Specimens are ALL-CAPS on purpose: an already-cased
// name passes through the formatter unchanged and can never prove formatting
// happened (the documented mixed-case-fixture vacuous pass).
describe("/state/[code]/county/[slug] route rendering", () => {
  it("formats an identity-safe ALL-CAPS linked-candidate name through the shared owner", () => {
    const rendered = render(CountyPage, {
      props: {
        data: countyPageData([linkedCandidate({ candidate_name: "OSSOFF, T. JONATHAN" })])
      } as never
    });

    expect(rendered.body).toContain("<strong>Ossoff, T. Jonathan</strong>");
    expect(rendered.body).not.toContain("OSSOFF, T. JONATHAN");
  });

  it("renders an identity-unsafe linked-candidate name as the raw filed string", () => {
    const rendered = render(CountyPage, {
      props: {
        data: countyPageData([
          linkedCandidate({
            // Address-like FEC source string; digits mark it identity-unsafe.
            candidate_name: "212 MAIN AVE W. JOHN, RODNEY",
            identity_is_safe: false
          })
        ])
      } as never
    });

    expect(rendered.body).toContain("<strong>212 MAIN AVE W. JOHN, RODNEY</strong>");
    expect(rendered.body).not.toContain("212 Main Ave W. John, Rodney");
  });

  it("fails closed when the runtime identity flag is not a boolean", () => {
    const malformedCandidate = {
      ...linkedCandidate({ candidate_name: "212 MAIN AVE W. JOHN, RODNEY" }),
      identity_is_safe: "false"
    } as unknown as CountySummaryLinkedCandidate;

    const rendered = render(CountyPage, {
      props: { data: countyPageData([malformedCandidate]) } as never
    });

    expect(rendered.body).toContain("<strong>212 MAIN AVE W. JOHN, RODNEY</strong>");
    expect(rendered.body).not.toContain("212 Main Ave W. John, Rodney");
  });
});
