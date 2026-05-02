/** View-model builders for campaign-finance detail pages and route chooser states. */
import { buildEntityRouteHref } from "$lib/entity-detail/contract";
import {
  buildTrustSection,
  type TrustSectionViewModel
} from "$lib/detail-trust/presentation";
import { formatCountLabel } from "$lib/count-label";
import {
  buildCandidateHref,
  buildCommitteeHref
} from "$lib/campaign-finance-detail/contract";
import type { ChartSeries } from "$lib/charts/types";
import type {
  CandidateDetailResponse,
  CandidateListItem,
  CampaignFinanceTransactionResponse,
  CommitteeDetailResponse,
  CommitteeFilingBreakdown,
  CandidateFundraisingSummary,
  CommitteeFundraisingSummary,
  CommitteeListItem,
  IndependentExpenditureResponse,
  IndependentExpenditureSummary,
  SerializedMoney
} from "$lib/campaign-finance-detail/contract";
import type { CandidateDetailBundle, CommitteeDetailBundle } from "$lib/server/api/campaign-finance-detail";

export type CampaignFinanceFactRow = {
  label: string;
  value: string;
  href: string | null;
};

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
  cashOnHandTrendSeries: ChartSeries[];
};

export type FundraisingSummaryPresentation = {
  totalRaised: string;
  totalSpent: string;
  net: string;
  transactionCount: number;
  jurisdiction: string;
  dataThrough: string;
};

export type FilingBreakdownRowPresentation = {
  filingId: string;
  filingFecId: string;
  filingName: string;
  reportType: string;
  amendmentIndicator: string;
  coveragePeriod: string;
  receiptDate: string;
  totalRaised: string;
  totalSpent: string;
  net: string;
  transactionCount: number;
};

export type FilingBreakdownPresentation = {
  rows: FilingBreakdownRowPresentation[];
  emptyMessage: string | null;
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
};

export type CandidateAggregateSummaryPresentation = {
  totalRaised: string;
  totalSpent: string;
  net: string;
  transactionCount: number;
};

export type CandidateCommitteeBreakdownRow = {
  committeeId: string;
  committeeName: string;
  committeeHref: string;
  totalRaised: string;
  totalSpent: string;
  net: string;
  transactionCount: number;
  jurisdiction: string;
  dataThrough: string;
};

export type OutsideSpendingTopSpenderRow = {
  committeeName: string;
  committeeHref: string;
  stance: string;
  totalAmount: string;
  transactionCountLabel: string;
};

export type OutsideSpendingTransactionRow = {
  date: string;
  disseminationDate: string;
  spender: string;
  spenderHref: string;
  stance: string;
  amount: string;
};

export type OutsideSpendingPresentation = {
  supportTotal: string;
  opposeTotal: string;
  supportCountLabel: string;
  opposeCountLabel: string;
  topSpenders: OutsideSpendingTopSpenderRow[];
  explanatoryBlock: string | null;
  transactionRows: OutsideSpendingTransactionRow[];
  emptyMessage: string | null;
};

