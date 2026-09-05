/** Backend contract types for landing-page and state-detail data fetches. */
import type { SourceInfo } from "$lib/entity-detail/contract";
import { sanitizeExternalUrl } from "$lib/url/sanitize-external-url";

export const STATE_SUPPORT_STATUS_VALUES = [
  "supported",
  "warning",
  "unsupported",
] as const;

export const STATE_COVERAGE_TIER_VALUES = [
  "launch-support candidate",
  "implemented but unproven",
  "freshness-limited",
  "deferred/blocked",
] as const;

export type StateSupportStatus = (typeof STATE_SUPPORT_STATUS_VALUES)[number];
export type StateCoverageTier =
  (typeof STATE_COVERAGE_TIER_VALUES)[number] | null;

/**
 */
export type StateSummaryItem = {
  state_code: string;
  total_raised: string | null;
  total_spent: string | null;
  net: string | null;
  committee_count: number;
  transaction_count: number;
  federal_candidate_count: number;
  ie_support_total: string | null;
  ie_oppose_total: string | null;
  ie_support_count: number | null;
  ie_oppose_count: number | null;
  coverage_tier: StateCoverageTier;
  support_status: StateSupportStatus;
  supported: boolean;
  warning_text: string | null;
  data_through: string | null;
};

export type StateCandidateTopEntry = {
  candidate_id: string;
  candidate_name: string;
  total_raised: string;
};

export type StateCommitteeTopEntry = {
  committee_id: string;
  committee_name: string;
  total_raised: string;
};

export type StateIndependentExpenditureTopSpender = {
  committee_id: string;
  committee_name: string;
  total_amount: string;
};

export type StateDetailResponse = StateSummaryItem & {
  top_candidates: StateCandidateTopEntry[];
  top_committees: StateCommitteeTopEntry[];
  top_ie_spenders: StateIndependentExpenditureTopSpender[];
  sources: SourceInfo[];
};

export type RetiredStateCampaignFinancePage = {
  heading: string;
  message: string;
  reversalPath: string;
};

export type GeometryFeatureProperties = {
  state: string;
  name: string;
  division_type: string;
  boundary_year: number | null;
};

export type GeometryRingCoordinates = number[][];
export type GeometryPolygonCoordinates = GeometryRingCoordinates[];
export type GeometryMultiPolygonCoordinates = GeometryPolygonCoordinates[];

export type GeometryPolygon = {
  type: "Polygon";
  coordinates: GeometryPolygonCoordinates;
};

export type GeometryMultiPolygon = {
  type: "MultiPolygon";
  coordinates: GeometryMultiPolygonCoordinates;
};

export type GeometryFeature = {
  type: "Feature";
  geometry: GeometryPolygon | GeometryMultiPolygon;
  properties: GeometryFeatureProperties;
};

export type GeometryFeatureCollection = {
  type: "FeatureCollection";
  features: GeometryFeature[];
};

export const COUNTRY_GEOMETRY_PATH = "/v1/geometry?level=country";

export const REGIONAL_NODE_KINDS = [
  "state",
  "county",
  "municipality",
  "school_district",
  "special_district",
] as const;
export const REGIONAL_CHILD_KINDS = [
  "county",
  "municipality",
  "school_district",
  "special_district",
] as const;
export const REGIONAL_FINANCE_STATUSES = [
  "available",
  "degraded",
  "stale",
  "unavailable",
] as const;
export const REGIONAL_AUTHORITY_KINDS = [
  "federal",
  "state",
  "county",
  "municipality",
  "school_district",
  "special_district",
  "named_other",
] as const;
export const REGIONAL_AUTHORITY_RELATIONS = [
  "independent",
  "inherited",
  "partitioned_overlapping",
  "unresolved",
] as const;
export const REGIONAL_AGGREGATION_DISPOSITIONS = [
  "not_applicable",
  "deduplicate",
  "refuse_combination",
  "refuse",
] as const;
export const REGIONAL_TRANSLATION_STATUSES = ["resolved", "refused"] as const;
export const REGIONAL_RECURRENCE_STATUSES = [
  "qualified",
  "degraded",
  "unknown",
  "refused",
] as const;
export const REGIONAL_REVISION_PARITIES = [
  "match",
  "mismatch",
  "unknown",
] as const;
export const REGIONAL_EXECUTION_ORIGINS = [
  "manual",
  "scheduled",
  "unknown",
] as const;
export const REGIONAL_MONEY_CLASS_KEYS = [
  "contributions",
  "expenditures",
  "independent_expenditures",
  "loans",
] as const;
export const REGIONAL_REFRESH_STATUSES = [
  "crashed",
  "empty",
  "degraded",
  "failed",
  "running",
  "success",
] as const;
export const REGIONAL_OVERLAP_DISPOSITIONS = ["not_combined"] as const;

