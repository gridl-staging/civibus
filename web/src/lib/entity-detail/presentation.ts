/**
 * @module Presentation builders for public person and organization detail pages.
 */
import { formatDisplayValue } from "$lib/detail-format";
import {
  buildTrustSection,
  type TrustSectionViewModel
} from "$lib/detail-trust/presentation";
import type {
  EntityDetailResponse,
  OrgDetailResponse,
  PersonDetailResponse,
  Stage4EntityType
} from "$lib/entity-detail/contract";
export {
  buildPersonContributionInsightsPresentation,
  buildPersonDonorVendorEmptyStateBanner,
  buildPersonDonorVendorRows,
  buildPersonLinkedCommitteeEmptyStateBanner,
  buildPersonLinkedCommitteeRows,
  buildPersonMoneyAtGlancePresentation,
  buildPersonMoneyAtGlanceSummary,
  buildPersonOutsideSpendingSection
} from "./person-campaign-finance-presentation";
export type {
  PersonContributionInsightsPresentation,
  PersonContributionTotalSummaryKey,
  PersonContributionTotalSummaryView,
  PersonCycleOption,
  PersonMoneyAtGlancePresentation,
  PersonMoneyAtGlanceSummary
} from "./person-campaign-finance-presentation";
export type {
  PersonGeographySharePresentation,
  PersonMonthlyContributionsPresentation,
  PersonReceiptCompositionPresentation,
  PersonSizeBucketPresentation
} from "./person-contribution-chart-presentation";

export type DetailFactRow = {
  label: string;
  value: string;
};

export type EntityDetailSectionKey =
  | "summary"
  | "trust"
  | "metrics"
  | "records"
  | "person-campaign-finance";

export type DetailRouteMetadata = {
  title: string;
  description: string;
};

export type EntityDetailMetadataInput = {
  entityType: Stage4EntityType;
  canonicalName: string;
  identifierCount: number;
};

export type EntityDetailMetadataFromDetailInput = {
  entityType: Stage4EntityType;
  detail: EntityDetailResponse;
};

export type EntityDetailShellInput = {
  entityType: Stage4EntityType;
  detail: EntityDetailResponse;
};

export type EntityDetailShellPresentation = {
  entityType: Stage4EntityType;
  canonicalName: string;
  sectionOrder: EntityDetailSectionKey[];
  coreFactRows: DetailFactRow[];
  keyMetricRows: DetailFactRow[];
  identifierRows: DetailFactRow[];
  trustSection: TrustSectionViewModel;
  identifierEmptyMessage: string | null;
};

export type EntityDetailPresentation = EntityDetailShellPresentation;

const ENTITY_TYPE_LABELS: Record<Stage4EntityType, string> = {
  person: "Person",
  org: "Organization"
};

const IDENTIFIER_EMPTY_MESSAGE =
  "No identifiers are available yet. Check related records after the next refresh.";

const PERSON_SECTION_ORDER: EntityDetailSectionKey[] = [
  "summary",
  "person-campaign-finance",
  "trust",
  "metrics",
  "records"
];
const ORG_SECTION_ORDER: EntityDetailSectionKey[] = ["summary", "trust", "metrics", "records"];

export function buildEntityDetailMetadata(input: EntityDetailMetadataInput): DetailRouteMetadata {
  const entityTypeLabel = ENTITY_TYPE_LABELS[input.entityType];

  return {
    title: `${input.canonicalName} | ${entityTypeLabel} | Civibus`,
    description: `${entityTypeLabel} profile with ${input.identifierCount} ${formatIdentifierLabel(input.identifierCount)} and source-linked records.`
  };
}

export function buildEntityDetailMetadataFromDetail(
  input: EntityDetailMetadataFromDetailInput
): DetailRouteMetadata {
  return buildEntityDetailMetadata({
    entityType: input.entityType,
    canonicalName: input.detail.canonical_name,
    identifierCount: Object.keys(input.detail.identifiers).length
  });
}

function formatIdentifierLabel(count: number): string {
  return count === 1 ? "identifier" : "identifiers";
}

function buildSharedFactRows(detail: EntityDetailResponse): DetailFactRow[] {
  return [{ label: "Canonical name", value: detail.canonical_name }];
}

/**
 */
export function buildCanonicalDetailFacts(
  entityType: Stage4EntityType,
  detail: EntityDetailResponse
): DetailFactRow[] {
  const sharedRows = buildSharedFactRows(detail);

  if (entityType === "person") {
    const personDetail = detail as PersonDetailResponse;

    return [
      ...sharedRows,
      { label: "First name", value: formatDisplayValue(personDetail.first_name) },
      { label: "Last name", value: formatDisplayValue(personDetail.last_name) },
      { label: "Occupation", value: formatDisplayValue(personDetail.occupation) },
      { label: "Education", value: formatDisplayValue(personDetail.education) },
      { label: "Year of birth", value: formatDisplayValue(personDetail.year_of_birth) }
    ];
  }

  const organizationDetail = detail as OrgDetailResponse;

  return [
    ...sharedRows,
    { label: "Organization type", value: formatDisplayValue(organizationDetail.org_type) },
    { label: "Registered state", value: formatDisplayValue(organizationDetail.registered_state) },
    { label: "Formation date", value: formatDisplayValue(organizationDetail.formation_date) }
  ];
}

export function buildIdentifierRows(identifiers: Record<string, string>): DetailFactRow[] {
  return Object.entries(identifiers)
    .sort(([leftKey], [rightKey]) => leftKey.localeCompare(rightKey))
    .map(([label, value]) => ({ label, value }));
}

export function buildIdentifierKeyMetrics(identifierRows: DetailFactRow[]): DetailFactRow[] {
  return [{ label: "Identifiers", value: String(identifierRows.length) }];
}

export function getIdentifierEmptyMessage(): string {
  return IDENTIFIER_EMPTY_MESSAGE;
}

/**
 */
export function buildEntityDetailShellPresentation(
  input: EntityDetailShellInput
): EntityDetailShellPresentation {
  const identifierRows = buildIdentifierRows(input.detail.identifiers);

  return {
    entityType: input.entityType,
    canonicalName: input.detail.canonical_name,
    sectionOrder: input.entityType === "person" ? PERSON_SECTION_ORDER : ORG_SECTION_ORDER,
    coreFactRows: buildCanonicalDetailFacts(input.entityType, input.detail),
    keyMetricRows: buildIdentifierKeyMetrics(identifierRows),
    identifierRows,
    trustSection: buildTrustSection(input.detail.sources),
    identifierEmptyMessage: identifierRows.length === 0 ? getIdentifierEmptyMessage() : null
  };
}

export function buildEntityDetailPresentation(
  input: EntityDetailShellInput
): EntityDetailPresentation {
  return buildEntityDetailShellPresentation(input);
}