export type CandidateDetailShellPresentation = {
  canonicalName: string;
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
  filingBreakdown: Deferred<CommitteeFilingBreakdown>;
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
  | ({ routeKind: "canonical-detail" } & CandidateDetailBundle)
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

export function formatCurrency(value: SerializedMoney | number): string {
  return CURRENCY_FORMATTER.format(parseSerializedMoney(value));
}

type AggregateSummarySource = {
  total_raised: SerializedMoney;
  total_spent: SerializedMoney;
  net: SerializedMoney;
  transaction_count: number;
};

export function buildCandidateAggregateSummaryPresentation(
  summary: AggregateSummarySource
): CandidateAggregateSummaryPresentation {
  return {
    totalRaised: formatCurrency(summary.total_raised),
    totalSpent: formatCurrency(summary.total_spent),
    net: formatCurrency(summary.net),
    transactionCount: summary.transaction_count
  };
}

export function buildFundraisingSummaryPresentation(
  summary: CommitteeFundraisingSummary
): FundraisingSummaryPresentation {
  return {
    ...buildCandidateAggregateSummaryPresentation(summary),
    jurisdiction: formatRowValue(summary.jurisdiction),
    dataThrough: formatDateValue(summary.data_through)
  };
}

/** Converts backend filing breakdown rows into table-ready presentation data. */
export function buildFilingBreakdownPresentation(
  filingBreakdown: CommitteeFilingBreakdown
): FilingBreakdownPresentation {
  const rows = filingBreakdown.filings.map((filing) => ({
    filingId: filing.filing_id,
    filingFecId: filing.filing_fec_id,
    filingName: formatRowValue(filing.filing_name),
    reportType: formatRowValue(filing.report_type),
    amendmentIndicator: filing.amendment_indicator,
    coveragePeriod: buildCoveragePeriodLabel(filing.coverage_start_date, filing.coverage_end_date),
    receiptDate: formatDateValue(filing.receipt_date),
    totalRaised: formatCurrency(filing.total_raised),
    totalSpent: formatCurrency(filing.total_spent),
    net: formatCurrency(filing.net),
    transactionCount: filing.transaction_count
  }));

  return {
    rows,
    emptyMessage: rows.length === 0 ? EMPTY_FILING_BREAKDOWN_MESSAGE : null
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

export type CommitteeTransactionRouteReferences = {
  candidateById?: Record<string, SlugRoutableReference>;
  committeeById?: Record<string, SlugRoutableReference>;
};

function buildFallbackSlugReference(routeId: string): SlugRoutableReference {
  return {
    id: routeId,
    slug: routeId,
    slug_is_unique: false
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


export function buildCommitteeDetailMetadata(
  canonicalName: string
): CampaignFinanceDetailMetadata {
  return {
    title: `${canonicalName} | Committee | Civibus`,
    description: "Committee profile from campaign-finance records."
  };
}

export function buildCandidateDetailMetadata(canonicalName: string): CampaignFinanceDetailMetadata {
  return {
    title: `${canonicalName} | Candidate | Civibus`,
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
  return [
    { label: "Candidate name", value: detail.name, href: null },
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
    recipientCandidateHref: buildOptionalSlugRouteHref(
      transaction.recipient_candidate_id,
      routeReferences.candidateById,
      buildCandidateHref
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
    { label: "Transactions", value: String(summary.transaction_count) }
  ];
}

function buildRankedPartyRows(
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

function buildCashOnHandTrendSeries(filingBreakdown: CommitteeFilingBreakdown): ChartSeries[] {
  const points = filingBreakdown.filings
    .filter((filing) => filing.cash_on_hand !== null)
    .map((filing) => {
      const y = parseSerializedMoney(filing.cash_on_hand as SerializedMoney);
      if (Number.isNaN(y)) {
        return null;
      }

      return {
        x: filing.coverage_end_date ?? filing.receipt_date ?? filing.row_id,
        y
      };
    })
    .filter((point): point is { x: string; y: number } => point !== null);

  if (points.length === 0) {
    return [];
  }

  return [
    {
      id: "cash-on-hand",
      label: "Cash on hand",
      points
    }
  ];
}

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
    cashOnHandTrendSeries: buildCashOnHandTrendSeries(filingBreakdown)
  };
}

export function buildCommitteeDetailShellPresentation(
  detail: CommitteeDetailResponse
): CommitteeDetailShellPresentation {
  return {
    canonicalName: resolveCanonicalName(detail.name, "Committee"),
    factRows: buildCommitteeFactRows(detail),
    trustSection: buildTrustSection(detail.sources, { includeJurisdictionFreshnessNote: true }),
    sectionOrder: ["summary", "trust", "metrics", "records"],
    committeeRouteRef: {
      committeeById: {
        [detail.id]: { id: detail.id, slug: detail.slug, slug_is_unique: detail.slug_is_unique }
      }
    }
  };
}

export function buildCandidateDetailShellPresentation(
  detail: CandidateDetailResponse,
  options?: {
    l10Reference?: CandidateL10Reference | null;
  }
): CandidateDetailShellPresentation {
  const detailExtras = detail as CandidateDetailResponse & CandidateDetailL10Extras;

  return {
    canonicalName: resolveCanonicalName(detail.name, "Candidate"),
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

export function buildCommitteeDeferredFilingBreakdown(
  filingBreakdown: CommitteeFilingBreakdown
): FilingBreakdownPresentation {
  return buildFilingBreakdownPresentation(filingBreakdown);
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
  ieTransactions: IndependentExpenditureResponse[]
): OutsideSpendingPresentation {
  return buildOutsideSpendingPresentation(ieSummary, ieTransactions);
}

export function buildCandidateDeferredKeyMetrics(summary: CandidateFundraisingSummary): KeyMetric[] {
  return buildKeyMetrics(summary);
}

function _hasZeroAggregate(summary: CandidateFundraisingSummary): boolean {
  return (
    parseSerializedMoney(summary.total_raised) === 0 &&
    parseSerializedMoney(summary.total_spent) === 0 &&
    parseSerializedMoney(summary.net) === 0 &&
    summary.transaction_count === 0
  );
}

function _computeDeviationRatio(currentTotal: number, expectedTotal: number): number {
  if (expectedTotal === 0) {
    return currentTotal === 0 ? 0 : Number.POSITIVE_INFINITY;
  }

  return Math.abs(currentTotal - expectedTotal) / expectedTotal;
}

export function buildCandidateCompletenessWarnings(
  summary: CandidateFundraisingSummary,
  l10Reference: CandidateL10Reference | null
): CandidateCompletenessWarning[] {
  const warnings: CandidateCompletenessWarning[] = [];

  if (_hasZeroAggregate(summary)) {
    warnings.push({
      message: CANDIDATE_EMPTY_COMPLETENESS_WARNING,
      methodologyHref: "/methodology"
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
        methodologyHref: l10Reference.methodologyHref
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

export function isOutsideSpendingSummaryEmpty(ieSummary: IndependentExpenditureSummary): boolean {
  return (
    parseSerializedMoney(ieSummary.support_total) === 0 &&
    parseSerializedMoney(ieSummary.oppose_total) === 0 &&
    ieSummary.support_count === 0 &&
    ieSummary.oppose_count === 0 &&
    ieSummary.top_spenders.length === 0
  );
}

const OUTSIDE_SPENDING_EXPLANATORY_BLOCK =
  "Outside spending is independent and not controlled by the candidate committee.";

/** Formats IE transactions for the outside-spending table shown on candidate pages. */
function buildOutsideSpendingTransactionRows(
  ieTransactions: IndependentExpenditureResponse[]
): OutsideSpendingTransactionRow[] {
  return ieTransactions.map((tx) => ({
    date: formatDateValue(tx.transaction_date),
    disseminationDate: formatDateValue(tx.dissemination_date),
    spender: tx.committee_name,
    spenderHref: buildCommitteeHref({
      id: tx.committee_id,
      slug: tx.committee_id,
      slug_is_unique: false
    }),
    stance: formatStanceLabel(tx.support_oppose),
    amount: formatCurrency(tx.amount)
  }));
}

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
      explanatoryBlock: null,
      transactionRows: [],
      emptyMessage: OUTSIDE_SPENDING_UNAVAILABLE_MESSAGE
    };
  }

  if (isOutsideSpendingSummaryEmpty(ieSummary)) {
    return {
      supportTotal: "—",
      opposeTotal: "—",
      supportCountLabel: "—",
      opposeCountLabel: "—",
      topSpenders: [],
      explanatoryBlock: null,
      transactionRows: [],
      emptyMessage: OUTSIDE_SPENDING_NO_ACTIVITY_MESSAGE
    };
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
    explanatoryBlock: OUTSIDE_SPENDING_EXPLANATORY_BLOCK,
    transactionRows: buildOutsideSpendingTransactionRows(ieTransactions),
    emptyMessage: null
  };
}

export function buildCandidateCommitteeBreakdown(
  summary: CandidateFundraisingSummary
): CandidateCommitteeBreakdownRow[] {
  return summary.committees.map((c) => ({
    committeeId: c.committee_id,
    committeeName: c.committee_name,
    committeeHref: buildCommitteeHref({
      id: c.committee_id,
      slug: c.slug ?? c.committee_id,
      slug_is_unique: c.slug_is_unique ?? false
    }),
    totalRaised: formatCurrency(c.total_raised),
    totalSpent: formatCurrency(c.total_spent),
    net: formatCurrency(c.net),
    transactionCount: c.transaction_count,
    jurisdiction: formatRowValue(c.jurisdiction),
    dataThrough: formatDateValue(c.data_through)
  }));
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
    filingBreakdown: data.filingBreakdown
  };
}