export type RegionalNodeKind = (typeof REGIONAL_NODE_KINDS)[number];
export type RegionalChildKind = (typeof REGIONAL_CHILD_KINDS)[number];
export type RegionalFinanceStatus = (typeof REGIONAL_FINANCE_STATUSES)[number];
export type RegionalAuthorityKind = (typeof REGIONAL_AUTHORITY_KINDS)[number];
export type RegionalAuthorityRelation =
  (typeof REGIONAL_AUTHORITY_RELATIONS)[number];
export type RegionalAggregationDisposition =
  (typeof REGIONAL_AGGREGATION_DISPOSITIONS)[number];
export type RegionalTranslationStatus =
  (typeof REGIONAL_TRANSLATION_STATUSES)[number];
export type RegionalRecurrenceStatus =
  (typeof REGIONAL_RECURRENCE_STATUSES)[number];
export type RegionalRevisionParity =
  (typeof REGIONAL_REVISION_PARITIES)[number];
export type RegionalExecutionOrigin =
  (typeof REGIONAL_EXECUTION_ORIGINS)[number];
export type RegionalMoneyClassKey = (typeof REGIONAL_MONEY_CLASS_KEYS)[number];
export type RegionalRefreshStatus = (typeof REGIONAL_REFRESH_STATUSES)[number];
export type RegionalOverlapDisposition =
  (typeof REGIONAL_OVERLAP_DISPOSITIONS)[number];

export type RegionalSubjectIdentity = {
  kind: RegionalNodeKind;
  code: string;
  name: string;
};

export type RegionalFilingAuthority = {
  kind: RegionalAuthorityKind;
  code: string;
  name: string;
  scope: string;
  provenance_scope: string;
  official_url: string | null;
};

export type RegionalAuthorityContext = {
  subject: RegionalSubjectIdentity;
  public_route: string | null;
  acquisition_scope: string | null;
  provenance_scope: string | null;
  relation: RegionalAuthorityRelation;
  filing_authorities: RegionalFilingAuthority[];
  included_scopes: string[];
  excluded_scopes: string[];
  provenance_scopes: string[];
  aggregation_disposition: RegionalAggregationDisposition;
  evidence_date: string | null;
  translation_status: RegionalTranslationStatus;
  refusal_reasons: string[];
};

export type RegionalAuthorityHealth = {
  authority_code: string;
  freshness_status: RegionalFinanceStatus;
  degraded_source_names: string[];
  recurrence_status: RegionalRecurrenceStatus;
  recurrence_observed_at: string | null;
  revision_parity: RegionalRevisionParity;
  deployed_revision: string | null;
  promotion_eligible: boolean;
  refusal_reasons: string[];
};

export type RegionalFinanceSource = {
  class_key: RegionalMoneyClassKey;
  authority_code: string;
  source_identity: string;
  name: string;
  url: string;
  status: RegionalFinanceStatus;
  last_successful_pull: string | null;
  last_verified_working: string | null;
  latest_refresh_completed_at: string | null;
  latest_refresh_status: RegionalRefreshStatus | null;
  latest_refresh_execution_origin: RegionalExecutionOrigin;
  recurrence_status: RegionalRecurrenceStatus;
  reason: string;
};

