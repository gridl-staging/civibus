/**
 * Presentation builders for canonical person and organization detail pages.
 * These helpers keep display logic, civic-record shaping, and technical-disclosure
 * formatting out of the Svelte components.
 */
import { formatCountLabel } from "$lib/count-label";
import {
  buildCandidacyRoutePath,
  buildContestRoutePath,
  buildOfficeRoutePath,
  buildOfficeholdingRoutePath,
  type CandidacyDetailResponse,
  type OfficeholdingDetailResponse
} from "$lib/civic-detail/contract";
import {
  buildCandidateDeferredFundraisingSummary,
  buildCandidateDeferredOutsideSpending,
  buildCandidateCommitteeBreakdown,
  buildCommitteeDeferredTransactionRows,
  type CandidateAggregateSummaryPresentation,
  type CandidateCommitteeBreakdownRow,
  type CommitteeTransactionRow,
  type OutsideSpendingPresentation
} from "$lib/campaign-finance-detail/presentation";
import type {
  CandidateFundraisingSummary,
  CampaignFinanceTransactionResponse,
  IndependentExpenditureResponse,
  IndependentExpenditureSummary,
  SerializedMoney
} from "$lib/campaign-finance-detail/contract";
import type { ChartSeries } from "$lib/charts/types";
import { formatDisplayValue } from "$lib/detail-format";
import {
  buildDonorVendorEmptyStateBanner,
  buildLinkedCommitteeEmptyStateBanner,
  buildTrustSection,
  type TrustSectionViewModel
} from "$lib/detail-trust/presentation";
import {
  classifyGraphNeighborRoute,
  type EntityDetailResponse,
  type EntityGraphRelationshipsResponse,
  type GraphNeighbor,
  type Stage4EntityType,
  type ErMatchDecision,
  type OrgDetailResponse,
  type PersonDetailResponse
} from "$lib/entity-detail/contract";

export type DetailFactRow = {
  label: string;
  value: string;
};

export type ErMatchSummaryRow = {
  counterpartEntityId: string;
  decision: string;
  confidence: string;
  decidedAt: string;
};

export type GraphNeighborDisplayRow = {
  title: string;
  entityType: string;
  relationshipType: string;
  direction: "outbound" | "inbound";
  href: string | null;
};

export type EmptyPanelKey = "identifiers" | "matches" | "neighbors";
export type EntityDetailSectionKey =
  | "summary"
  | "trust"
  | "metrics"
  | "records"
  | "civic-record"
  | "person-civic-history"
  | "person-campaign-finance"
  | "technical-disclosure";

type CivicContextLabel = "Office" | "Contest";

export type CivicRecordRow = {
  recordType: "Candidacy" | "Officeholding";
  recordName: string;
  recordHref: string;
  contextLabel: CivicContextLabel | null;
  contextName: string | null;
  contextHref: string | null;
};

export type CivicRecordSection = {
  title: string;
  rows: CivicRecordRow[];
  emptyMessage: string | null;
};

export type DetailRouteMetadata = {
  title: string;
  description: string;
};

export type EntityDetailMetadataInput = {
  entityType: Stage4EntityType;
  canonicalName: string;
  identifierCount: number;
  matchCount: number;
  neighborCount: number;
};

export type EntityDetailMetadataFromDetailInput = {
  entityType: Stage4EntityType;
  detail: EntityDetailResponse;
};

export type EntityDetailShellInput = {
  entityType: Stage4EntityType;
  detail: EntityDetailResponse;
};

export type ResolvedEntityDetailBundle = {
  entityType: Stage4EntityType;
  detail: EntityDetailResponse;
  matches: ErMatchDecision[];
  relationships: EntityGraphRelationshipsResponse;
};

