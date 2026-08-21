/** Contracts and route helpers for shared entity detail pages. */
export const STAGE4_DETAIL_ENTITY_TYPES = ["person", "org"] as const;

/** Public route message for a contract-invalid core person payload. */
export const PERSON_PROFILE_UNAVAILABLE_MESSAGE = "Person profile is temporarily unavailable.";

/**
 * Typed, adapter-mappable failure raised when a `/v1/person/{id}` payload is
 * present but violates the core person-detail contract (missing/invalid bio
 * attribution keys or malformed `current_office`). The runtime guard owns the
 * shape diagnosis; the server API adapter maps `status` + `routeErrorBody` to a
 * 502-class route error so a contract-invalid payload never escapes as a raw
 * SvelteKit 500 and never renders a blank HTTP 200.
 */
export class PersonPayloadContractError extends Error {
  readonly status = 502;
  readonly routeErrorBody = { message: PERSON_PROFILE_UNAVAILABLE_MESSAGE };

  constructor(detail: string) {
    super(detail);
    this.name = "PersonPayloadContractError";
  }
}

export type Stage4EntityType = (typeof STAGE4_DETAIL_ENTITY_TYPES)[number];
const REQUIRED_PERSON_BIO_KEYS = [
  "bio_text",
  "bio_source_url",
  "bio_license",
  "bio_pulled_at"
] as const;

const DETAIL_PATH_SEGMENT_BY_ENTITY_TYPE: Record<Stage4EntityType, Stage4EntityType> = {
  person: "person",
  org: "org"
};

const ROUTABLE_ENTITY_ROUTE_TYPES = ["person", "org", "committee", "candidate"] as const;

export type RoutableEntityRouteType = (typeof ROUTABLE_ENTITY_ROUTE_TYPES)[number];

const ROUTE_SEGMENT_BY_ENTITY_TYPE: Record<RoutableEntityRouteType, RoutableEntityRouteType> = {
  person: "person",
  org: "org",
  committee: "committee",
  candidate: "candidate"
};

export type SourceInfo = {
  domain: string;
  jurisdiction: string | null;
  data_source_name: string;
  data_source_url: string;
  source_record_key: string | null;
  record_url: string | null;
  pull_date: string;
};

type BaseDetailResponse = {
  id: string;
  canonical_name: string;
  name_variants: string[];
  identifiers: Record<string, string>;
  primary_address_id: string | null;
  er_cluster_id: string | null;
  er_confidence: number | null;
  sources: SourceInfo[];
};

export type PersonDetailResponse = BaseDetailResponse & {
  first_name: string | null;
  middle_name: string | null;
  last_name: string | null;
  suffix: string | null;
  occupation?: string | null;
  education?: string | null;
  date_of_birth: string | null;
  year_of_birth: number | null;
  bio_text: string | null;
  bio_source_url: string | null;
  bio_license: string | null;
  bio_pulled_at: string | null;
  portrait?: PersonPortraitResponse | null;
  current_office?: CurrentOfficeResponse | null;
  // Optional for version skew like current_office: older payloads may omit it.
  // The backend always serves the key (empty list = no races). civibus-x8b/7qj.
  candidacies?: PersonCandidacyResponse[] | null;
};

/**
 * One race the person is a candidate in, with linkable contest identity.
 * Server-ordered nearest election first; consumers must not re-sort. The
 * backend resolves rows through the shadow-person-safe join (candidate_number
 * -> cf.candidate.fec_candidate_id as well as person_id), so this list is
 * trustworthy for chamber-switching incumbents split across two person rows.
 */
export type PersonCandidacyResponse = {
  candidacy_id: string;
  contest_id: string;
  contest_name: string;
  election_date: string | null;
  election_type: string;
  office_id: string;
  office_name: string;
  office_level: string;
  party: string | null;
  status: string | null;
  incumbent_challenge: string | null;
  fec_candidate_id: string | null;
};

export type OrgDetailResponse = BaseDetailResponse & {
  org_type: string | null;
  registered_state: string | null;
  formation_date: string | null;
  dissolution_date: string | null;
};

export type PersonPortraitResponse = {
  status: string;
  rights_status: string;
  source_image_url: string | null;
  mime_type: string | null;
  width_px: number | null;
  height_px: number | null;
};

export type CurrentOfficeResponse = {
  officeholding_id: string;
  office_id: string;
  office_name: string;
  office_level: string;
  state: string | null;
};

export type EntityDetailResponse = PersonDetailResponse | OrgDetailResponse;

/**
 * Runtime contract guard for `/v1/person/{id}` payloads consumed by the detail page.
 * Stage 4 requires required-nullable bio attribution keys to always exist.
 */
