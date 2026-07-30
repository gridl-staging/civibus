import { describe, expect, it } from "vitest";
import { hasCanonicalCandidateSlug } from "$lib/campaign-finance-detail/contract";
import { CANDIDATE_ROUTE_INDEXABILITY } from "./candidate_indexability";

const SPECIMENS = [
  {
    label: "in-window official total",
    item: { has_official_total: true },
    expectedIndexable: true,
    expectedRobots: null
  },
  {
    label: "out-of-cycle official total",
    item: { has_official_total: true },
    expectedIndexable: true,
    expectedRobots: null
  },
  {
    label: "loaded zero without official total",
    item: { has_official_total: false },
    expectedIndexable: false,
    expectedRobots: "noindex"
  },
  {
    label: "not loaded without official total",
    item: { has_official_total: false },
    expectedIndexable: false,
    expectedRobots: "noindex"
  }
] as const;

describe("CANDIDATE_ROUTE_INDEXABILITY", () => {
  it.each(SPECIMENS)(
    "returns the exact indexability and robots answers for $label",
    ({ item, expectedIndexable, expectedRobots }) => {
      expect(CANDIDATE_ROUTE_INDEXABILITY.isIndexable(item)).toBe(expectedIndexable);
      expect(CANDIDATE_ROUTE_INDEXABILITY.robots(item)).toBe(expectedRobots);
    }
  );

  it.each(SPECIMENS)("keeps sitemap and robots decisions in agreement for $label", ({ item }) => {
    const canonicalCandidate = {
      id: "11111111-1111-4111-8111-111111111111",
      slug: "canonical-candidate",
      slug_is_unique: true,
      identity_is_safe: true,
      ...item
    };
    const sitemapEligible =
      hasCanonicalCandidateSlug(canonicalCandidate) &&
      CANDIDATE_ROUTE_INDEXABILITY.isIndexable(canonicalCandidate);

    expect(hasCanonicalCandidateSlug(canonicalCandidate)).toBe(true);
    expect(CANDIDATE_ROUTE_INDEXABILITY.robots(canonicalCandidate) === null).toBe(
      sitemapEligible
    );
  });
});