export type EntityDetailPresentation = {
  entityType: Stage4EntityType;
  canonicalName: string;
  sectionOrder: EntityDetailSectionKey[];
  coreFactRows: DetailFactRow[];
  keyMetricRows: DetailFactRow[];
  identifierRows: DetailFactRow[];
  trustSection: TrustSectionViewModel;
  matchRows: ErMatchSummaryRow[];
  neighborRows: GraphNeighborDisplayRow[];
  technicalDisclosure: TechnicalDisclosureSection;
  civicRecordSection: CivicRecordSection | null;
  identifierEmptyMessage: string | null;
  matchEmptyMessage: string | null;
  neighborEmptyMessage: string | null;
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

export type TechnicalDisclosureSection = {
  summary: string;
  matchRows: ErMatchSummaryRow[];
  neighborRows: GraphNeighborDisplayRow[];
  matchEmptyMessage: string | null;
  neighborEmptyMessage: string | null;
};

export type PersonOfficeholdingTimelineRow = {
  officeholdingId: string;
  officeholdingLabel: string;
  officeholdingHref: string;
  officeLabel: string;
  officeHref: string;
  holderStatus: string;
  validFrom: string;
  validThrough: string;
};

export type PersonCandidacyRow = {
  candidacyId: string;
  candidacyLabel: string;
  candidacyHref: string;
  contestLabel: string;
  contestHref: string;
  filingDate: string;
  party: string;
  status: string;
  incumbentChallenge: string;
};

const ENTITY_TYPE_LABELS: Record<Stage4EntityType, string> = {
  person: "Person",
  org: "Organization"
};

const EMPTY_PANEL_MESSAGES: Record<EmptyPanelKey, string> = {
  identifiers: "No identifiers are available yet. Check related records after the next refresh.",
  matches: "No entity-resolution matches are available yet. Check back after the next ER refresh.",
  neighbors: "No graph relationships are available yet. Linked records will appear after future ingests."
};

function getOptionalEmptyMessage(rows: unknown[], panel: EmptyPanelKey): string | null {
  return rows.length === 0 ? EMPTY_PANEL_MESSAGES[panel] : null;
}

const PERSON_SECTION_ORDER: EntityDetailSectionKey[] = [
  "summary",
  "trust",
  "metrics",
  "records",
  "civic-record",
  "person-civic-history",
  "person-campaign-finance",
  "technical-disclosure"
];
const ORG_SECTION_ORDER: EntityDetailSectionKey[] = ["summary", "trust", "metrics", "records", "technical-disclosure"];

const TECHNICAL_DISCLOSURE_SUMMARY = "Entity-resolution and graph internals";
const CIVIC_RECORD_TITLE = "Civic Record";
const CIVIC_RECORD_EMPTY_MESSAGE = "No civic record relationships are available yet.";
const LOADING_METRIC_VALUE = "Loading...";
const UNAVAILABLE_METRIC_VALUE = "Unavailable";
const DEFAULT_OFFICEHOLDING_LABEL = "Officeholding record";
const DEFAULT_OFFICE_LABEL = "Office record";
const DEFAULT_CANDIDACY_LABEL = "Candidacy record";
const DEFAULT_CONTEST_LABEL = "Contest record";

export function buildEntityDetailMetadata(input: EntityDetailMetadataInput): DetailRouteMetadata {
  const identifierLabel = formatCountLabel(input.identifierCount, "identifier");
  const matchLabel = formatCountLabel(input.matchCount, "ER match", "ER matches");
  const relationshipLabel = formatCountLabel(input.neighborCount, "graph relationship");
  const entityTypeLabel = ENTITY_TYPE_LABELS[input.entityType];

  return {
    title: `${input.canonicalName} | ${entityTypeLabel} | Civibus`,
    description: `${entityTypeLabel} profile with ${identifierLabel}, ${matchLabel}, and ${relationshipLabel}.`
  };
}

export function buildEntityDetailMetadataFromDetail(
  input: EntityDetailMetadataFromDetailInput
): DetailRouteMetadata {
  const identifierLabel = formatCountLabel(Object.keys(input.detail.identifiers).length, "identifier");
  const entityTypeLabel = ENTITY_TYPE_LABELS[input.entityType];

  return {
    title: `${input.detail.canonical_name} | ${entityTypeLabel} | Civibus`,
    description: `${entityTypeLabel} profile with ${identifierLabel} and source-linked records.`
  };
}

function formatConfidence(value: number | null): string {
  if (value === null) {
    return "—";
  }

  return value.toFixed(2);
}

function buildSharedFactRows(detail: EntityDetailResponse): DetailFactRow[] {
  return [{ label: "Canonical name", value: detail.canonical_name }];
}

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
      { label: "Year of birth", value: formatDisplayValue(personDetail.year_of_birth) },
      { label: "ER confidence", value: formatConfidence(personDetail.er_confidence) }
    ];
  }

  const organizationDetail = detail as OrgDetailResponse;

  return [
    ...sharedRows,
    { label: "Organization type", value: formatDisplayValue(organizationDetail.org_type) },
    { label: "Registered state", value: formatDisplayValue(organizationDetail.registered_state) },
    { label: "Formation date", value: formatDisplayValue(organizationDetail.formation_date) },
    { label: "ER confidence", value: formatConfidence(organizationDetail.er_confidence) }
  ];
}