export type RegionalMoneyClass = {
  key: RegionalMoneyClassKey;
  authority_code: string;
  source_identity: string;
  label: string;
  status: RegionalFinanceStatus;
  amount: string | null;
  transaction_count: number;
  data_through: string | null;
  source_name: string;
  reason: string;
};

export type RegionalNativeIdentifier = {
  authority_code: string;
  value: string;
};

export type RegionalCandidate = {
  person_id: string;
  person_name: string;
  candidacy_id: string;
  contest_id: string;
  contest_name: string;
  election_date: string | null;
  office_id: string;
  office_name: string;
  office_title: string | null;
  division_id: string | null;
  division_name: string | null;
  party: string | null;
  candidacy_status: string | null;
  current_officeholding_id: string | null;
  native_filer_identifier: RegionalNativeIdentifier | null;
  money_connection: "connected" | "unavailable";
  activity_amount: string | null;
  transaction_count: number;
};

export type RegionalCommittee = {
  committee_id: string;
  organization_id: string | null;
  name: string;
  activity_amount: string;
  transaction_count: number;
  data_through: string | null;
};

export type RegionalFinanceDetail = {
  subject: RegionalSubjectIdentity;
  authority_context: RegionalAuthorityContext;
  authority_health: RegionalAuthorityHealth[];
  as_of: string;
  period_start: string;
  period_end: string;
  money: RegionalMoneyClass[];
  candidates: RegionalCandidate[];
  committees: RegionalCommittee[];
  sources: RegionalFinanceSource[];
  registry_evidence_date: string | null;
  lifecycle_registry_updated_at: string | null;
  included: string[];
  excluded: string[];
  named_gaps: string[];
};

export type RegionalNavigationNode = {
  kind: RegionalNodeKind;
  name: string;
  state_code: string;
  state_name: string;
  slug: string | null;
  canonical_path: string;
  geometry_reference: {
    namespace: "civic";
    kind: "electoral_division_name";
    value: string;
  } | null;
  finance: {
    status: RegionalFinanceStatus;
    authority_context: RegionalAuthorityContext;
    authority_health: RegionalAuthorityHealth[];
    reason: string;
  };
  finance_detail: RegionalFinanceDetail | null;
  proxy_analysis: {
    label: string;
    scope_label: string;
    excludes: string[];
    overlap_disposition: RegionalOverlapDisposition;
  } | null;
};

export type RegionalNavigationListResult = {
  items: RegionalNavigationNode[];
  incomplete_node_kinds: RegionalNodeKind[];
  has_unsafe_omissions: boolean;
};

export type RegionalResolveParams = {
  kind: RegionalNodeKind;
  stateCode: string;
  slug?: string | null;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isNonBlankString(value: unknown): value is string {
  return typeof value === "string" && value.trim() !== "";
}

function hasOnlyKeys(
  value: Record<string, unknown>,
  allowedKeys: readonly string[],
): boolean {
  const allowed = new Set(allowedKeys);
  return Object.keys(value).every((key) => allowed.has(key));
}

function isIsoDateOrNull(value: unknown): value is string | null {
  if (value === null) return true;
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value))
    return false;
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  return (
    date.getUTCFullYear() === year &&
    date.getUTCMonth() === month - 1 &&
    date.getUTCDate() === day
  );
}

function isSafeExternalUrl(value: unknown): value is string {
  return typeof value === "string" && sanitizeExternalUrl(value) !== null;
}

function isIsoDateTimeOrNull(value: unknown): value is string | null {
  return (
    value === null ||
    (typeof value === "string" && !Number.isNaN(Date.parse(value)))
  );
}

function isOptionalString(value: unknown): value is string | null {
  return value === null || isNonBlankString(value);
}

function isUuid(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
      value,
    )
  );
}

