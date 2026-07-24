/** View-model builders for campaign-finance detail pages and route chooser states. */
import { buildEntityRouteHref } from "$lib/entity-detail/contract";
import {
  buildTrustSection,
  type TrustSectionViewModel
} from "$lib/detail-trust/presentation";
import { formatCountLabel } from "$lib/count-label";
import {
  buildCandidateHref,
  buildCommitteeHref,
  buildFilingDetailPath
} from "$lib/campaign-finance-detail/contract";
import { sanitizeExternalUrl } from "$lib/url/sanitize-external-url";
import {
  buildPaginationContext,
  type PaginationContext
} from "$lib/campaign-finance-detail/list-presentation";
import type { CashOnHandPoint, ChartSource, OutsideSpendingRow } from "$lib/charts/types";
import type {
  CandidateDetailResponse,
  CandidateListItem,
  CampaignFinanceTransactionResponse,
  CommitteeDetailResponse,
  CommitteeFilingBreakdown,
  CandidateFundraisingSummary,
  CommitteeFundraisingSummary,
  CommitteeIndependentExpenditureActivity,
  CommitteeIndependentExpenditureTarget,
  CommitteeListItem,
  IndependentExpenditureResponse,
  IndependentExpenditureSummary,
  SerializedMoney
} from "$lib/campaign-finance-detail/contract";
import type { CandidateDetailBundle, CommitteeDetailBundle } from "$lib/server/api/campaign-finance-detail";
export {
  CANDIDATE_SUMMARY_SOURCE_LABELS,
  COMMITTEE_SUMMARY_SOURCE_LABELS,
  buildCommitteeItemizedCoverageNote
} from "$lib/campaign-finance-detail/summary-source";
import {
  CANDIDATE_SUMMARY_SOURCE_LABELS,
  COMMITTEE_SUMMARY_SOURCE_LABELS,
  buildCommitteeItemizedCoverageNote
} from "$lib/campaign-finance-detail/summary-source";

export type CampaignFinanceFactRow = {
  label: string;
  value: string;
  href: string | null;
};

/**
 */
export type CommitteeTransactionRow = {
  id: string;
  date: string;
  amount: string;
  transactionType: string;
  contributorName: string;
  contributorPersonHref: string | null;
  contributorPersonLabel: string | null;
  contributorOrgHref: string | null;
  contributorOrgLabel: string | null;
  recipientCandidateHref: string | null;
  recipientCandidateLabel: string | null;
  recipientCommitteeHref: string | null;
  recipientCommitteeLabel: string | null;
  ieStance: string;
  disseminationDate: string;
  aggregateAmount: string;
};

export type LabelValueRow = {
  label: string;
  value: string;
};

export type RankedPartyRow = {
  name: string;
  totalAmount: string;
  transactionCountLabel: string;
};

export type SpendCategoryRow = {
  category: string;
  totalAmount: string;
  transactionCountLabel: string;
};

export type CommitteeHighSignalSummaryPresentation = {
  receiptSplit: LabelValueRow[];
  topDonors: RankedPartyRow[];
  topVendors: RankedPartyRow[];
  spendCategories: SpendCategoryRow[];
  spendCategoriesEmptyMessage: string | null;
  cashOnHandTrend: CommitteeCashOnHandTrendFigure;
};

export type CommitteeCashOnHandTrendFigure = {
  cycle: number;
  coverageThrough: string | null;
  sources: ChartSource[];
  points: CashOnHandPoint[];
};

export type FundraisingSummaryPresentation = {
  totalRaised: string;
  totalSpent: string;
  net: string;
  transactionCount: number;
  jurisdiction: string;
  dataThrough: string;
  summarySourceLabel: string;
  itemizedCoverageNote: string;
};

export type CommitteeCycleSummaryRow = {
  cycle: number;
  cycleLabel: string;
  coveragePeriod: string;
  totalReceipts: string;
  totalDisbursements: string;
  cashOnHand: string;
};

export type LinkedCandidateLink = {
  candidateId: string;
  name: string;
  context: string;
  href: string;
};

export type FilingBreakdownRowPresentation = {
  filingId: string;
  filingFecId: string;
  filingName: string;
  reportType: string;
  amendmentIndicator: string;
  coveragePeriod: string;
  receiptDate: string;
  totalReceipts: string;
  totalDisbursements: string;
  cashOnHand: string;
  transactionCount: number;
};

/** Client-paginated slice of the newest-first filing window for the detail table. */
export type PaginatedFilingBreakdownPresentation = {
  rows: FilingBreakdownRowPresentation[];
  emptyMessage: string | null;
  normalizedOffset: number;
  pagination: PaginationContext;
  label: string | null;
};

export type KeyMetric = {
  label: string;
  value: string;
};

export type CommitteeDetailShellPresentation = {
  canonicalName: string;
  factRows: CampaignFinanceFactRow[];
  trustSection: TrustSectionViewModel;
  sectionOrder: string[];
  committeeRouteRef: CommitteeTransactionRouteReferences;
  linkedCandidates: LinkedCandidateLink[];
};

export type CandidateAggregateSummaryPresentation = {
  totalReceipts: string;
  totalDisbursements: string;
  cashOnHand: string;
  debtsOwedByCommittee: string;
  itemizedTransactions: number;
  selectedCycle: number;
  coveragePeriod: string;
  summarySourceLabel: string;
  factRows: KeyMetric[];
};

export type CandidateCommitteeBreakdownRow = {
  committeeId: string;
  committeeName: string;
  committeeHref: string;
  totalReceipts: string;
  totalDisbursements: string;
  cashOnHand: string;
  debtsOwedByCommittee: string;
  itemizedTransactions: number;
  totalRaised: string;
  totalSpent: string;
  net: string;
  transactionCount: number;
  jurisdiction: string;
  dataThrough: string;
  factRows: KeyMetric[];
};

export type OutsideSpendingTopSpenderRow = {
  committeeName: string;
  committeeHref: string;
  stance: string;
  totalAmount: string;
  transactionCountLabel: string;
};

export type OutsideSpendingTransactionRow = {
  rowKey: string;
  date: string;
  disseminationDate: string;
  spender: string;
  spenderHref: string;
  stance: string;
  amount: string;
  sourceHref: string | null;
};

export type OutsideSpendingPresentation = {
  supportTotal: string;
  opposeTotal: string;
  supportCountLabel: string;
  opposeCountLabel: string;
  topSpenders: OutsideSpendingTopSpenderRow[];
  chartRows: OutsideSpendingRow[];
  chartTopSpenders: OutsideSpendingRow[];
  explanatoryBlock: string | null;
  transactionRows: OutsideSpendingTransactionRow[];
  emptyMessage: string | null;
};

export type CandidateOutsideSpendingFigure = {
  cycle: number;
  coverageThrough: string | null;
  rows: OutsideSpendingRow[];
  topSpenders: OutsideSpendingRow[];
  sources: ChartSource[];
};

export type CommitteeOutsideSpendingTargetRow = {
  rowKey: string;
  candidateName: string;
  targetHref: string | null;
  context: string;
  supportTotal: string;
  opposeTotal: string;
  transactionCountLabel: string;
};

export type CommitteeOutsideSpendingSourceRow = {
  rowKey: string;
  candidateName: string;
  sourceName: string;
  sourceRecordKey: string;
  href: string | null;
};