export function assertPersonPayloadHasRequiredBioKeys(
  payload: unknown
): asserts payload is PersonDetailResponse {
  if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
    throw new PersonPayloadContractError("Person payload must be an object.");
  }

  const personPayload = payload as Record<string, unknown>;
  const missingBioKeys = REQUIRED_PERSON_BIO_KEYS.filter((key) => !(key in personPayload));

  if (missingBioKeys.length > 0) {
    throw new PersonPayloadContractError(`Person payload missing required bio keys: ${missingBioKeys.join(", ")}`);
  }

  const invalidValueKeys = REQUIRED_PERSON_BIO_KEYS.filter((key) => {
    const value = personPayload[key];
    return value !== null && typeof value !== "string";
  });

  if (invalidValueKeys.length > 0) {
    throw new PersonPayloadContractError(
      `Person payload bio keys must be string or null: ${invalidValueKeys.join(", ")}`
    );
  }

  // Before the current_office early-returns: candidacies must be validated even
  // when the payload has no current-office context.
  assertCandidaciesShape(personPayload);

  if (!("current_office" in personPayload)) {
    return;
  }

  const currentOffice = personPayload.current_office;
  if (currentOffice === null) {
    return;
  }
  if (typeof currentOffice !== "object" || Array.isArray(currentOffice)) {
    throw new PersonPayloadContractError("Person payload current_office must be an object or null.");
  }

  const currentOfficePayload = currentOffice as Record<string, unknown>;
  for (const key of ["officeholding_id", "office_id", "office_name", "office_level"] as const) {
    if (typeof currentOfficePayload[key] !== "string") {
      throw new PersonPayloadContractError(`Person payload current_office.${key} must be a string.`);
    }
  }
  if (currentOfficePayload.state !== null && typeof currentOfficePayload.state !== "string") {
    throw new PersonPayloadContractError("Person payload current_office.state must be a string or null.");
  }
}

// Required-string identity fields of a candidacy row: without these a Races row
// cannot render a truthful link. The nullable facts below may be absent-as-null
// but never a non-string value.
const REQUIRED_CANDIDACY_STRING_KEYS = [
  "candidacy_id",
  "contest_id",
  "contest_name",
  "election_type",
  "office_id",
  "office_name",
  "office_level"
] as const;

const NULLABLE_CANDIDACY_STRING_KEYS = [
  "election_date",
  "party",
  "status",
  "incumbent_challenge",
  "fec_candidate_id"
] as const;

/**
 * Guard for the optional `candidacies` list, called from
 * `assertPersonPayloadHasRequiredBioKeys` with the same version-skew rule as
 * `current_office`: omission (or null) is legal, malformed presence is the
 * typed 502-class contract failure.
 */
function assertCandidaciesShape(personPayload: Record<string, unknown>): void {
  if (!("candidacies" in personPayload) || personPayload.candidacies === null) {
    return;
  }

  const candidacies = personPayload.candidacies;
  if (!Array.isArray(candidacies)) {
    throw new PersonPayloadContractError("Person payload candidacies must be an array.");
  }

  candidacies.forEach((row, index) => {
    if (row === null || typeof row !== "object" || Array.isArray(row)) {
      throw new PersonPayloadContractError(`Person payload candidacies[${index}] must be an object.`);
    }
    const candidacyRow = row as Record<string, unknown>;
    for (const key of REQUIRED_CANDIDACY_STRING_KEYS) {
      if (typeof candidacyRow[key] !== "string") {
        throw new PersonPayloadContractError(`Person payload candidacies[${index}].${key} must be a string.`);
      }
    }
    for (const key of NULLABLE_CANDIDACY_STRING_KEYS) {
      if (candidacyRow[key] !== null && typeof candidacyRow[key] !== "string") {
        throw new PersonPayloadContractError(
          `Person payload candidacies[${index}].${key} must be a string or null.`
        );
      }
    }
  });
}

export function encodeRoutePathSegment(value: string): string {
  return encodeURIComponent(value);
}

function isRoutableEntityRouteType(value: string): value is RoutableEntityRouteType {
  return ROUTABLE_ENTITY_ROUTE_TYPES.includes(value as RoutableEntityRouteType);
}

export function buildEntityRouteHref(entityType: string, entityId: string): string | null {
  if (!isRoutableEntityRouteType(entityType)) {
    return null;
  }

  return `/${ROUTE_SEGMENT_BY_ENTITY_TYPE[entityType]}/${encodeRoutePathSegment(entityId)}`;
}

export function buildEntityDetailPath(entityType: Stage4EntityType, entityId: string): string {
  return `/v1/${DETAIL_PATH_SEGMENT_BY_ENTITY_TYPE[entityType]}/${encodeRoutePathSegment(entityId)}`;
}