function isMoneyString(value: unknown): value is string {
  return (
    typeof value === "string" && /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(value)
  );
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function isRegionalFinanceStatus(
  value: unknown,
): value is RegionalFinanceStatus {
  return (
    typeof value === "string" &&
    REGIONAL_FINANCE_STATUSES.includes(value as RegionalFinanceStatus)
  );
}

function isRegionalMoneyClassKey(
  value: unknown,
): value is RegionalMoneyClassKey {
  return (
    typeof value === "string" &&
    REGIONAL_MONEY_CLASS_KEYS.includes(value as RegionalMoneyClassKey)
  );
}

function isRegionalNodeKind(value: unknown): value is RegionalNodeKind {
  return (
    typeof value === "string" &&
    REGIONAL_NODE_KINDS.includes(value as RegionalNodeKind)
  );
}

function isRegionalSubjectIdentity(
  value: unknown,
): value is RegionalSubjectIdentity {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["kind", "code", "name"]) &&
    isRegionalNodeKind(value.kind) &&
    isNonBlankString(value.code) &&
    isNonBlankString(value.name)
  );
}

function isRegionalFilingAuthority(
  value: unknown,
): value is RegionalFilingAuthority {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, [
      "kind",
      "code",
      "name",
      "scope",
      "provenance_scope",
      "official_url",
    ]) &&
    typeof value.kind === "string" &&
    REGIONAL_AUTHORITY_KINDS.includes(value.kind as RegionalAuthorityKind) &&
    isNonBlankString(value.code) &&
    isNonBlankString(value.name) &&
    isNonBlankString(value.scope) &&
    isNonBlankString(value.provenance_scope) &&
    (value.official_url === null || isSafeExternalUrl(value.official_url))
  );
}

function isNonBlankStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isNonBlankString);
}

function isRegionalAuthorityContext(
  value: unknown,
): value is RegionalAuthorityContext {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, [
      "subject",
      "public_route",
      "acquisition_scope",
      "provenance_scope",
      "relation",
      "filing_authorities",
      "included_scopes",
      "excluded_scopes",
      "provenance_scopes",
      "aggregation_disposition",
      "evidence_date",
      "translation_status",
      "refusal_reasons",
    ]) ||
    !isRegionalSubjectIdentity(value.subject) ||
    !isOptionalString(value.public_route) ||
    !isOptionalString(value.acquisition_scope) ||
    !isOptionalString(value.provenance_scope) ||
    typeof value.relation !== "string" ||
    !REGIONAL_AUTHORITY_RELATIONS.includes(
      value.relation as RegionalAuthorityRelation,
    ) ||
    !Array.isArray(value.filing_authorities) ||
    !value.filing_authorities.every(isRegionalFilingAuthority) ||
    !isNonBlankStringArray(value.included_scopes) ||
    !isNonBlankStringArray(value.excluded_scopes) ||
    !isNonBlankStringArray(value.provenance_scopes) ||
    typeof value.aggregation_disposition !== "string" ||
    !REGIONAL_AGGREGATION_DISPOSITIONS.includes(
      value.aggregation_disposition as RegionalAggregationDisposition,
    ) ||
    !isIsoDateOrNull(value.evidence_date) ||
    typeof value.translation_status !== "string" ||
    !REGIONAL_TRANSLATION_STATUSES.includes(
      value.translation_status as RegionalTranslationStatus,
    ) ||
    !isNonBlankStringArray(value.refusal_reasons)
  )
    return false;
  const authorityKeys = value.filing_authorities.map(
    (authority) => `${authority.kind}:${authority.code}`,
  );
  if (new Set(authorityKeys).size !== authorityKeys.length) return false;
  if (
    value.relation === "partitioned_overlapping" &&
    (value.filing_authorities.length < 2 ||
      !["deduplicate", "refuse_combination"].includes(
        value.aggregation_disposition,
      ))
  )
    return false;
  if (
    value.relation === "unresolved" &&
    (value.aggregation_disposition !== "refuse" ||
      value.translation_status !== "refused")
  )
    return false;
  return !(
    value.translation_status === "refused" &&
    value.refusal_reasons.length === 0
  );
}