export type CommitteeOutsideSpendingPresentation = {
  supportTotal: string;
  opposeTotal: string;
  ieCountLabel: string;
  outlierNote: string | null;
  targetRows: CommitteeOutsideSpendingTargetRow[];
  sourceRows: CommitteeOutsideSpendingSourceRow[];
  emptyMessage: string | null;
};

export type CandidateDetailShellPresentation = {
  canonicalName: string;
  identityQualifier: string | null;
  jsonLdName: string | null;
  factRows: CampaignFinanceFactRow[];
  trustSection: TrustSectionViewModel;
  sectionOrder: string[];
  l10Reference: CandidateL10Reference | null;
};

export type CandidateL10Reference = {
  totalRaised: SerializedMoney;
  sourceLabel: string;
  methodologyHref: string;
  deviationThresholdRatio: number;
};

export type CandidateCompletenessWarning = {
  message: string;
  methodologyHref: string;
};

export type CampaignFinanceDetailMetadata = {
  title: string;
  description: string;
};

export type SlugCollisionMatchPresentation = {
  id: string;
  name: string;
  href: string;
};

type Deferred<T> = T | Promise<T>;

export type CandidateCanonicalDetailRoutePresentation = {
  routeKind: "canonical-detail";
  entityType: "candidate";
  shell: CandidateDetailShellPresentation;
  summary: Deferred<CandidateFundraisingSummary>;
  ieTransactions: Deferred<IndependentExpenditureResponse[]>;
  ieSummary: Deferred<IndependentExpenditureSummary | null>;
};

export type CommitteeCanonicalDetailRoutePresentation = {
  routeKind: "canonical-detail";
  entityType: "committee";
  shell: CommitteeDetailShellPresentation;
  transactions: Deferred<CampaignFinanceTransactionResponse[]>;
  summary: Deferred<CommitteeFundraisingSummary>;
  filingBreakdown: CommitteeFilingBreakdown | null;
  independentExpendituresMade: Deferred<CommitteeIndependentExpenditureActivity>;
};

type CandidateSlugCollisionRoutePresentation = {
  routeKind: "slug-collision";
  entityType: "candidate";
  slug: string;
  heading: string;
  chooserLabel: string;
  matches: SlugCollisionMatchPresentation[];
};

type CommitteeSlugCollisionRoutePresentation = {
  routeKind: "slug-collision";
  entityType: "committee";
  slug: string;
  heading: string;
  chooserLabel: string;
  matches: SlugCollisionMatchPresentation[];
};

export type CandidateDetailRoutePresentation =
  | CandidateCanonicalDetailRoutePresentation
  | CandidateSlugCollisionRoutePresentation;

export type CommitteeDetailRoutePresentation =
  | CommitteeCanonicalDetailRoutePresentation
  | CommitteeSlugCollisionRoutePresentation;

export type CampaignFinanceDetailRoutePresentation =
  | CandidateDetailRoutePresentation
  | CommitteeDetailRoutePresentation;

export type CandidateRouteData =
  | ({ routeKind: "canonical-detail" } & CandidateDetailBundle & CandidateCanonicalRouteDataExtras)
  | {
      routeKind: "slug-collision";
      slug: string;
      matches: CandidateListItem[];
    };

type CandidateCanonicalRouteDataExtras = {
  keelL10Reference?: CandidateL10Reference | null;
};

type CandidateDetailL10Extras = {
  keel_l10_reference?: CandidateL10Reference | null;
};

export type CommitteeRouteData =
  | ({ routeKind: "canonical-detail" } & CommitteeDetailBundle)
  | {
      routeKind: "slug-collision";
      slug: string;
      matches: CommitteeListItem[];
    };

const COMMITTEE_TRANSACTION_EMPTY_MESSAGE = "No recent committee transactions found.";
const EMPTY_FILING_BREAKDOWN_MESSAGE = "No filing-period fundraising data available.";
const OUTSIDE_SPENDING_UNAVAILABLE_MESSAGE =
  "Outside-spending data is not yet available for this candidate. Coverage may be incomplete.";
const OUTSIDE_SPENDING_NO_ACTIVITY_MESSAGE =
  "No outside spending is reported in available filings. Coverage may be incomplete.";
export const CANDIDATE_IE_NOT_LOADED_MESSAGE =
  "FEC Schedule E independent-expenditure coverage is not yet available for this candidate and cycle.";
export const CANDIDATE_METHODOLOGY_HREF = "/methodology";
const COMMITTEE_OUTSIDE_SPENDING_EMPTY_MESSAGE =
  "This committee reported no independent expenditures";
const COMMITTEE_SPEND_CATEGORIES_UNAVAILABLE_MESSAGE =
  "Spend categories are not available for this committee.";
const CANDIDATE_EMPTY_COMPLETENESS_WARNING =
  "No transactions loaded for this candidate yet. Coverage may be incomplete.";
const PERSON_RECORD_LINK_VALUE_PREFIX = "Person record";
const ORGANIZATION_RECORD_LINK_VALUE_PREFIX = "Organization record";
const COMMITTEE_RECORD_LINK_VALUE_PREFIX = "Committee record";
const CONTRIBUTOR_PERSON_LINK_LABEL = "View contributor person record";
const CONTRIBUTOR_ORG_LINK_LABEL = "View contributor organization record";
const RECIPIENT_CANDIDATE_LINK_LABEL = "View recipient candidate record";
const RECIPIENT_COMMITTEE_LINK_LABEL = "View recipient committee record";
const CURRENCY_FORMATTER = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2
});
const INTEGER_FORMATTER = new Intl.NumberFormat("en-US");

/** Rows shown per full filing-table page; the final page renders the remainder. */
export const COMMITTEE_FILINGS_PAGE_SIZE = 25;

function formatRowValue(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }

  return value;
}

function resolveCanonicalName(rawName: string, fallbackLabel: "Candidate" | "Committee"): string {
  const trimmedName = rawName.trim();
  return trimmedName === "" ? fallbackLabel : trimmedName;
}

function parseSerializedMoney(value: SerializedMoney | number): number {
  return typeof value === "number" ? value : Number(value);
}

function parseFiniteSerializedMoney(value: SerializedMoney | number | null): number | null {
  if (value === null) {
    return null;
  }

  const parsedValue = parseSerializedMoney(value);
  return Number.isFinite(parsedValue) ? parsedValue : null;
}

function formatOptionalCurrency(value: SerializedMoney | null | undefined): string {
  return value === null || value === undefined ? "Not available" : formatCurrency(value);
}

function formatDateValue(value: string | null): string {
  if (!value) {
    return "—";
  }

  if (/^\d{4}-\d{2}-\d{2}/.test(value)) {
    return value.slice(0, 10);
  }

  return value;
}

/** Formats filing coverage ranges while handling open-ended or missing bounds. */
function buildCoveragePeriodLabel(startDate: string | null, endDate: string | null): string {
  const formattedStartDate = formatDateValue(startDate);
  const formattedEndDate = formatDateValue(endDate);

  if (formattedStartDate === "—" && formattedEndDate === "—") {
    return "—";
  }

  if (formattedStartDate === "—") {
    return `through ${formattedEndDate}`;
  }

  if (formattedEndDate === "—") {
    return `from ${formattedStartDate}`;
  }

  return `${formattedStartDate} to ${formattedEndDate}`;
}