export function buildIdentifierRows(identifiers: Record<string, string>): DetailFactRow[] {
  return Object.entries(identifiers)
    .sort(([leftKey], [rightKey]) => leftKey.localeCompare(rightKey))
    .map(([label, value]) => ({ label, value }));
}

function buildCounterpartEntityId(match: ErMatchDecision, subjectEntityId: string): string {
  if (match.entity_id_a === subjectEntityId) {
    return match.entity_id_b;
  }

  return match.entity_id_a;
}

export function buildErMatchSummaries(
  matches: ErMatchDecision[],
  subjectEntityId: string
): ErMatchSummaryRow[] {
  return matches.map((match) => ({
    counterpartEntityId: buildCounterpartEntityId(match, subjectEntityId),
    decision: match.decision,
    confidence: match.confidence.toFixed(2),
    decidedAt: match.decided_at
  }));
}

export function buildNeighborTitle(neighbor: GraphNeighbor): string {
  if (neighbor.name) {
    return neighbor.name;
  }

  return `${neighbor.entity_type} ${neighbor.entity_id}`;
}

export function buildGraphNeighborRows(neighbors: GraphNeighbor[]): GraphNeighborDisplayRow[] {
  return neighbors.map((neighbor) => {
    const route = classifyGraphNeighborRoute(neighbor);

    return {
      title: buildNeighborTitle(neighbor),
      entityType: neighbor.entity_type,
      relationshipType: neighbor.relationship_type,
      direction: neighbor.direction,
      href: route.href
    };
  });
}

export function getEmptyPanelMessage(panel: EmptyPanelKey): string {
  return EMPTY_PANEL_MESSAGES[panel];
}

function formatDateForTimeline(value: string | null): string {
  if (value === null) {
    return "—";
  }

  if (/^\d{4}-\d{2}-\d{2}/.test(value)) {
    return value.slice(0, 10);
  }

  return value;
}

function resolveDisplayLabel(value: string | null | undefined, fallback: string): string {
  if (typeof value !== "string") {
    return fallback;
  }

  const trimmed = value.trim();
  return trimmed === "" ? fallback : trimmed;
}

function compareDateDesc(left: string | null, right: string | null): number {
  if (left === right) {
    return 0;
  }
  if (left === null) {
    return 1;
  }
  if (right === null) {
    return -1;
  }

  return right.localeCompare(left);
}