function isRegionalAuthorityHealth(
  value: unknown,
): value is RegionalAuthorityHealth {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, [
      "authority_code",
      "freshness_status",
      "degraded_source_names",
      "recurrence_status",
      "recurrence_observed_at",
      "revision_parity",
      "deployed_revision",
      "promotion_eligible",
      "refusal_reasons",
    ]) ||
    !isNonBlankString(value.authority_code) ||
    !isRegionalFinanceStatus(value.freshness_status) ||
    !Array.isArray(value.degraded_source_names) ||
    !value.degraded_source_names.every((name) => typeof name === "string") ||
    typeof value.recurrence_status !== "string" ||
    !REGIONAL_RECURRENCE_STATUSES.includes(
      value.recurrence_status as RegionalRecurrenceStatus,
    ) ||
    !isIsoDateTimeOrNull(value.recurrence_observed_at) ||
    typeof value.revision_parity !== "string" ||
    !REGIONAL_REVISION_PARITIES.includes(
      value.revision_parity as RegionalRevisionParity,
    ) ||
    !isOptionalString(value.deployed_revision) ||
    typeof value.promotion_eligible !== "boolean" ||
    !isNonBlankStringArray(value.refusal_reasons)
  )
    return false;
  return value.promotion_eligible
    ? value.refusal_reasons.length === 0
    : value.refusal_reasons.length > 0;
}

function isRegionalFinanceSource(
  value: unknown,
): value is RegionalFinanceSource {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, [
      "class_key",
      "authority_code",
      "source_identity",
      "name",
      "url",
      "status",
      "last_successful_pull",
      "last_verified_working",
      "latest_refresh_completed_at",
      "latest_refresh_status",
      "latest_refresh_execution_origin",
      "recurrence_status",
      "reason",
    ]) &&
    isRegionalMoneyClassKey(value.class_key) &&
    isNonBlankString(value.authority_code) &&
    isNonBlankString(value.source_identity) &&
    isNonBlankString(value.name) &&
    isSafeExternalUrl(value.url) &&
    isRegionalFinanceStatus(value.status) &&
    isIsoDateTimeOrNull(value.last_successful_pull) &&
    isIsoDateOrNull(value.last_verified_working) &&
    isIsoDateTimeOrNull(value.latest_refresh_completed_at) &&
    (value.latest_refresh_status === null ||
      (typeof value.latest_refresh_status === "string" &&
        REGIONAL_REFRESH_STATUSES.includes(
          value.latest_refresh_status as RegionalRefreshStatus,
        ))) &&
    typeof value.latest_refresh_execution_origin === "string" &&
    REGIONAL_EXECUTION_ORIGINS.includes(
      value.latest_refresh_execution_origin as RegionalExecutionOrigin,
    ) &&
    typeof value.recurrence_status === "string" &&
    REGIONAL_RECURRENCE_STATUSES.includes(
      value.recurrence_status as RegionalRecurrenceStatus,
    ) &&
    isNonBlankString(value.reason)
  );
}

function isRegionalMoneyClass(value: unknown): value is RegionalMoneyClass {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, [
      "key",
      "authority_code",
      "source_identity",
      "label",
      "status",
      "amount",
      "transaction_count",
      "data_through",
      "source_name",
      "reason",
    ]) ||
    !isRegionalMoneyClassKey(value.key) ||
    !isNonBlankString(value.authority_code) ||
    !isNonBlankString(value.source_identity) ||
    !isNonBlankString(value.label) ||
    !isRegionalFinanceStatus(value.status) ||
    !(value.amount === null || isMoneyString(value.amount)) ||
    !isNonNegativeInteger(value.transaction_count) ||
    !isIsoDateOrNull(value.data_through) ||
    !isNonBlankString(value.source_name) ||
    !isNonBlankString(value.reason)
  ) {
    return false;
  }
  return value.status === "unavailable"
    ? value.amount === null
    : isMoneyString(value.amount);
}

function isRegionalNativeIdentifier(
  value: unknown,
): value is RegionalNativeIdentifier {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["authority_code", "value"]) &&
    isNonBlankString(value.authority_code) &&
    isNonBlankString(value.value)
  );
}