function parseIsoDateOnly(value: string | null): Date | null {
  if (value === null || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return null;
  }

  const parsedDate = new Date(`${value}T00:00:00.000Z`);
  return Number.isNaN(parsedDate.getTime()) ? null : parsedDate;
}

function hasCoverageGap(previousEndDate: string | null, nextStartDate: string | null): boolean {
  const previousEnd = parseIsoDateOnly(previousEndDate);
  const nextStart = parseIsoDateOnly(nextStartDate);

  if (previousEnd === null || nextStart === null) {
    return false;
  }

  const nextExpectedStart = new Date(previousEnd);
  nextExpectedStart.setUTCDate(nextExpectedStart.getUTCDate() + 1);
  return nextStart.getTime() > nextExpectedStart.getTime();
}

export function formatCurrency(value: SerializedMoney | number): string {
  return CURRENCY_FORMATTER.format(parseSerializedMoney(value));
}

type NormalizedCommitteeFilingFact = {
  filing: CommitteeFilingBreakdown["filings"][number];
  originalIndex: number;
  coverageEndDate: string | null;
  cashOnHandAmount: number | null;
};

type FilingFactSortDirection = "chronological" | "newest-first";

/**
 */
function compareFilingFactsByCoverageEndDate(
  left: NormalizedCommitteeFilingFact,
  right: NormalizedCommitteeFilingFact,
  direction: FilingFactSortDirection
): number {
  if (left.coverageEndDate !== null && right.coverageEndDate !== null) {
    const chronologicalDateComparison =
      left.coverageEndDate.localeCompare(right.coverageEndDate);
    if (chronologicalDateComparison !== 0) {
      return direction === "chronological"
        ? chronologicalDateComparison
        : -chronologicalDateComparison;
    }

    return left.originalIndex - right.originalIndex;
  }

  if (left.coverageEndDate !== null) {
    return -1;
  }

  if (right.coverageEndDate !== null) {
    return 1;
  }

  return left.originalIndex - right.originalIndex;
}

/**
 */
function buildNormalizedCommitteeFilingFacts(
  filingBreakdown: CommitteeFilingBreakdown
): NormalizedCommitteeFilingFact[] {
  return filingBreakdown.filings
    .map((filing, originalIndex) => ({
      filing,
      originalIndex,
      coverageEndDate: parseIsoDateOnly(filing.coverage_end_date) === null ? null : filing.coverage_end_date,
      cashOnHandAmount: parseFiniteSerializedMoney(filing.cash_on_hand)
    }))
    .sort((left, right) => compareFilingFactsByCoverageEndDate(left, right, "chronological"));
}

/**
 */
function buildCashOnHandTrendPoints(filingFacts: NormalizedCommitteeFilingFact[]): CashOnHandPoint[] {
  const points: CashOnHandPoint[] = [];
  let previousPointFact: NormalizedCommitteeFilingFact | null = null;

  for (const fact of filingFacts) {
    if (fact.coverageEndDate === null || fact.cashOnHandAmount === null) {
      continue;
    }

    points.push({
      periodEnd: fact.coverageEndDate,
      amount: fact.cashOnHandAmount,
      missingIntervalBefore:
        previousPointFact === null
          ? false
          : hasCoverageGap(previousPointFact.filing.coverage_end_date, fact.filing.coverage_start_date)
    });
    previousPointFact = fact;
  }

  return points;
}

export function buildCandidateAggregateSummaryPresentation(
  summary: CandidateFundraisingSummary
): CandidateAggregateSummaryPresentation {
  const totalReceipts = formatCurrency(summary.total_raised);
  const totalDisbursements = formatCurrency(summary.total_spent);
  const cashOnHand = formatOptionalCurrency(summary.cash_on_hand);
  const debtsOwedByCommittee = formatOptionalCurrency(summary.debts_owed_by_committee);
  const itemizedTransactions = summary.itemized_transaction_count;
  const selectedCycle = summary.selected_cycle;
  const coveragePeriod = buildCoveragePeriodLabel(summary.coverage_start_date, summary.coverage_end_date);
  const summarySourceLabel = CANDIDATE_SUMMARY_SOURCE_LABELS[summary.summary_source];

  return {
    totalReceipts,
    totalDisbursements,
    cashOnHand,
    debtsOwedByCommittee,
    itemizedTransactions,
    selectedCycle,
    coveragePeriod,
    summarySourceLabel,
    factRows: [
      { label: "Total receipts", value: totalReceipts },
      { label: "Total disbursements", value: totalDisbursements },
      { label: "Cash on hand", value: cashOnHand },
      { label: "Debts owed by the committee", value: debtsOwedByCommittee },
      { label: "Itemized transactions", value: String(itemizedTransactions) },
      { label: "Selected cycle", value: String(selectedCycle) },
      { label: "Coverage", value: coveragePeriod },
      { label: "Source", value: summarySourceLabel }
    ]
  };
}

export function buildFundraisingSummaryPresentation(
  summary: CommitteeFundraisingSummary
): FundraisingSummaryPresentation {
  return {
    totalRaised: formatCurrency(summary.total_raised),
    totalSpent: formatCurrency(summary.total_spent),
    net: formatCurrency(summary.net),
    transactionCount: summary.transaction_count,
    jurisdiction: formatRowValue(summary.jurisdiction),
    dataThrough: formatDateValue(summary.data_through),
    summarySourceLabel: COMMITTEE_SUMMARY_SOURCE_LABELS[summary.summary_source],
    itemizedCoverageNote: buildCommitteeItemizedCoverageNote(summary)
  };
}

export function buildCommitteeCycleSummaryRows(
  summary: CommitteeFundraisingSummary
): CommitteeCycleSummaryRow[] {
  return summary.cycle_summaries.map((cycle) => ({
    cycle: cycle.cycle,
    cycleLabel: String(cycle.cycle),
    coveragePeriod: buildCoveragePeriodLabel(cycle.coverage_start_date, cycle.coverage_end_date),
    totalReceipts: formatCurrency(cycle.total_receipts),
    totalDisbursements: formatCurrency(cycle.total_disbursements),
    cashOnHand: cycle.cash_on_hand === null ? "—" : formatCurrency(cycle.cash_on_hand)
  }));
}

type CandidateContextSource = {
  office: string;
  state: string | null;
  district: string | null;
  party: string | null;
};

function buildCandidateContext(candidate: CandidateContextSource): string {
  const parts: string[] = [];
  parts.push(candidate.office);
  if (candidate.state !== null && candidate.state !== "") {
    parts.push(candidate.state);
  }
  if (candidate.district !== null && candidate.district !== "") {
    parts.push(`District ${candidate.district}`);
  }
  if (candidate.party !== null && candidate.party !== "") {
    parts.push(candidate.party);
  }
  return parts.join(" · ");
}

function buildLinkedCandidateContext(candidate: CandidateListItem): string {
  return buildCandidateContext(candidate);
}

export function buildLinkedCandidateLinks(detail: CommitteeDetailResponse): LinkedCandidateLink[] {
  return detail.linked_candidates.map((candidate) => ({
    candidateId: candidate.id,
    name: candidate.name,
    context: buildLinkedCandidateContext(candidate),
    href: buildCandidateHref(candidate)
  }));
}

