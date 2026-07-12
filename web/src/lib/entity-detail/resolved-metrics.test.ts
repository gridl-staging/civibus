import { describe, expect, it } from "vitest";
import type { DetailFactRow } from "$lib/entity-detail/presentation";
import { buildIdentifierKeyMetrics } from "$lib/entity-detail/presentation";

describe("public key metrics contract", () => {
  it("returns only identifier counts for public entity detail pages", () => {
    const identifierRows: DetailFactRow[] = [
      { label: "alpha_id", value: "A-1" },
      { label: "beta_id", value: "B-1" }
    ];

    expect(buildIdentifierKeyMetrics(identifierRows)).toEqual([
      { label: "Identifiers", value: "2" }
    ]);
  });
});
