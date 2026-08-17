import type { PersonDetailResponse } from "./contract";

const PERSON_ID = "11111111-1111-4111-8111-111111111111";

export function buildPersonDetailFixture(
  overrides: Partial<PersonDetailResponse> = {}
): PersonDetailResponse {
  return {
    id: PERSON_ID,
    canonical_name: "Jane Doe",
    name_variants: [],
    first_name: "Jane",
    middle_name: null,
    last_name: "Doe",
    suffix: null,
    occupation: "Attorney",
    education: "State University",
    date_of_birth: null,
    year_of_birth: 1985,
    bio_text: null,
    bio_source_url: null,
    bio_license: null,
    bio_pulled_at: null,
    identifiers: { fec_candidate_id: "H0NC01001" },
    primary_address_id: null,
    er_cluster_id: null,
    er_confidence: null,
    current_office: {
      officeholding_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      office_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      office_name: "City Council Member",
      office_level: "municipal",
      state: "NC"
    },
    portrait: {
      status: "active",
      rights_status: "licensed",
      source_image_url: "https://images.example.org/jane-doe.jpg",
      mime_type: "image/jpeg",
      width_px: 512,
      height_px: 512
    },
    sources: [],
    ...overrides
  };
}