/** Maps one normalized filing fact into a table-ready presentation row. */
function buildFilingBreakdownRow(fact: NormalizedCommitteeFilingFact): FilingBreakdownRowPresentation {
  const { filing, cashOnHandAmount } = fact;
  return {
    filingId: filing.filing_id,
    filingFecId: filing.filing_fec_id,
    filingName: formatRowValue(filing.filing_name),
    reportType: formatRowValue(filing.report_type),
    amendmentIndicator: filing.amendment_indicator,
    coveragePeriod: buildCoveragePeriodLabel(filing.coverage_start_date, filing.coverage_end_date),
    receiptDate: formatDateValue(filing.receipt_date),
    totalReceipts: formatCurrency(filing.total_raised),
    totalDisbursements: formatCurrency(filing.total_spent),
    cashOnHand: cashOnHandAmount === null ? "—" : formatCurrency(cashOnHandAmount),
    transactionCount: filing.transaction_count
  };
}

/**
 * Resolves the raw `filings_offset` query value to a page-aligned, in-window offset.
 * Missing, empty, nonnumeric, fractional, explicitly signed, and negative values
 * resolve to `0`; valid positives round down to the nearest page boundary and clamp
 * to the last non-empty page (or `0` for an empty window).
 */
function normalizeFilingsOffset(
  rawOffset: string | null | undefined,
  paginableRecentCount: number
): number {
  const lastPageBoundary =
    paginableRecentCount === 0
      ? 0
      : Math.floor((paginableRecentCount - 1) / COMMITTEE_FILINGS_PAGE_SIZE) *
        COMMITTEE_FILINGS_PAGE_SIZE;

  if (typeof rawOffset !== "string" || !/^\d+$/.test(rawOffset)) {
    return 0;
  }

  const parsedOffset = Number(rawOffset);
  if (!Number.isFinite(parsedOffset)) {
    // Digit-only positive offset beyond JS numeric range: a beyond-window value, so
    // clamp to the last non-empty page rather than resetting to the first page.
    return lastPageBoundary;
  }

  const pageAlignedOffset =
    Math.floor(parsedOffset / COMMITTEE_FILINGS_PAGE_SIZE) * COMMITTEE_FILINGS_PAGE_SIZE;

  return Math.min(pageAlignedOffset, lastPageBoundary);
}

/** Composes the honest recent-window vs all-time filing label from the shared range math. */
function buildFilingRangeLabel(
  rangeLabel: string,
  paginableRecentCount: number,
  allTimeCount: number
): string {
  return (
    `${rangeLabel} of ${INTEGER_FORMATTER.format(paginableRecentCount)} most recent ` +
    `· ${INTEGER_FORMATTER.format(allTimeCount)} total filings`
  );
}

/**
 * Builds one client-paginated 25-row slice of the newest-first filing window.
 *
 * The full recent window is already fetched, so pagination is derived purely from the
 * normalized offset, page size, and the paginable recent count — the backend `has_next`
 * flag is intentionally ignored here. The chronological trend keeps its own owner
 * (`buildCommitteeCashOnHandTrendFigure`) and is unaffected by the offset.
 */
export function buildPaginatedCommitteeFilingBreakdown(
  filingBreakdown: CommitteeFilingBreakdown,
  rawOffset: string | null | undefined
): PaginatedFilingBreakdownPresentation {
  const fetchedFilingCount = filingBreakdown.filings.length;
  const allTimeCount = filingBreakdown.total_filings ?? fetchedFilingCount;
  const paginableRecentCount = Math.min(
    filingBreakdown.total_filings ?? fetchedFilingCount,
    filingBreakdown.store_limit ?? fetchedFilingCount,
    fetchedFilingCount
  );

  const newestFirstFacts = buildNormalizedCommitteeFilingFacts(filingBreakdown)
    .slice()
    .sort((left, right) => compareFilingFactsByCoverageEndDate(left, right, "newest-first"))
    .slice(0, paginableRecentCount);

  const normalizedOffset = normalizeFilingsOffset(rawOffset, paginableRecentCount);
  const pageRows = newestFirstFacts
    .slice(normalizedOffset, normalizedOffset + COMMITTEE_FILINGS_PAGE_SIZE)
    .map(buildFilingBreakdownRow);

  const hasNext = normalizedOffset + COMMITTEE_FILINGS_PAGE_SIZE < paginableRecentCount;
  const pagination = buildPaginationContext(
    normalizedOffset,
    COMMITTEE_FILINGS_PAGE_SIZE,
    hasNext,
    pageRows.length
  );

  if (paginableRecentCount === 0) {
    return {
      rows: pageRows,
      emptyMessage: EMPTY_FILING_BREAKDOWN_MESSAGE,
      normalizedOffset,
      pagination,
      label: null
    };
  }

  return {
    rows: pageRows,
    emptyMessage: null,
    normalizedOffset,
    pagination,
    label: buildFilingRangeLabel(pagination.label, paginableRecentCount, allTimeCount)
  };
}

function buildOptionalEntityHref(entityType: string, entityId: string | null): string | null {
  return entityId === null ? null : buildEntityRouteHref(entityType, entityId);
}

type SlugRoutableReference = {
  id: string;
  slug: string;
  slug_is_unique: boolean;
};

type CandidateSlugRoutableReference = SlugRoutableReference & {
  identity_is_safe: boolean;
};

export type CommitteeTransactionRouteReferences = {
  candidateById?: Record<string, CandidateSlugRoutableReference>;
  committeeById?: Record<string, SlugRoutableReference>;
};

function buildFallbackSlugReference(routeId: string): SlugRoutableReference {
  return {
    id: routeId,
    slug: routeId,
    slug_is_unique: false
  };
}

function buildFallbackCandidateSlugReference(routeId: string): CandidateSlugRoutableReference {
  return {
    id: routeId,
    slug: routeId,
    slug_is_unique: false,
    identity_is_safe: false
  };
}

function buildOptionalSlugRouteHref(
  routeId: string | null,
  routeReferences: Record<string, SlugRoutableReference> | undefined,
  buildHref: (reference: SlugRoutableReference) => string
): string | null {
  if (routeId === null) {
    return null;
  }

  const reference = routeReferences?.[routeId] ?? buildFallbackSlugReference(routeId);
  return buildHref(reference);
}

function buildOptionalCandidateRouteHref(
  routeId: string | null,
  routeReferences: Record<string, CandidateSlugRoutableReference> | undefined
): string | null {
  if (routeId === null) {
    return null;
  }

  const reference = routeReferences?.[routeId] ?? buildFallbackCandidateSlugReference(routeId);
  return buildCandidateHref(reference);
}


export function buildCommitteeDetailMetadata(
  canonicalName: string
): CampaignFinanceDetailMetadata {
  return {
    title: `${canonicalName} | Committee | Civibus`,
    description: "Committee profile from campaign-finance records."
  };
}

export function buildCandidateDetailMetadata(
  shell: Pick<CandidateDetailShellPresentation, "canonicalName" | "jsonLdName">
): CampaignFinanceDetailMetadata {
  const title = shell.jsonLdName === null
    ? `${shell.canonicalName} | Civibus`
    : `${shell.canonicalName} | Candidate | Civibus`;

  return {
    title,
    description: "Candidate profile from campaign-finance records."
  };
}