function isRegionalCandidate(
  value: unknown,
): value is RegionalCandidate {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, [
      "person_id",
      "person_name",
      "candidacy_id",
      "contest_id",
      "contest_name",
      "election_date",
      "office_id",
      "office_name",
      "office_title",
      "division_id",
      "division_name",
      "party",
      "candidacy_status",
      "current_officeholding_id",
      "native_filer_identifier",
      "money_connection",
      "activity_amount",
      "transaction_count",
    ])
  )
    return false;
  if (
    !isUuid(value.person_id) ||
    !isNonBlankString(value.person_name) ||
    !isUuid(value.candidacy_id) ||
    !isUuid(value.contest_id) ||
    !isNonBlankString(value.contest_name) ||
    !isIsoDateOrNull(value.election_date) ||
    !isUuid(value.office_id) ||
    !isNonBlankString(value.office_name) ||
    !isOptionalString(value.office_title) ||
    !(value.division_id === null || isUuid(value.division_id)) ||
    !isOptionalString(value.division_name) ||
    !isOptionalString(value.party) ||
    !isOptionalString(value.candidacy_status) ||
    !(
      value.current_officeholding_id === null ||
      isUuid(value.current_officeholding_id)
    ) ||
    !(
      value.native_filer_identifier === null ||
      isRegionalNativeIdentifier(value.native_filer_identifier)
    ) ||
    (value.money_connection !== "connected" &&
      value.money_connection !== "unavailable") ||
    !(value.activity_amount === null || isMoneyString(value.activity_amount)) ||
    !isNonNegativeInteger(value.transaction_count)
  )
    return false;
  return value.money_connection === "connected"
    ? isRegionalNativeIdentifier(value.native_filer_identifier) &&
        isMoneyString(value.activity_amount)
    : value.native_filer_identifier === null &&
        value.activity_amount === null &&
        value.transaction_count === 0;
}

function isRegionalCommittee(
  value: unknown,
): value is RegionalCommittee {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, [
      "committee_id",
      "organization_id",
      "name",
      "activity_amount",
      "transaction_count",
      "data_through",
    ]) &&
    isUuid(value.committee_id) &&
    (value.organization_id === null || isUuid(value.organization_id)) &&
    isNonBlankString(value.name) &&
    isMoneyString(value.activity_amount) &&
    isNonNegativeInteger(value.transaction_count) &&
    value.transaction_count > 0 &&
    isIsoDateOrNull(value.data_through)
  );
}

function isRegionalFinanceDetail(
  value: unknown,
): value is RegionalFinanceDetail {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, [
      "subject",
      "authority_context",
      "authority_health",
      "as_of",
      "period_start",
      "period_end",
      "money",
      "candidates",
      "committees",
      "sources",
      "registry_evidence_date",
      "lifecycle_registry_updated_at",
      "included",
      "excluded",
      "named_gaps",
    ]) ||
    !isRegionalSubjectIdentity(value.subject) ||
    !isRegionalAuthorityContext(value.authority_context) ||
    !Array.isArray(value.authority_health) ||
    !value.authority_health.every(isRegionalAuthorityHealth) ||
    !isIsoDateTimeOrNull(value.as_of) ||
    value.as_of === null ||
    !isIsoDateOrNull(value.period_start) ||
    value.period_start === null ||
    !isIsoDateOrNull(value.period_end) ||
    value.period_end === null ||
    !Array.isArray(value.money) ||
    value.money.length === 0 ||
    !value.money.every(isRegionalMoneyClass) ||
    !Array.isArray(value.candidates) ||
    !value.candidates.every(isRegionalCandidate) ||
    !Array.isArray(value.committees) ||
    !value.committees.every(isRegionalCommittee) ||
    !Array.isArray(value.sources) ||
    value.sources.length === 0 ||
    !value.sources.every(isRegionalFinanceSource) ||
    !isIsoDateOrNull(value.registry_evidence_date) ||
    !isIsoDateOrNull(value.lifecycle_registry_updated_at) ||
    !Array.isArray(value.included) ||
    value.included.length === 0 ||
    !value.included.every(isNonBlankString) ||
    !Array.isArray(value.excluded) ||
    value.excluded.length === 0 ||
    !value.excluded.every(isNonBlankString) ||
    !Array.isArray(value.named_gaps) ||
    !value.named_gaps.every(isNonBlankString)
  )
    return false;
  const moneyKeys = value.money.map(
    (row) => `${row.authority_code}:${row.source_identity}:${row.key}`,
  );
  const sourceKeys = value.sources.map(
    (row) => `${row.authority_code}:${row.source_identity}:${row.class_key}`,
  );
  return (
    new Set(moneyKeys).size === moneyKeys.length &&
    new Set(sourceKeys).size === sourceKeys.length &&
    moneyKeys.length === sourceKeys.length &&
    moneyKeys.every((key) => sourceKeys.includes(key)) &&
    JSON.stringify(value.subject) ===
      JSON.stringify(value.authority_context.subject) &&
    new Set(value.named_gaps).size === value.named_gaps.length
  );
}

