import { describe, expect, it } from "vitest";
import {
  assertPersonPayloadHasRequiredBioKeys,
  buildEntityDetailPath,
  buildEntityRouteHref,
  type PersonDetailResponse,
  type Stage4EntityType
} from "./contract";

const PERSON_ID = "11111111-1111-4111-8111-111111111111";
const ORG_ID = "22222222-2222-4222-8222-222222222222";

describe("entity detail contract", () => {
  it("builds Stage 4 person detail paths", () => {
    const entityType: Stage4EntityType = "person";

    expect(buildEntityDetailPath(entityType, PERSON_ID)).toBe(`/v1/person/${PERSON_ID}`);
  });

  it("builds org detail paths", () => {
    const entityType: Stage4EntityType = "org";

    expect(buildEntityDetailPath(entityType, ORG_ID)).toBe(`/v1/org/${ORG_ID}`);
  });

  it("encodes route and API path segments before interpolation", () => {
    const maliciousId = "../search?entity_type=org";

    expect(buildEntityRouteHref("person", maliciousId)).toBe("/person/..%2Fsearch%3Fentity_type%3Dorg");
    expect(buildEntityDetailPath("person", maliciousId)).toBe(
      "/v1/person/..%2Fsearch%3Fentity_type%3Dorg"
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

  it("rejects non-string bio attribution values for required keys", () => {
    const malformedBioPayload = {
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
      sources: [],
      bio_text: "Biography text",
      bio_source_url: "https://example.org/bio",
      bio_license: "licensed",
      bio_pulled_at: 1234
    };

    expect(() => assertPersonPayloadHasRequiredBioKeys(malformedBioPayload)).toThrow(
      /bio keys must be string or null/i
    );
  });
});