export function buildCommitteeDetailMetadataFromBundle(
  data: CommitteeDetailBundle
): CampaignFinanceDetailMetadata {
  return buildCommitteeDetailMetadata(resolveCanonicalName(data.detail.name, "Committee"));
}

function buildReadableRecordLinkValue(recordLabel: string, entityId: string | null): string {
  if (entityId === null) {
    return "—";
  }

  return `${recordLabel} (${entityId})`;
}

function buildLinkFactRow(
  label: string,
  entityType: string,
  entityId: string | null,
  recordLabel: string
): CampaignFinanceFactRow {
  const href = buildOptionalEntityHref(entityType, entityId);

  return {
    label,
    value: buildReadableRecordLinkValue(recordLabel, entityId),
    href
  };
}

/** Formats committee fields and linked canonical records for the detail summary. */
export function buildCommitteeFactRows(detail: CommitteeDetailResponse): CampaignFinanceFactRow[] {
  return [
    { label: "Committee name", value: detail.name, href: null },
    { label: "FEC committee ID", value: detail.fec_committee_id, href: null },
    buildLinkFactRow(
      "Canonical organization",
      "org",
      detail.organization_id,
      ORGANIZATION_RECORD_LINK_VALUE_PREFIX
    ),
    { label: "Committee type", value: formatRowValue(detail.committee_type), href: null },
    { label: "Committee designation", value: formatRowValue(detail.committee_designation), href: null },
    { label: "Party", value: formatRowValue(detail.party), href: null },
    { label: "State", value: formatRowValue(detail.state), href: null },
    { label: "City", value: formatRowValue(detail.city), href: null },
    { label: "ZIP", value: formatRowValue(detail.zip_code), href: null },
    { label: "Treasurer", value: formatRowValue(detail.treasurer_name), href: null }
  ];
}

/** Formats candidate fields and linked canonical records for the detail summary. */
export function buildCandidateFactRows(detail: CandidateDetailResponse): CampaignFinanceFactRow[] {
  const nameLabel = detail.identity_is_safe ? "Candidate name" : "FEC-filed candidate name";
  return [
    { label: nameLabel, value: detail.name, href: null },
    { label: "FEC candidate ID", value: detail.fec_candidate_id, href: null },
    buildLinkFactRow("Canonical person", "person", detail.person_id, PERSON_RECORD_LINK_VALUE_PREFIX),
    buildLinkFactRow(
      "Principal committee",
      "committee",
      detail.principal_committee_id,
      COMMITTEE_RECORD_LINK_VALUE_PREFIX
    ),
    { label: "Party", value: formatRowValue(detail.party), href: null },
    { label: "Office", value: formatRowValue(detail.office), href: null },
    { label: "State", value: formatRowValue(detail.state), href: null },
    { label: "District", value: formatRowValue(detail.district), href: null },
    { label: "Incumbent/challenge", value: formatRowValue(detail.incumbent_challenge), href: null }
  ];
}

/** Maps raw committee transactions into linked rows for the records table. */
export function buildCommitteeTransactionRows(
  transactions: CampaignFinanceTransactionResponse[],
  routeReferences: CommitteeTransactionRouteReferences = {}
): CommitteeTransactionRow[] {
  return transactions.map((transaction) => ({
    id: transaction.id,
    date: formatRowValue(transaction.transaction_date),
    amount: transaction.amount.toFixed(2),
    transactionType: transaction.transaction_type,
    contributorName: formatRowValue(transaction.contributor_name_raw),
    contributorPersonHref: buildOptionalEntityHref("person", transaction.contributor_person_id),
    contributorPersonLabel:
      transaction.contributor_person_id === null ? null : CONTRIBUTOR_PERSON_LINK_LABEL,
    contributorOrgHref: buildOptionalEntityHref("org", transaction.contributor_organization_id),
    contributorOrgLabel:
      transaction.contributor_organization_id === null ? null : CONTRIBUTOR_ORG_LINK_LABEL,
    recipientCandidateHref: buildOptionalCandidateRouteHref(
      transaction.recipient_candidate_id,
      routeReferences.candidateById
    ),
    recipientCandidateLabel:
      transaction.recipient_candidate_id === null ? null : RECIPIENT_CANDIDATE_LINK_LABEL,
    recipientCommitteeHref: buildOptionalSlugRouteHref(
      transaction.recipient_committee_id,
      routeReferences.committeeById,
      buildCommitteeHref
    ),
    recipientCommitteeLabel:
      transaction.recipient_committee_id === null ? null : RECIPIENT_COMMITTEE_LINK_LABEL,
    ieStance: formatOptionalStanceLabel(transaction.support_oppose),
    disseminationDate: formatDateValue(transaction.dissemination_date ?? null),
    aggregateAmount:
      transaction.aggregate_amount === null || transaction.aggregate_amount === undefined
        ? "—"
        : formatCurrency(transaction.aggregate_amount)
  }));
}

export function getCampaignFinanceEmptyMessage(): string {
  return COMMITTEE_TRANSACTION_EMPTY_MESSAGE;
}

export function buildKeyMetrics(
  summary: { total_raised: SerializedMoney; total_spent: SerializedMoney; transaction_count: number }
): KeyMetric[] {
  return [
    { label: "Total raised", value: formatCurrency(summary.total_raised) },
    { label: "Total spent", value: formatCurrency(summary.total_spent) },
    { label: "Itemized transactions loaded", value: String(summary.transaction_count) }
  ];
}

export function buildRankedPartyRows(
  parties: { name: string; total_amount: SerializedMoney; transaction_count: number }[]
): RankedPartyRow[] {
  return parties.map((party) => ({
    name: party.name,
    totalAmount: formatCurrency(party.total_amount),
    transactionCountLabel: formatCountLabel(party.transaction_count, "transaction")
  }));
}

function buildSpendCategoryRows(
  categories: { category: string; total_amount: SerializedMoney; transaction_count: number }[]
): SpendCategoryRow[] {
  return categories.map((category) => ({
    category: category.category,
    totalAmount: formatCurrency(category.total_amount),
    transactionCountLabel: formatCountLabel(category.transaction_count, "transaction")
  }));
}

function buildCommitteeCashOnHandTrendFigure(
  summary: CommitteeFundraisingSummary,
  filingBreakdown: CommitteeFilingBreakdown
): CommitteeCashOnHandTrendFigure {
  const filingFacts = buildNormalizedCommitteeFilingFacts(filingBreakdown);

  return {
    cycle: summary.selected_cycle,
    coverageThrough: summary.coverage_end_date,
    sources: [],
    points: buildCashOnHandTrendPoints(filingFacts)
  };
}

/**
 */