/** Builds deterministic officeholding timeline rows for person detail pages. */
export function buildPersonOfficeholdingTimelineRows(
  officeholdings: OfficeholdingDetailResponse[],
  labelLookups: {
    officeholdingLabelsById?: Record<string, string>;
    officeLabelsById?: Record<string, string>;
  } = {}
): PersonOfficeholdingTimelineRow[] {
  return [...officeholdings]
    .sort((left, right) => {
      const lowerBoundOrder = compareDateDesc(left.valid_period_lower, right.valid_period_lower);
      if (lowerBoundOrder !== 0) {
        return lowerBoundOrder;
      }
      return left.id.localeCompare(right.id);
    })
    .map((officeholding) => ({
      officeholdingId: officeholding.id,
      officeholdingLabel: resolveDisplayLabel(
        labelLookups.officeholdingLabelsById?.[officeholding.id],
        DEFAULT_OFFICEHOLDING_LABEL
      ),
      officeholdingHref: buildOfficeholdingRoutePath(officeholding.id),
      officeLabel: resolveDisplayLabel(
        labelLookups.officeLabelsById?.[officeholding.office_id],
        DEFAULT_OFFICE_LABEL
      ),
      officeHref: buildOfficeRoutePath(officeholding.office_id),
      holderStatus: officeholding.holder_status,
      validFrom: formatDateForTimeline(officeholding.valid_period_lower),
      validThrough: officeholding.valid_period_upper === null ? "Present" : formatDateForTimeline(officeholding.valid_period_upper)
    }));
}

/** Builds deterministic candidacy rows for person detail pages. */
export function buildPersonCandidacyRows(
  candidacies: CandidacyDetailResponse[],
  labelLookups: {
    candidacyLabelsById?: Record<string, string>;
    contestLabelsById?: Record<string, string>;
  } = {}
): PersonCandidacyRow[] {
  return [...candidacies]
    .sort((left, right) => {
      const filingDateOrder = compareDateDesc(left.filing_date, right.filing_date);
      if (filingDateOrder !== 0) {
        return filingDateOrder;
      }
      return left.id.localeCompare(right.id);
    })
    .map((candidacy) => ({
      candidacyId: candidacy.id,
      candidacyLabel: resolveDisplayLabel(
        labelLookups.candidacyLabelsById?.[candidacy.id],
        DEFAULT_CANDIDACY_LABEL
      ),
      candidacyHref: buildCandidacyRoutePath(candidacy.id),
      contestLabel: resolveDisplayLabel(
        labelLookups.contestLabelsById?.[candidacy.contest_id],
        DEFAULT_CONTEST_LABEL
      ),
      contestHref: buildContestRoutePath(candidacy.contest_id),
      filingDate: formatDateForTimeline(candidacy.filing_date),
      party: formatDisplayValue(candidacy.party),
      status: formatDisplayValue(candidacy.status),
      incumbentChallenge: formatDisplayValue(candidacy.incumbent_challenge)
    }));
}

function parseMoney(value: SerializedMoney): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

/** Converts candidate fundraising totals into shared chart-series input. */
export function buildPersonSummaryChartSeries(summary: {
  total_raised: SerializedMoney;
  total_spent: SerializedMoney;
  net: SerializedMoney;
}): ChartSeries[] {
  return [
    {
      id: "finance",
      label: "Finance",
      points: [
        { x: "Raised", y: parseMoney(summary.total_raised) },
        { x: "Spent", y: parseMoney(summary.total_spent) },
        { x: "Net", y: parseMoney(summary.net) }
      ]
    }
  ];
}

/** Converts IE support/oppose totals into shared chart-series input. */
export function buildPersonOutsideSpendingChartSeries(summary: {
  support_total: SerializedMoney;
  oppose_total: SerializedMoney;
} | null): ChartSeries[] {
  if (summary === null) {
    return [];
  }

  return [
    {
      id: "outside-spending",
      label: "Outside spending",
      points: [
        { x: "Support", y: parseMoney(summary.support_total) },
        { x: "Oppose", y: parseMoney(summary.oppose_total) }
      ]
    }
  ];
}

/** Delegates person finance summary formatting to the shared finance owner. */
export function buildPersonFinanceSummaryPresentation(
  summary: CandidateFundraisingSummary
): CandidateAggregateSummaryPresentation {
  return buildCandidateDeferredFundraisingSummary(summary);
}

