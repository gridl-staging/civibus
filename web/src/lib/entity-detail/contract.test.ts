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
      current_office: null,
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

  it("allows older person payloads to omit current-office context", () => {
    const personPayloadWithoutCurrentOffice = {
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
      bio_text: null,
      bio_source_url: null,
      bio_license: null,
      bio_pulled_at: null
    };

    expect(() => assertPersonPayloadHasRequiredBioKeys(personPayloadWithoutCurrentOffice)).not.toThrow();
  });

  it("rejects malformed current-office context before page consumption", () => {
    const malformedCurrentOfficePayload = {
      id: PERSON_ID,
      canonical_name: "Jane Doe",
      bio_text: null,
      bio_source_url: null,
      bio_license: null,
      bio_pulled_at: null,
      current_office: {
        officeholding_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        office_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        office_name: null,
        office_level: "municipal",
        state: "NC"
      }
    };

    expect(() => assertPersonPayloadHasRequiredBioKeys(malformedCurrentOfficePayload)).toThrow(
      /current_office\.office_name must be a string/i
    );
  });

  // Stage 3 regression: the guard distinguishes an absent optional
  // current_office (accepted) from malformed core data by raising a typed,
  // adapter-mappable failure rather than a bare `Error`. The shared contract owns
  // the shape error; the server API layer owns adapting it to a route response.
  it("raises a typed adapter-mappable 502 failure for malformed core data, not a bare Error", () => {
    const validPayloadWithoutCurrentOffice = {
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
      bio_text: null,
      bio_source_url: null,
      bio_license: null,
      bio_pulled_at: null
    };

    expect(() =>
      assertPersonPayloadHasRequiredBioKeys(validPayloadWithoutCurrentOffice)
    ).not.toThrow();

    const malformedCorePayload = { ...validPayloadWithoutCurrentOffice, bio_text: 123 };

    let thrown: unknown;
    try {
      assertPersonPayloadHasRequiredBioKeys(malformedCorePayload);
    } catch (cause) {
      thrown = cause;
    }

    expect(thrown).toMatchObject({
      name: "PersonPayloadContractError",
      status: 502
    });
    expect((thrown as Error).constructor).not.toBe(Error);
  });

  // civibus-7qj: the Races panel consumes `candidacies`, guarded with the same
  // version-skew tolerance current_office has — omission is legal, malformed
  // presence is the typed 502-class contract failure.
  const VALID_PERSON_PAYLOAD_BASE = {
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
    bio_text: null,
    bio_source_url: null,
    bio_license: null,
    bio_pulled_at: null
  };

  const VALID_CANDIDACY_ROW = {
    candidacy_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    contest_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
    contest_name: "Test State U.S. Senate — 2026 General Election",
    election_date: "2026-11-03",
    election_type: "general",
    office_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    office_name: "Test Senator",
    office_level: "federal",
    party: "DEM",
    status: "qualified",
    incumbent_challenge: "I",
    fec_candidate_id: "S8ZZ00001"
  };

  it("allows older person payloads to omit the candidacies list", () => {
    expect(() => assertPersonPayloadHasRequiredBioKeys(VALID_PERSON_PAYLOAD_BASE)).not.toThrow();
  });

  it("accepts a well-formed candidacies list, including null optional facts", () => {
    const payload = {
      ...VALID_PERSON_PAYLOAD_BASE,
      candidacies: [
        VALID_CANDIDACY_ROW,
        {
          ...VALID_CANDIDACY_ROW,
          candidacy_id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
          election_date: null,
          party: null,
          status: null,
          incumbent_challenge: null,
          fec_candidate_id: null
        }
      ]
    };

    expect(() => assertPersonPayloadHasRequiredBioKeys(payload)).not.toThrow();
  });

  it("rejects a non-array candidacies value", () => {
    const payload = { ...VALID_PERSON_PAYLOAD_BASE, candidacies: { rows: [] } };

    expect(() => assertPersonPayloadHasRequiredBioKeys(payload)).toThrow(
      /candidacies must be an array/i
    );
  });

  it("rejects a candidacy row missing required string identity fields", () => {
    const payload = {
      ...VALID_PERSON_PAYLOAD_BASE,
      candidacies: [{ ...VALID_CANDIDACY_ROW, contest_id: null }]
    };

    expect(() => assertPersonPayloadHasRequiredBioKeys(payload)).toThrow(
      /candidacies\[0\]\.contest_id must be a string/i
    );
  });

  it("rejects non-string optional candidacy facts", () => {
    const payload = {
      ...VALID_PERSON_PAYLOAD_BASE,
      candidacies: [{ ...VALID_CANDIDACY_ROW, party: 7 }]
    };

    expect(() => assertPersonPayloadHasRequiredBioKeys(payload)).toThrow(
      /candidacies\[0\]\.party must be a string or null/i
    );
  });

  it("raises the typed 502-class failure for malformed candidacies, not a bare Error", () => {
    let thrown: unknown;
    try {
      assertPersonPayloadHasRequiredBioKeys({
        ...VALID_PERSON_PAYLOAD_BASE,
        candidacies: [{ ...VALID_CANDIDACY_ROW, contest_name: 42 }]
      });
    } catch (cause) {
      thrown = cause;
    }

    expect(thrown).toMatchObject({
      name: "PersonPayloadContractError",
      status: 502
    });
  });
});