export function buildCommitteeHighSignalSummaryPresentation(
  summary: CommitteeFundraisingSummary,
  filingBreakdown: CommitteeFilingBreakdown
): CommitteeHighSignalSummaryPresentation {
  const spendCategories = summary.spend_categories === null ? [] : buildSpendCategoryRows(summary.spend_categories);

  return {
    receiptSplit: [
      { label: "Cash receipts", value: formatCurrency(summary.cash_receipts_total) },
      { label: "In-kind receipts", value: formatCurrency(summary.in_kind_receipts_total) },
      { label: "Loans", value: formatCurrency(summary.loan_receipts_total) },
      { label: "Contributions", value: formatCurrency(summary.contribution_receipts_total) }
    ],
    topDonors: buildRankedPartyRows(summary.top_donors),
    topVendors: buildRankedPartyRows(summary.top_vendors),
    spendCategories,
    spendCategoriesEmptyMessage:
      summary.spend_categories === null ? COMMITTEE_SPEND_CATEGORIES_UNAVAILABLE_MESSAGE : null,
    cashOnHandTrend: buildCommitteeCashOnHandTrendFigure(summary, filingBreakdown)
  };
}

/**
 */
export function buildCommitteeDetailShellPresentation(
  detail: CommitteeDetailResponse
): CommitteeDetailShellPresentation {
  return {
    canonicalName: resolveCanonicalName(detail.name, "Committee"),
    factRows: buildCommitteeFactRows(detail),
    trustSection: buildTrustSection(detail.sources, { includeJurisdictionFreshnessNote: true }),
    sectionOrder: ["summary", "trust", "metrics", "outside-spending", "records"],
    committeeRouteRef: {
      committeeById: {
        [detail.id]: { id: detail.id, slug: detail.slug, slug_is_unique: detail.slug_is_unique }
      }
    },
    linkedCandidates: buildLinkedCandidateLinks(detail)
  };
}

/**
 */
export function buildCandidateDetailShellPresentation(
  detail: CandidateDetailResponse,
  options?: {
    l10Reference?: CandidateL10Reference | null;
  }
): CandidateDetailShellPresentation {
  const detailExtras = detail as CandidateDetailResponse & CandidateDetailL10Extras;
  const identityQualifier = detail.identity_is_safe
    ? null
    : "FEC-filed candidate name needs review.";
  const canonicalName = detail.identity_is_safe
    ? resolveCanonicalName(detail.name, "Candidate")
    : "Candidate record";

  return {
    canonicalName,
    identityQualifier,
    jsonLdName: detail.identity_is_safe ? canonicalName : null,
    factRows: buildCandidateFactRows(detail),
    trustSection: buildTrustSection(detail.sources, { includeJurisdictionFreshnessNote: true }),
    sectionOrder: ["summary", "trust", "metrics", "outside-spending", "records"],
    l10Reference: options?.l10Reference ?? detailExtras.keel_l10_reference ?? null
  };
}

export function buildCommitteeDeferredFundraisingSummary(
  summary: CommitteeFundraisingSummary
): FundraisingSummaryPresentation {
  return buildFundraisingSummaryPresentation(summary);
}

export function buildCommitteeDeferredTransactionRows(
  transactions: CampaignFinanceTransactionResponse[],
  routeReferences: CommitteeTransactionRouteReferences
): CommitteeTransactionRow[] {
  return buildCommitteeTransactionRows(transactions, routeReferences);
}

export function buildCommitteeDeferredKeyMetrics(summary: CommitteeFundraisingSummary): KeyMetric[] {
  return buildKeyMetrics(summary);
}

export function buildCommitteeDeferredHighSignalSummary(
  summary: CommitteeFundraisingSummary,
  filingBreakdown: CommitteeFilingBreakdown
): CommitteeHighSignalSummaryPresentation {
  return buildCommitteeHighSignalSummaryPresentation(summary, filingBreakdown);
}

export function buildCommitteeDeferredOutsideSpending(
  activity: CommitteeIndependentExpenditureActivity
): CommitteeOutsideSpendingPresentation {
  return buildCommitteeOutsideSpendingPresentation(activity);
}

export function buildCandidateDeferredFundraisingSummary(
  summary: CandidateFundraisingSummary
): CandidateAggregateSummaryPresentation {
  return buildCandidateAggregateSummaryPresentation(summary);
}

export function buildCandidateDeferredCommitteeBreakdown(
  summary: CandidateFundraisingSummary
): CandidateCommitteeBreakdownRow[] {
  return buildCandidateCommitteeBreakdown(summary);
}

export function buildCandidateDeferredOutsideSpending(
  ieSummary: IndependentExpenditureSummary | null,
  ieTransactions: IndependentExpenditureResponse[],
  selectedCycleOverride: number | null = null
): OutsideSpendingPresentation {
  return buildOutsideSpendingPresentation(
    selectOutsideSpendingSummaryForCycle(ieSummary, selectedCycleOverride),
    selectOutsideSpendingTransactionsForCycle(ieSummary, ieTransactions, selectedCycleOverride)
  );
}

export function buildCandidateDeferredOutsideSpendingFigure(
  ieSummary: IndependentExpenditureSummary | null,
  selectedCycleOverride: number | null = null
): CandidateOutsideSpendingFigure | null {
  return buildOutsideSpendingFigure(ieSummary, selectedCycleOverride);
}

export function buildCandidateDeferredKeyMetrics(summary: CandidateFundraisingSummary): KeyMetric[] {
  return [
    { label: "Total receipts", value: formatCurrency(summary.total_raised) },
    { label: "Total disbursements", value: formatCurrency(summary.total_spent) },
    { label: "Cash on hand", value: formatOptionalCurrency(summary.cash_on_hand) },
    {
      label: "Debts owed by the committee",
      value: formatOptionalCurrency(summary.debts_owed_by_committee)
    },
    { label: "Itemized transactions", value: String(summary.itemized_transaction_count) }
  ];
}

function hasNotLoadedFundraisingCoverage(summary: CandidateFundraisingSummary): boolean {
  return summary.coverage.activity_state === "not_loaded";
}

function _computeDeviationRatio(currentTotal: number, expectedTotal: number): number {
  if (expectedTotal === 0) {
    return currentTotal === 0 ? 0 : Number.POSITIVE_INFINITY;
  }

  return Math.abs(currentTotal - expectedTotal) / expectedTotal;
}

function sanitizeMethodologyHref(methodologyHref: string): string {
  if (methodologyHref.startsWith("/") && !methodologyHref.startsWith("//")) {
    return methodologyHref;
  }

  return sanitizeExternalUrl(methodologyHref) ?? "/methodology";
}

/**
 */
export function buildCandidateCompletenessWarnings(
  summary: CandidateFundraisingSummary,
  l10Reference: CandidateL10Reference | null
): CandidateCompletenessWarning[] {
  const warnings: CandidateCompletenessWarning[] = [];

  if (hasNotLoadedFundraisingCoverage(summary)) {
    warnings.push({
      message: CANDIDATE_EMPTY_COMPLETENESS_WARNING,
      methodologyHref: CANDIDATE_METHODOLOGY_HREF
    });
  }

  if (l10Reference !== null) {
    const currentTotalRaised = parseSerializedMoney(summary.total_raised);
    const referenceTotalRaised = parseSerializedMoney(l10Reference.totalRaised);
    const deviationRatio = _computeDeviationRatio(currentTotalRaised, referenceTotalRaised);

    if (deviationRatio > l10Reference.deviationThresholdRatio) {
      warnings.push({
        message:
          `Civibus shows ${formatCurrency(currentTotalRaised)} raised, ` +
          `but the ${l10Reference.sourceLabel} reference is ${formatCurrency(referenceTotalRaised)}. ` +
          "Coverage may be incomplete.",
        methodologyHref: sanitizeMethodologyHref(l10Reference.methodologyHref)
      });
    }
  }

  return warnings;
}