/** Delegates linked-committee row formatting to the shared finance owner. */
export function buildPersonLinkedCommitteeRows(
  summary: CandidateFundraisingSummary
): CandidateCommitteeBreakdownRow[] {
  return buildCandidateCommitteeBreakdown(summary);
}

/** Delegates donor/vendor transaction formatting to the shared finance owner. */
export function buildPersonDonorVendorRows(
  transactions: CampaignFinanceTransactionResponse[]
): CommitteeTransactionRow[] {
  return buildCommitteeDeferredTransactionRows(transactions, {});
}

export function buildPersonLinkedCommitteeEmptyStateBanner(linkedCommitteeCount: number): string | null {
  return buildLinkedCommitteeEmptyStateBanner(linkedCommitteeCount);
}

export function buildPersonDonorVendorEmptyStateBanner(donorVendorTransactionCount: number): string | null {
  return buildDonorVendorEmptyStateBanner(donorVendorTransactionCount);
}

/** Delegates IE section formatting to the shared finance owner. */
export function buildPersonOutsideSpendingSection(
  ieSummary: IndependentExpenditureSummary | null,
  ieTransactions: IndependentExpenditureResponse[]
): OutsideSpendingPresentation {
  return buildCandidateDeferredOutsideSpending(ieSummary, ieTransactions);
}

function buildKeyMetricRows(
  identifierCount: string,
  erMatchCount: string,
  graphRelationshipCount: string
): DetailFactRow[] {
  return [
    { label: "Identifiers", value: identifierCount },
    { label: "ER matches", value: erMatchCount },
    { label: "Graph relationships", value: graphRelationshipCount }
  ];
}

function buildLoadingKeyMetrics(identifierRows: DetailFactRow[]): DetailFactRow[] {
  return buildKeyMetricRows(
    String(identifierRows.length),
    LOADING_METRIC_VALUE,
    LOADING_METRIC_VALUE
  );
}

export function buildResolvedKeyMetrics(
  identifierRows: DetailFactRow[],
  matches: ErMatchDecision[],
  relationships: EntityGraphRelationshipsResponse
): DetailFactRow[] {
  return buildKeyMetricRows(
    String(identifierRows.length),
    String(matches.length),
    String(relationships.total_count)
  );
}

export function buildUnavailableKeyMetrics(identifierRows: DetailFactRow[]): DetailFactRow[] {
  return buildKeyMetricRows(
    String(identifierRows.length),
    UNAVAILABLE_METRIC_VALUE,
    UNAVAILABLE_METRIC_VALUE
  );
}

type CivicContext = {
  label: CivicContextLabel;
  name: string;
  href: string;
};

function buildCivicContext(neighbor: GraphNeighbor): CivicContext | null {
  if (neighbor.entity_type === "office") {
    return {
      label: "Office",
      name: buildNeighborTitle(neighbor),
      href: buildOfficeRoutePath(neighbor.entity_id)
    };
  }

  if (neighbor.entity_type === "contest") {
    return {
      label: "Contest",
      name: buildNeighborTitle(neighbor),
      href: buildContestRoutePath(neighbor.entity_id)
    };
  }

  return null;
}

function getPreferredCivicContext(
  contexts: CivicContext[],
  preferredLabel: CivicContextLabel
): CivicContext | null {
  const preferredContext = contexts.find((context) => context.label === preferredLabel);

  if (preferredContext !== undefined) {
    return preferredContext;
  }

  return contexts[0] ?? null;
}

