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
import type {
  CandidateDetailResponse,
  CandidateListItem,
  CampaignFinanceTransactionResponse,
  CommitteeDetailResponse,
  CommitteeFilingBreakdown,
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

export type CommitteeDetailPresentation = {
  canonicalName: string;
  factRows: CampaignFinanceFactRow[];
  trustSection: TrustSectionViewModel;
  sectionOrder: string[];
  keyMetrics: KeyMetric[];
  fundraisingSummary: FundraisingSummaryPresentation;
  filingBreakdown: FilingBreakdownPresentation;
  transactionRows: CommitteeTransactionRow[];
  transactionEmptyMessage: string | null;
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

export type CandidateDetailPresentation = {
  canonicalName: string;
  factRows: CampaignFinanceFactRow[];
  trustSection: TrustSectionViewModel;
  sectionOrder: string[];
  keyMetrics: KeyMetric[];
  fundraisingSummary: CandidateAggregateSummaryPresentation;
  outsideSpending: OutsideSpendingPresentation;
  committeeBreakdown: CandidateCommitteeBreakdownRow[];
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

type CandidateCanonicalDetailRoutePresentation = {
  routeKind: "canonical-detail";
  entityType: "candidate";
  detail: CandidateDetailPresentation;
};

type CommitteeCanonicalDetailRoutePresentation = {
  routeKind: "canonical-detail";
  entityType: "committee";
  detail: CommitteeDetailPresentation;
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

function buildAggregateSummaryPresentation(
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
    ...buildAggregateSummaryPresentation(summary),
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

/** Prefers a detail name, then summary name, then a generic fallback label. */
function resolveCanonicalName(
  detailName: string,
  summaryName: string,
  fallbackLabel: "Candidate" | "Committee"
): string {
  const trimmedDetailName = detailName.trim();
  if (trimmedDetailName !== "") {
    return trimmedDetailName;
  }

  const trimmedSummaryName = summaryName.trim();
  if (trimmedSummaryName !== "") {
    return trimmedSummaryName;
  }

  return fallbackLabel;
}

export function buildCommitteeDetailMetadata(
  canonicalName: string,
  transactionCount: number
): CampaignFinanceDetailMetadata {
  const transactionLabel = formatCountLabel(transactionCount, "recent transaction");

  return {
    title: `${canonicalName} | Committee | Civibus`,
    description: `Committee profile with ${transactionLabel}.`
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
  return buildCommitteeDetailMetadata(
    resolveCanonicalName(data.detail.name, data.summary.committee_name, "Committee"),
    data.transactions.length
  );
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
      transaction.recipient_committee_id === null ? null : RECIPIENT_COMMITTEE_LINK_LABEL
  }));
}

export function getCampaignFinanceEmptyMessage(): string {
  return COMMITTEE_TRANSACTION_EMPTY_MESSAGE;
}

/** Assembles the full committee detail presentation model from the fetched bundle. */
export function buildCommitteeDetailPresentation(data: CommitteeDetailBundle): CommitteeDetailPresentation {
  const trustSection = buildTrustSection(data.detail.sources);
  const transactionRows = buildCommitteeTransactionRows(data.transactions, {
    committeeById: {
      [data.detail.id]: {
        id: data.detail.id,
        slug: data.detail.slug,
        slug_is_unique: data.detail.slug_is_unique
      }
    }
  });

  return {
    canonicalName: resolveCanonicalName(data.detail.name, data.summary.committee_name, "Committee"),
    factRows: buildCommitteeFactRows(data.detail),
    trustSection,
    sectionOrder: ["summary", "trust", "metrics", "records"],
    keyMetrics: [
      { label: "Total raised", value: formatCurrency(data.summary.total_raised) },
      { label: "Total spent", value: formatCurrency(data.summary.total_spent) },
      { label: "Transactions", value: String(data.summary.transaction_count) }
    ],
    fundraisingSummary: buildFundraisingSummaryPresentation(data.summary),
    filingBreakdown: buildFilingBreakdownPresentation(data.filingBreakdown),
    transactionRows,
    transactionEmptyMessage: transactionRows.length === 0 ? getCampaignFinanceEmptyMessage() : null
  };
}

function formatStanceLabel(stance: "S" | "O"): string {
  return stance === "S" ? "Support" : "Oppose";
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

/** Builds the outside-spending section, including explicit empty and unavailable states. */
function buildOutsideSpendingPresentation(
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

/** Assembles the full candidate detail presentation model from the fetched bundle. */
export function buildCandidateDetailPresentation(data: CandidateDetailBundle): CandidateDetailPresentation {
  const trustSection = buildTrustSection(data.detail.sources);
  const { summary } = data;

  const committeeBreakdown: CandidateCommitteeBreakdownRow[] = summary.committees.map((c) => ({
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

  return {
    canonicalName: resolveCanonicalName(data.detail.name, summary.candidate_name, "Candidate"),
    factRows: buildCandidateFactRows(data.detail),
    trustSection,
    sectionOrder: ["summary", "trust", "metrics", "outside-spending", "records"],
    keyMetrics: [
      { label: "Total raised", value: formatCurrency(summary.total_raised) },
      { label: "Total spent", value: formatCurrency(summary.total_spent) },
      { label: "Transactions", value: String(summary.transaction_count) }
    ],
    fundraisingSummary: buildAggregateSummaryPresentation(summary),
    outsideSpending: buildOutsideSpendingPresentation(data.ieSummary, data.ieTransactions),
    committeeBreakdown
  };
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

  return {
    routeKind: "canonical-detail",
    entityType: "candidate",
    detail: buildCandidateDetailPresentation(data)
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
    detail: buildCommitteeDetailPresentation(data)
  };
}