function formatStanceLabel(stance: "S" | "O"): string {
  return stance === "S" ? "Support" : "Oppose";
}

function formatOptionalStanceLabel(stance: "S" | "O" | null | undefined): string {
  if (stance === "S" || stance === "O") {
    return formatStanceLabel(stance);
  }

  return "—";
}

const OUTSIDE_SPENDING_EXPLANATORY_BLOCK =
  "Outside spending is independent and not controlled by the candidate committee.";

function buildLoadedZeroOutsideSpendingPresentation(
  ieSummary: IndependentExpenditureSummary
): OutsideSpendingPresentation {
  return {
    supportTotal: formatCurrency(ieSummary.support_total),
    opposeTotal: formatCurrency(ieSummary.oppose_total),
    supportCountLabel: formatCountLabel(ieSummary.support_count, "expenditure"),
    opposeCountLabel: formatCountLabel(ieSummary.oppose_count, "expenditure"),
    topSpenders: [],
    chartRows: [],
    chartTopSpenders: [],
    explanatoryBlock: OUTSIDE_SPENDING_EXPLANATORY_BLOCK,
    transactionRows: [],
    emptyMessage: null
  };
}

/** Formats IE transactions for the outside-spending table shown on candidate pages. */
function buildOutsideSpendingTransactionRows(
  ieTransactions: IndependentExpenditureResponse[]
): OutsideSpendingTransactionRow[] {
  return ieTransactions.map((tx) => ({
    rowKey: tx.id,
    date: formatDateValue(tx.transaction_date),
    disseminationDate: formatDateValue(tx.dissemination_date),
    spender: tx.committee_name,
    spenderHref: buildCommitteeHref({
      id: tx.committee_id,
      slug: tx.committee_id,
      slug_is_unique: false
    }),
    stance: formatStanceLabel(tx.support_oppose),
    amount: formatCurrency(tx.amount),
    sourceHref: tx.filing_id === null ? null : buildFilingDetailPath(tx.filing_id)
  }));
}

/**
 */
function buildOutsideSpendingChartRows(
  ieSummary: IndependentExpenditureSummary
): OutsideSpendingRow[] {
  return [
    {
      id: "support-spending",
      label: "Support spending",
      stance: "support",
      amount: parseSerializedMoney(ieSummary.support_total),
      transactionCount: ieSummary.support_count
    },
    {
      id: "oppose-spending",
      label: "Oppose spending",
      stance: "oppose",
      amount: parseSerializedMoney(ieSummary.oppose_total),
      transactionCount: ieSummary.oppose_count
    }
  ];
}

function buildOutsideSpendingTopSpenderChartRows(
  ieSummary: IndependentExpenditureSummary
): OutsideSpendingRow[] {
  return ieSummary.top_spenders.map((spender) => ({
    id: spender.committee_id,
    label: spender.committee_name,
    stance: spender.support_oppose === "O" ? "oppose" : "support",
    amount: parseSerializedMoney(spender.total_amount),
    transactionCount: spender.transaction_count
  }));
}

/**
 */
function buildOutsideSpendingFigure(
  ieSummary: IndependentExpenditureSummary | null,
  selectedCycleOverride: number | null = null
): CandidateOutsideSpendingFigure | null {
  const selectedSummary = selectOutsideSpendingSummaryForCycle(ieSummary, selectedCycleOverride);
  if (selectedSummary === null) {
    return null;
  }

  return {
    cycle: selectedSummary.selected_cycle,
    coverageThrough: selectedSummary.coverage_end_date,
    rows: [
      {
        id: "support",
        label: "Support spending",
        stance: "support",
        amount: parseSerializedMoney(selectedSummary.support_total),
        transactionCount: selectedSummary.support_count
      },
      {
        id: "oppose",
        label: "Oppose spending",
        stance: "oppose",
        amount: parseSerializedMoney(selectedSummary.oppose_total),
        transactionCount: selectedSummary.oppose_count
      }
    ],
    topSpenders: selectedSummary.top_spenders.map((spender) => ({
      id: `${spender.committee_id}-${spender.support_oppose}`,
      label: spender.committee_name,
      stance: spender.support_oppose === "S" ? "support" : "oppose",
      amount: parseSerializedMoney(spender.total_amount),
      transactionCount: spender.transaction_count
    })),
    sources: []
  };
}

export function selectOutsideSpendingSummaryForCycle(
  ieSummary: IndependentExpenditureSummary | null,
  selectedCycleOverride: number | null
): IndependentExpenditureSummary | null {
  if (ieSummary === null) {
    return null;
  }

  if (selectedCycleOverride !== null && selectedCycleOverride !== ieSummary.selected_cycle) {
    return null;
  }

  return ieSummary;
}

export function selectOutsideSpendingTransactionsForCycle(
  ieSummary: IndependentExpenditureSummary | null,
  ieTransactions: IndependentExpenditureResponse[],
  selectedCycleOverride: number | null
): IndependentExpenditureResponse[] {
  return selectOutsideSpendingSummaryForCycle(ieSummary, selectedCycleOverride) === null
    ? []
    : ieTransactions;
}

/**
 */
export function buildOutsideSpendingPresentation(
  ieSummary: IndependentExpenditureSummary | null,
  ieTransactions: IndependentExpenditureResponse[]
): OutsideSpendingPresentation {
  // This UI section uses "outside spending" because it renders independent-expenditure records;
  // "dark money" is broader and can include sources not represented in this route contract.
  if (ieSummary === null) {
    return {
      supportTotal: "—",
      opposeTotal: "—",
      supportCountLabel: "—",
      opposeCountLabel: "—",
      topSpenders: [],
      chartRows: [],
      chartTopSpenders: [],
      explanatoryBlock: null,
      transactionRows: [],
      emptyMessage: OUTSIDE_SPENDING_UNAVAILABLE_MESSAGE
    };
  }

  if (ieSummary.coverage?.activity_state === "not_loaded") {
    return {
      supportTotal: "—",
      opposeTotal: "—",
      supportCountLabel: "—",
      opposeCountLabel: "—",
      topSpenders: [],
      chartRows: [],
      chartTopSpenders: [],
      explanatoryBlock: null,
      transactionRows: [],
      emptyMessage: CANDIDATE_IE_NOT_LOADED_MESSAGE
    };
  }

  if (ieSummary.coverage?.activity_state === "loaded_zero") {
    return buildLoadedZeroOutsideSpendingPresentation(ieSummary);
  }

  return {
    supportTotal: formatCurrency(ieSummary.support_total),
    opposeTotal: formatCurrency(ieSummary.oppose_total),
    supportCountLabel: formatCountLabel(ieSummary.support_count, "expenditure"),
    opposeCountLabel: formatCountLabel(ieSummary.oppose_count, "expenditure"),
    topSpenders: ieSummary.top_spenders.map((spender) => ({
      committeeName: spender.committee_name,
      committeeHref: buildCommitteeHref({
        id: spender.committee_id,
        slug: spender.committee_id,
        slug_is_unique: false
      }),
      stance: formatStanceLabel(spender.support_oppose),
      totalAmount: formatCurrency(spender.total_amount),
      transactionCountLabel: formatCountLabel(spender.transaction_count, "expenditure")
    })),
    chartRows: buildOutsideSpendingChartRows(ieSummary),
    chartTopSpenders: buildOutsideSpendingTopSpenderChartRows(ieSummary),
    explanatoryBlock: OUTSIDE_SPENDING_EXPLANATORY_BLOCK,
    transactionRows: buildOutsideSpendingTransactionRows(ieTransactions),
    emptyMessage: null
  };
}