function buildCivicRecordRows(neighbors: GraphNeighbor[]): CivicRecordRow[] {
  const contexts = neighbors
    .map((neighbor) => buildCivicContext(neighbor))
    .filter((context): context is CivicContext => context !== null);
  const contestContext = getPreferredCivicContext(contexts, "Contest");
  const officeContext = getPreferredCivicContext(contexts, "Office");

  return neighbors.flatMap((neighbor): CivicRecordRow[] => {
    if (neighbor.entity_type === "candidacy" && neighbor.relationship_type === "CANDIDACY_OF") {
      return [
        {
          recordType: "Candidacy" as const,
          recordName: buildNeighborTitle(neighbor),
          recordHref: buildCandidacyRoutePath(neighbor.entity_id),
          contextLabel: contestContext?.label ?? null,
          contextName: contestContext?.name ?? null,
          contextHref: contestContext?.href ?? null
        }
      ];
    }

    if (neighbor.entity_type === "officeholding" && neighbor.relationship_type === "HOLDS") {
      return [
        {
          recordType: "Officeholding" as const,
          recordName: buildNeighborTitle(neighbor),
          recordHref: buildOfficeholdingRoutePath(neighbor.entity_id),
          contextLabel: officeContext?.label ?? null,
          contextName: officeContext?.name ?? null,
          contextHref: officeContext?.href ?? null
        }
      ];
    }

    return [];
  });
}

export function buildCivicRecordSection(
  entityType: Stage4EntityType,
  neighbors: GraphNeighbor[]
): CivicRecordSection | null {
  if (entityType !== "person") {
    return null;
  }

  const rows = buildCivicRecordRows(neighbors);
  return {
    title: CIVIC_RECORD_TITLE,
    rows,
    emptyMessage: rows.length === 0 ? CIVIC_RECORD_EMPTY_MESSAGE : null
  };
}

export function buildTechnicalDisclosureSection(
  matches: ErMatchDecision[],
  neighbors: GraphNeighbor[],
  subjectEntityId: string
): TechnicalDisclosureSection {
  const matchRows = buildErMatchSummaries(matches, subjectEntityId);
  const neighborRows = buildGraphNeighborRows(neighbors);

  return {
    summary: TECHNICAL_DISCLOSURE_SUMMARY,
    matchRows,
    neighborRows,
    matchEmptyMessage: getOptionalEmptyMessage(matchRows, "matches"),
    neighborEmptyMessage: getOptionalEmptyMessage(neighborRows, "neighbors")
  };
}

export function buildEntityDetailShellPresentation(
  input: EntityDetailShellInput
): EntityDetailShellPresentation {
  const identifierRows = buildIdentifierRows(input.detail.identifiers);

  return {
    entityType: input.entityType,
    canonicalName: input.detail.canonical_name,
    sectionOrder: input.entityType === "person" ? PERSON_SECTION_ORDER : ORG_SECTION_ORDER,
    coreFactRows: buildCanonicalDetailFacts(input.entityType, input.detail),
    keyMetricRows: buildLoadingKeyMetrics(identifierRows),
    identifierRows,
    trustSection: buildTrustSection(input.detail.sources),
    identifierEmptyMessage: getOptionalEmptyMessage(identifierRows, "identifiers")
  };
}

export function buildEntityDetailPresentation(data: ResolvedEntityDetailBundle): EntityDetailPresentation {
  const identifierRows = buildIdentifierRows(data.detail.identifiers);
  const technicalDisclosure = buildTechnicalDisclosureSection(
    data.matches,
    data.relationships.neighbors,
    data.detail.id
  );
  const civicRecordSection = buildCivicRecordSection(data.entityType, data.relationships.neighbors);

  return {
    entityType: data.entityType,
    canonicalName: data.detail.canonical_name,
    sectionOrder: data.entityType === "person" ? PERSON_SECTION_ORDER : ORG_SECTION_ORDER,
    coreFactRows: buildCanonicalDetailFacts(data.entityType, data.detail),
    keyMetricRows: buildResolvedKeyMetrics(identifierRows, data.matches, data.relationships),
    identifierRows,
    trustSection: buildTrustSection(data.detail.sources),
    matchRows: technicalDisclosure.matchRows,
    neighborRows: technicalDisclosure.neighborRows,
    civicRecordSection,
    technicalDisclosure,
    identifierEmptyMessage: getOptionalEmptyMessage(identifierRows, "identifiers"),
    matchEmptyMessage: technicalDisclosure.matchEmptyMessage,
    neighborEmptyMessage: technicalDisclosure.neighborEmptyMessage
  };
}
