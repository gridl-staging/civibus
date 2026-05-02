import { describe, expect, it } from "vitest";
import {
  assertPersonPayloadHasRequiredBioKeys,
  buildEntityDetailPath,
  buildEntityErMatchesPath,
  buildEntityGraphRelationshipsPath,
  buildEntityRouteHref,
  classifyGraphNeighborRoute,
  type PersonDetailResponse,
  type Stage4EntityType
} from "./contract";

const PERSON_ID = "11111111-1111-4111-8111-111111111111";
const ORG_ID = "22222222-2222-4222-8222-222222222222";

describe("entity detail contract", () => {
  it("builds Stage 4 person detail/ER/graph paths", () => {
    const entityType: Stage4EntityType = "person";

    expect(buildEntityDetailPath(entityType, PERSON_ID)).toBe(`/v1/person/${PERSON_ID}`);
    expect(buildEntityErMatchesPath(entityType, PERSON_ID)).toBe(`/v1/er/person/${PERSON_ID}/matches`);
    expect(buildEntityGraphRelationshipsPath(entityType, PERSON_ID)).toBe(
      `/v1/graph/person/${PERSON_ID}/relationships`
    );
  });

  it("builds org detail with organization ER mismatch and org graph mismatch", () => {
    const entityType: Stage4EntityType = "org";

    expect(buildEntityDetailPath(entityType, ORG_ID)).toBe(`/v1/org/${ORG_ID}`);
    expect(buildEntityErMatchesPath(entityType, ORG_ID)).toBe(`/v1/er/organization/${ORG_ID}/matches`);
    expect(buildEntityGraphRelationshipsPath(entityType, ORG_ID)).toBe(
      `/v1/graph/org/${ORG_ID}/relationships`
    );
  });

  it("classifies person/org/committee/candidate graph neighbors as routable", () => {
    expect(classifyGraphNeighborRoute({ entity_type: "person", entity_id: PERSON_ID })).toEqual({
      href: `/person/${PERSON_ID}`,
      isRoutable: true
    });
    expect(classifyGraphNeighborRoute({ entity_type: "org", entity_id: ORG_ID })).toEqual({
      href: `/org/${ORG_ID}`,
      isRoutable: true
    });
    expect(classifyGraphNeighborRoute({ entity_type: "committee", entity_id: ORG_ID })).toEqual({
      href: `/committee/${ORG_ID}`,
      isRoutable: true
    });
    expect(classifyGraphNeighborRoute({ entity_type: "candidate", entity_id: ORG_ID })).toEqual({
      href: `/candidate/${ORG_ID}`,
      isRoutable: true
    });
  });

  it("marks unsupported graph neighbor entity types as metadata-only", () => {
    expect(classifyGraphNeighborRoute({ entity_type: "filing", entity_id: ORG_ID })).toEqual({
      href: null,
      isRoutable: false
    });
  });

  it("encodes route and API path segments before interpolation", () => {
    const maliciousId = "../search?entity_type=org";

    expect(buildEntityRouteHref("person", maliciousId)).toBe("/person/..%2Fsearch%3Fentity_type%3Dorg");
    expect(buildEntityDetailPath("person", maliciousId)).toBe(
      "/v1/person/..%2Fsearch%3Fentity_type%3Dorg"
    );
    expect(buildEntityErMatchesPath("org", maliciousId)).toBe(
      "/v1/er/organization/..%2Fsearch%3Fentity_type%3Dorg/matches"
    );
    expect(buildEntityGraphRelationshipsPath("org", maliciousId)).toBe(
      "/v1/graph/org/..%2Fsearch%3Fentity_type%3Dorg/relationships"
    );
  });

  it("enforces runtime person payload bio attribution keys as required-nullable", () => {
    const personPayloadWithoutBioKeys = {
      id: PERSON_ID,
      canonical_name: "Jane Doe",
      name_variants: [],
      first_name: "Jane",
      middle_name: null,
      last_name: "Doe",
      suffix: null,
      date_of_birth: null,
      year_of_birth: 1980,
      identifiers: {},
      primary_address_id: null,
      er_cluster_id: null,
      er_confidence: null,
      portrait: null,
      sources: []
    };

    expect(() => assertPersonPayloadHasRequiredBioKeys(personPayloadWithoutBioKeys)).toThrow(
      /bio_text|bio_source_url|bio_license|bio_pulled_at/
    );

    const personPayloadWithNullableBioKeys: PersonDetailResponse = {
      ...personPayloadWithoutBioKeys,
      bio_text: null,
      bio_source_url: null,
      bio_license: null,
      bio_pulled_at: null
    };

    expect(() => assertPersonPayloadHasRequiredBioKeys(personPayloadWithNullableBioKeys)).not.toThrow();
  });
});