function expectedRegionalPath(
  kind: RegionalNodeKind,
  stateCode: string,
  slug: string | null,
): string | null {
  if (kind === "state") {
    return slug === null ? `/state/${stateCode}` : null;
  }
  if (slug === null || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug)) {
    return null;
  }
  const routeSegment =
    kind === "school_district"
      ? "school-district"
      : kind === "special_district"
        ? "special-district"
        : kind;
  return `/state/${stateCode}/${routeSegment}/${slug}`;
}

export function isRegionalNavigationNode(
  value: unknown,
): value is RegionalNavigationNode {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, [
      "kind",
      "name",
      "state_code",
      "state_name",
      "slug",
      "canonical_path",
      "geometry_reference",
      "finance",
      "finance_detail",
      "proxy_analysis",
    ]) ||
    !isRegionalNodeKind(value.kind)
  )
    return false;
  if (!isNonBlankString(value.name) || !isNonBlankString(value.state_name))
    return false;
  if (
    typeof value.state_code !== "string" ||
    !/^[A-Z]{2}$/.test(value.state_code)
  )
    return false;
  if (value.slug !== null && typeof value.slug !== "string") return false;

  const expectedPath = expectedRegionalPath(
    value.kind,
    value.state_code,
    value.slug as string | null,
  );
  if (expectedPath === null || value.canonical_path !== expectedPath)
    return false;

  if (value.geometry_reference !== null) {
    if (!isRecord(value.geometry_reference)) return false;
    if (
      !hasOnlyKeys(value.geometry_reference, ["namespace", "kind", "value"]) ||
      value.geometry_reference.namespace !== "civic" ||
      value.geometry_reference.kind !== "electoral_division_name" ||
      !isNonBlankString(value.geometry_reference.value)
    )
      return false;
  }

  if (!isRecord(value.finance)) return false;
  if (
    !hasOnlyKeys(value.finance, [
      "status",
      "authority_context",
      "authority_health",
      "reason",
    ]) ||
    !isRegionalFinanceStatus(value.finance.status) ||
    !isRegionalAuthorityContext(value.finance.authority_context) ||
    !Array.isArray(value.finance.authority_health) ||
    !value.finance.authority_health.every(isRegionalAuthorityHealth) ||
    !isNonBlankString(value.finance.reason)
  )
    return false;
  const context = value.finance.authority_context;
  if (
    context.subject.kind !== value.kind ||
    context.subject.name !== value.name ||
    (context.public_route !== null && context.public_route !== value.canonical_path)
  )
    return false;

  if (value.finance_detail !== null) {
    if (!isRegionalFinanceDetail(value.finance_detail)) return false;
    const detail = value.finance_detail;
    if (
      JSON.stringify(context) !== JSON.stringify(detail.authority_context) ||
      JSON.stringify(context.subject) !== JSON.stringify(detail.subject) ||
      JSON.stringify(value.finance.authority_health) !==
        JSON.stringify(detail.authority_health)
    )
      return false;
    const statuses = new Set(detail.money.map((row) => row.status));
    const expectedStatus: RegionalFinanceStatus =
      statuses.size === 1 && statuses.has("unavailable")
        ? "unavailable"
        : statuses.has("unavailable") || statuses.has("degraded")
          ? "degraded"
          : statuses.has("stale")
            ? "stale"
            : "available";
    if (value.finance.status !== expectedStatus) return false;
  }

  if (value.proxy_analysis !== null) {
    if (!isRecord(value.proxy_analysis)) return false;
    if (
      !hasOnlyKeys(value.proxy_analysis, [
        "label",
        "scope_label",
        "excludes",
        "overlap_disposition",
      ]) ||
      !isNonBlankString(value.proxy_analysis.label) ||
      !isNonBlankString(value.proxy_analysis.scope_label) ||
      !Array.isArray(value.proxy_analysis.excludes) ||
      !value.proxy_analysis.excludes.every(isNonBlankString) ||
      typeof value.proxy_analysis.overlap_disposition !== "string" ||
      !REGIONAL_OVERLAP_DISPOSITIONS.includes(
        value.proxy_analysis.overlap_disposition as RegionalOverlapDisposition,
      )
    )
      return false;
  }

  return true;
}

