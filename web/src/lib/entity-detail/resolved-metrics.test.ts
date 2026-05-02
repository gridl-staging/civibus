import { describe, expect, it } from "vitest";
import type { EntityGraphRelationshipsResponse, ErMatchDecision } from "$lib/entity-detail/contract";
import type { DetailFactRow } from "$lib/entity-detail/presentation";
import { buildResolvedKeyMetrics, buildUnavailableKeyMetrics } from "$lib/entity-detail/presentation";

const SUBJECT_ENTITY_ID = "11111111-1111-4111-8111-111111111111";

describe("resolved and unavailable key metrics contracts", () => {
  it("buildResolvedKeyMetrics returns counts for identifiers, ER matches, and graph relationships total_count", () => {
    const identifierRows: DetailFactRow[] = [
      { label: "alpha_id", value: "A-1" },
      { label: "beta_id", value: "B-1" }
    ];
    const matches: ErMatchDecision[] = [
      {
        id: "22222222-2222-4222-8222-222222222222",
        entity_type: "person",
        entity_id_a: SUBJECT_ENTITY_ID,
        entity_id_b: "33333333-3333-4333-8333-333333333333",
        decision: "match",
        confidence: 0.98,
        decided_by: "splink_v1",
        decision_method: "probabilistic",
        match_evidence: { name_similarity: 0.99 },
        decided_at: "2026-03-19T00:00:00Z"
      }
    ];
    const relationships: EntityGraphRelationshipsResponse = {
      entity_type: "person",
      entity_id: SUBJECT_ENTITY_ID,
      neighbors: [
        {
          entity_type: "committee",
          entity_id: "44444444-4444-4444-8444-444444444444",
          name: "Committee XYZ",
          relationship_type: "AFFILIATED_WITH",
          direction: "outbound"
        }
      ],
      total_count: 7
    };

    expect(buildResolvedKeyMetrics(identifierRows, matches, relationships)).toEqual([
      { label: "Identifiers", value: "2" },
      { label: "ER matches", value: "1" },
      { label: "Graph relationships", value: "7" }
    ]);
  });

  it("buildUnavailableKeyMetrics returns identifier count and unavailable placeholders", () => {
    const identifierRows: DetailFactRow[] = [
      { label: "alpha_id", value: "A-1" },
      { label: "beta_id", value: "B-1" },
      { label: "gamma_id", value: "C-1" }
    ];

    expect(buildUnavailableKeyMetrics(identifierRows)).toEqual([
      { label: "Identifiers", value: "3" },
      { label: "ER matches", value: "Unavailable" },
      { label: "Graph relationships", value: "Unavailable" }
    ]);
  });
});
