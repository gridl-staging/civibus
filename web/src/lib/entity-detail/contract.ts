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