function buildCommitteeOutsideSpendingTargetRows(
  targets: CommitteeIndependentExpenditureTarget[]
): CommitteeOutsideSpendingTargetRow[] {
  return targets.map((target) => ({
    rowKey: target.candidate_id,
    candidateName: target.candidate_name,
    targetHref: buildOptionalEntityHref("person", target.person_id),
    context: buildCandidateContext(target),
    supportTotal: formatCurrency(target.support_total),
    opposeTotal: formatCurrency(target.oppose_total),
    transactionCountLabel: formatCountLabel(target.transaction_count, "expenditure")
  }));
}

function buildCommitteeOutsideSpendingSourceRows(
  targets: CommitteeIndependentExpenditureTarget[]
): CommitteeOutsideSpendingSourceRow[] {
  return targets.flatMap((target) =>
    target.sources.map((source, sourceIndex) => ({
      rowKey: `${target.candidate_id}:${source.source_record_key ?? "unknown"}:${sourceIndex}`,
      candidateName: target.candidate_name,
      sourceName: source.data_source_name,
      sourceRecordKey: source.source_record_key ?? "—",
      href: sanitizeExternalUrl(source.record_url) ?? sanitizeExternalUrl(source.data_source_url)
    }))
  );
}

function buildCommitteeOutsideSpendingOutlierNote(excludedOutlierCount: number): string | null {
  if (excludedOutlierCount === 0) {
    return null;
  }

  if (excludedOutlierCount === 1) {
    return "1 reported independent expenditure was excluded from these totals as an outlier.";
  }

  return `${excludedOutlierCount} reported independent expenditures were excluded from these totals as outliers.`;
}

function isCommitteeOutsideSpendingEmpty(activity: CommitteeIndependentExpenditureActivity): boolean {
  return (
    parseSerializedMoney(activity.support_total) === 0 &&
    parseSerializedMoney(activity.oppose_total) === 0 &&
    activity.ie_transaction_count === 0 &&
    activity.targets.length === 0
  );
}

/**
 */
export function buildCommitteeOutsideSpendingPresentation(
  activity: CommitteeIndependentExpenditureActivity
): CommitteeOutsideSpendingPresentation {
  const targetRows = buildCommitteeOutsideSpendingTargetRows(activity.targets);
  const sourceRows = buildCommitteeOutsideSpendingSourceRows(activity.targets);

  return {
    supportTotal: formatCurrency(activity.support_total),
    opposeTotal: formatCurrency(activity.oppose_total),
    ieCountLabel: formatCountLabel(activity.ie_transaction_count, "expenditure"),
    outlierNote: buildCommitteeOutsideSpendingOutlierNote(activity.excluded_outlier_count),
    targetRows,
    sourceRows,
    emptyMessage: isCommitteeOutsideSpendingEmpty(activity) ? COMMITTEE_OUTSIDE_SPENDING_EMPTY_MESSAGE : null
  };
}

/**
 */
export function buildCandidateCommitteeBreakdown(
  summary: CandidateFundraisingSummary
): CandidateCommitteeBreakdownRow[] {
  return summary.committees.map((c) => {
    const totalReceipts = formatCurrency(c.total_raised);
    const totalDisbursements = formatCurrency(c.total_spent);
    const cashOnHand = formatOptionalCurrency(
      c.cycle_summaries.find((cycle) => cycle.cycle === c.selected_cycle)?.cash_on_hand
    );
    const debtsOwedByCommittee = formatOptionalCurrency(c.debts_owed_by_committee);
    const itemizedTransactions = c.itemized_transaction_count;
    const jurisdiction = formatRowValue(c.jurisdiction);
    const dataThrough = formatDateValue(c.data_through);
    return {
      committeeId: c.committee_id,
      committeeName: c.committee_name,
      committeeHref: buildCommitteeHref({
        id: c.committee_id,
        slug: c.slug ?? c.committee_id,
        slug_is_unique: c.slug_is_unique ?? false
      }),
      totalReceipts,
      totalDisbursements,
      cashOnHand,
      debtsOwedByCommittee,
      itemizedTransactions,
      totalRaised: totalReceipts,
      totalSpent: totalDisbursements,
      net: formatCurrency(c.net),
      transactionCount: c.transaction_count,
      jurisdiction,
      dataThrough,
      factRows: [
        { label: "Total receipts", value: totalReceipts },
        { label: "Total disbursements", value: totalDisbursements },
        { label: "Cash on hand", value: cashOnHand },
        { label: "Debts owed by the committee", value: debtsOwedByCommittee },
        { label: "Itemized transactions", value: String(itemizedTransactions) },
        { label: "Jurisdiction", value: jurisdiction },
        { label: "Data through", value: dataThrough }
      ]
    };
  });
}

type SlugCollisionMatchItem = CandidateListItem | CommitteeListItem;

function buildSlugCollisionMatches<TMatch extends SlugCollisionMatchItem>(
  matches: TMatch[],
  buildHref: (match: TMatch) => string
): SlugCollisionMatchPresentation[] {
  return matches.map((match) => ({
    id: match.id,
    name: match.name,
    href: buildHref(match)
  }));
}

/** Converts candidate route data into either a canonical detail model or slug chooser state. */
export function buildCandidateRoutePresentation(data: CandidateRouteData): CandidateDetailRoutePresentation {
  if (data.routeKind === "slug-collision") {
    return {
      routeKind: "slug-collision",
      entityType: "candidate",
      slug: data.slug,
      heading: `Multiple candidates match "${data.slug}"`,
      chooserLabel: "Select a candidate record",
      matches: buildSlugCollisionMatches(data.matches, (match) => buildCandidateHref(match))
    };
  }

  const canonicalData = data as typeof data & CandidateCanonicalRouteDataExtras;

  return {
    routeKind: "canonical-detail",
    entityType: "candidate",
    shell: buildCandidateDetailShellPresentation(data.detail, {
      l10Reference: canonicalData.keelL10Reference ?? null
    }),
    summary: data.summary,
    ieTransactions: data.ieTransactions,
    ieSummary: data.ieSummary
  };
}

/** Converts committee route data into either a canonical detail model or slug chooser state. */
export function buildCommitteeRoutePresentation(data: CommitteeRouteData): CommitteeDetailRoutePresentation {
  if (data.routeKind === "slug-collision") {
    return {
      routeKind: "slug-collision",
      entityType: "committee",
      slug: data.slug,
      heading: `Multiple committees match "${data.slug}"`,
      chooserLabel: "Select a committee record",
      matches: buildSlugCollisionMatches(data.matches, (match) => buildCommitteeHref(match))
    };
  }

  return {
    routeKind: "canonical-detail",
    entityType: "committee",
    shell: buildCommitteeDetailShellPresentation(data.detail),
    transactions: data.transactions,
    summary: data.summary,
    filingBreakdown: data.filingBreakdown,
    independentExpendituresMade: data.independentExpendituresMade
  };
}
