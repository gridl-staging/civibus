/** Contracts and route helpers for shared entity detail pages. */
export const STAGE4_DETAIL_ENTITY_TYPES = ["person", "org"] as const;

export type Stage4EntityType = (typeof STAGE4_DETAIL_ENTITY_TYPES)[number];
export type Stage4ErEntityType = "person" | "organization";
export type Stage4GraphEntityType = "person" | "org";
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

const ER_PATH_SEGMENT_BY_ENTITY_TYPE: Record<Stage4EntityType, Stage4ErEntityType> = {
  person: "person",
  org: "organization"
};

const GRAPH_PATH_SEGMENT_BY_ENTITY_TYPE: Record<Stage4EntityType, Stage4GraphEntityType> = {
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

export type EntityDetailResponse = PersonDetailResponse | OrgDetailResponse;

export type ErMatchDecision = {
  id: string;
  entity_type: Stage4ErEntityType;
  entity_id_a: string;
  entity_id_b: string;
  decision: string;
  confidence: number;
  decided_by: string;
  decision_method: string;
  match_evidence: Record<string, unknown> | null;
  decided_at: string;
};

export type GraphNeighbor = {
  entity_type: string;
  entity_id: string;
  name: string | null;
  relationship_type: string;
  direction: "outbound" | "inbound";
};

export type EntityGraphRelationshipsResponse = {
  entity_type: string;
  entity_id: string;
  neighbors: GraphNeighbor[];
  total_count: number;
};

export type GraphNeighborRouteClassification = {
  href: string | null;
  isRoutable: boolean;
};

/**
 * Runtime contract guard for `/v1/person/{id}` payloads consumed by the detail page.
 * Stage 4 requires required-nullable bio attribution keys to always exist.
 */
export function assertPersonPayloadHasRequiredBioKeys(
  payload: unknown
): asserts payload is PersonDetailResponse {
  if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error("Person payload must be an object.");
  }

  const personPayload = payload as Record<string, unknown>;
  const missingBioKeys = REQUIRED_PERSON_BIO_KEYS.filter((key) => !(key in personPayload));

  if (missingBioKeys.length > 0) {
    throw new Error(`Person payload missing required bio keys: ${missingBioKeys.join(", ")}`);
  }

  const invalidValueKeys = REQUIRED_PERSON_BIO_KEYS.filter((key) => {
    const value = personPayload[key];
    return value !== null && typeof value !== "string";
  });

  if (invalidValueKeys.length > 0) {
    throw new Error(
      `Person payload bio keys must be string or null: ${invalidValueKeys.join(", ")}`
    );
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

export function buildEntityErMatchesPath(entityType: Stage4EntityType, entityId: string): string {
  return `/v1/er/${ER_PATH_SEGMENT_BY_ENTITY_TYPE[entityType]}/${encodeRoutePathSegment(entityId)}/matches`;
}

export function buildEntityGraphRelationshipsPath(entityType: Stage4EntityType, entityId: string): string {
  return `/v1/graph/${GRAPH_PATH_SEGMENT_BY_ENTITY_TYPE[entityType]}/${encodeRoutePathSegment(entityId)}/relationships`;
}

/** Marks graph neighbors as routeable when the frontend has a matching detail page. */
export function classifyGraphNeighborRoute(
  neighbor: Pick<GraphNeighbor, "entity_type" | "entity_id">
): GraphNeighborRouteClassification {
  const href = buildEntityRouteHref(neighbor.entity_type, neighbor.entity_id);

  if (href === null) {
    return {
      href: null,
      isRoutable: false
    };
  }

  return {
    href,
    isRoutable: true
  };
}