export function buildRegionalResolvePath(
  params: RegionalResolveParams,
): string {
  const searchParams = new URLSearchParams({
    kind: params.kind,
    state_code: params.stateCode,
  });
  if (params.slug !== undefined && params.slug !== null)
    searchParams.set("slug", params.slug);
  return `/v1/regional-navigation/resolve?${searchParams.toString()}`;
}

export function buildRegionalChildrenPath(
  stateCode: string,
  kind: RegionalChildKind,
): string {
  const searchParams = new URLSearchParams({ state_code: stateCode, kind });
  return `/v1/regional-navigation/children?${searchParams.toString()}`;
}

export function buildRegionalSearchPath(query: string, limit = 20): string {
  const searchParams = new URLSearchParams({ q: query, limit: String(limit) });
  return `/v1/regional-navigation/search?${searchParams.toString()}`;
}

export function parseRegionalNavigationList(
  value: unknown,
): RegionalNavigationListResult {
  if (
    !isRecord(value) ||
    !hasOnlyKeys(value, [
      "items",
      "incomplete_node_kinds",
      "has_unsafe_omissions",
    ]) ||
    !Array.isArray(value.items) ||
    !Array.isArray(value.incomplete_node_kinds) ||
    typeof value.has_unsafe_omissions !== "boolean"
  ) {
    throw new Error(
      "Regional navigation response did not contain one safe list envelope.",
    );
  }

  if (
    !value.items.every(isRegionalNavigationNode) ||
    !value.incomplete_node_kinds.every(isRegionalNodeKind)
  ) {
    throw new Error(
      "Regional navigation response contained an unsafe route or omission kind.",
    );
  }

  const incompleteNodeKinds = value.incomplete_node_kinds as RegionalNodeKind[];
  const canonicalNodeKeys = (value.items as RegionalNavigationNode[]).map(
    (item) => `${item.kind}:${item.canonical_path}`,
  );
  if (new Set(canonicalNodeKeys).size !== canonicalNodeKeys.length) {
    throw new Error(
      "Regional navigation response contained duplicate canonical nodes.",
    );
  }
  const geometryReferenceKeys = (value.items as RegionalNavigationNode[])
    .map((item) => item.geometry_reference)
    .filter((reference) => reference !== null)
    .map(
      (reference) =>
        `${reference.namespace}:${reference.kind}:${reference.value}`,
    );
  if (new Set(geometryReferenceKeys).size !== geometryReferenceKeys.length) {
    throw new Error(
      "Regional navigation response contained duplicate typed geometry references.",
    );
  }
  if (incompleteNodeKinds.length > 0 && value.has_unsafe_omissions !== true) {
    throw new Error(
      "Regional navigation response contradicted its omission disclosure.",
    );
  }
  return {
    items: value.items as RegionalNavigationNode[],
    incomplete_node_kinds: [...new Set(incompleteNodeKinds)],
    has_unsafe_omissions: value.has_unsafe_omissions,
  };
}
