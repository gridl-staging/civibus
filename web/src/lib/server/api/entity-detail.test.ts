import { ApiResponseError } from "$lib/server/api/client";
import { describe, expect, it, vi } from "vitest";
import { fetchEntityDetailBundle } from "./entity-detail";
import type { ApiClient } from "./client";

const PERSON_ID = "11111111-1111-4111-8111-111111111111";
const ORG_ID = "22222222-2222-4222-8222-222222222222";

const PERSON_DETAIL = {
  id: PERSON_ID,
  canonical_name: "Jane Doe",
  name_variants: ["J. Doe"],
  first_name: "Jane",
  middle_name: null,
  last_name: "Doe",
  suffix: null,
  date_of_birth: null,
  year_of_birth: 1980,
  bio_text: null,
  bio_source_url: null,
  bio_license: null,
  bio_pulled_at: null,
  identifiers: { fec_candidate_id: "H0NC01001" },
  occupation: "Attorney",
  education: "State University",
  primary_address_id: null,
  er_cluster_id: null,
  er_confidence: null,
  portrait: {
    status: "active",
    rights_status: "licensed",
    source_image_url: "https://images.example.org/jane-doe.jpg",
    mime_type: "image/jpeg",
    width_px: 640,
    height_px: 480
  },
  sources: [
    {
      domain: "campaign_finance",
      jurisdiction: "federal/fec",
      data_source_name: "FEC",
      data_source_url: "https://www.fec.gov",
      source_record_key: "person-1",
      record_url: "https://example.org/person-1",
      pull_date: "2026-03-19T00:00:00Z"
    }
  ]
};

const ORG_DETAIL = {
  id: ORG_ID,
  canonical_name: "Civibus Action Org",
  name_variants: [],
  org_type: "pac",
  identifiers: { fec_committee_id: "C12345678" },
  registered_state: "NC",
  formation_date: "2014-05-01",
  dissolution_date: null,
  primary_address_id: null,
  er_cluster_id: null,
  er_confidence: 0.91,
  sources: [
    {
      domain: "campaign_finance",
      jurisdiction: "federal/fec",
      data_source_name: "FEC",
      data_source_url: "https://www.fec.gov",
      source_record_key: "org-1",
      record_url: "https://example.org/org-1",
      pull_date: "2026-03-19T00:00:00Z"
    }
  ]
};

describe("fetchEntityDetailBundle", () => {
  it("rejects person payloads that omit required nullable bio keys before page consumption", async () => {
    const malformedPersonPayload = {
      id: PERSON_ID,
      canonical_name: "Jane Doe",
      name_variants: ["J. Doe"],
      first_name: "Jane",
      middle_name: null,
      last_name: "Doe",
      suffix: null,
      date_of_birth: null,
      year_of_birth: 1980,
      identifiers: { fec_candidate_id: "H0NC01001" },
      primary_address_id: null,
      er_cluster_id: null,
      er_confidence: null,
      portrait: null,
      sources: []
    };
    const requestJson = vi.fn(async () => malformedPersonPayload);

    await expect(
      fetchEntityDetailBundle(
        { requestJson: requestJson as ApiClient["requestJson"] },
        { entityType: "person", id: PERSON_ID }
      )
    ).rejects.toThrow(/missing required bio keys/i);
  });

  it("rejects person payloads with malformed required bio attribution values", async () => {
    const requestJson = vi.fn(async () => ({
      ...PERSON_DETAIL,
      bio_pulled_at: 1714401000
    }));

    await expect(
      fetchEntityDetailBundle(
        { requestJson: requestJson as ApiClient["requestJson"] },
        { entityType: "person", id: PERSON_ID }
      )
    ).rejects.toThrow(/bio keys must be string or null/i);
  });

  it("returns only canonical person detail from the public detail bundle", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === `/v1/person/${PERSON_ID}`) {
        return PERSON_DETAIL;
      }
      throw new Error(`unexpected path: ${path}`);
    });

    const bundle = await fetchEntityDetailBundle(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { entityType: "person", id: PERSON_ID }
    );

    expect(bundle).toEqual({
      entityType: "person",
      detail: PERSON_DETAIL
    });
    expect("matches" in bundle).toBe(false);
    expect("relationships" in bundle).toBe(false);
    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([`/v1/person/${PERSON_ID}`]);
  });

  it("returns only canonical organization detail from the public detail bundle", async () => {
    const requestJson = vi.fn(async (path: string) => {
      if (path === `/v1/org/${ORG_ID}`) {
        return ORG_DETAIL;
      }
      throw new Error(`unexpected path: ${path}`);
    });

    const bundle = await fetchEntityDetailBundle(
      { requestJson: requestJson as ApiClient["requestJson"] },
      { entityType: "org", id: ORG_ID }
    );

    expect(bundle).toEqual({
      entityType: "org",
      detail: ORG_DETAIL
    });
    expect("matches" in bundle).toBe(false);
    expect("relationships" in bundle).toBe(false);
    expect(requestJson.mock.calls.map(([path]) => path)).toEqual([`/v1/org/${ORG_ID}`]);
  });

  it("preserves backend error semantics (e.g. malformed UUID 422)", async () => {
    const requestJson = vi
      .fn()
      .mockRejectedValue(
        new ApiResponseError(422, { detail: [{ loc: ["path", "person_id"], msg: "Input should be a valid UUID" }] })
      );

    await expect(
      fetchEntityDetailBundle(
        { requestJson: requestJson as ApiClient["requestJson"] },
        { entityType: "person", id: "not-a-uuid" }
      )
    ).rejects.toMatchObject({ status: 422 });
  });
});
