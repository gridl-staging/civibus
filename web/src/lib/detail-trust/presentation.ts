/** Presentation helpers for source provenance and freshness sections. */
import type { SourceInfo } from "$lib/entity-detail/contract";
import { sanitizeExternalUrl } from "$lib/url/sanitize-external-url";
import { formatAbsolutePullDate, formatRelativePullDate } from "./relative-date";

export type FreshnessSeverity = "fresh" | "stale" | "unknown";

export type TrustSectionRow = {
  source: string;
  sourceName: string;
  sourceLabel: string;
  sourceRecordKey: string;
  pullDate: string;
  recordUrl: string | null;
};

export type TrustSectionViewModel = {
  rows: TrustSectionRow[];
  lastPulledSummary: string;
  freshnessSeverity: FreshnessSeverity;
  emptyMessage: string | null;
  advisoryMessage: string;
  // Presentation-only warning copy for jurisdiction-specific caveats that do
  // not justify a backend schema field yet.
  freshnessNote: string | null;
};

export type BuildTrustSectionOptions = {
  includeJurisdictionFreshnessNote?: boolean;
};

export const TRUST_SECTION_EMPTY_MESSAGE = "No source records are available for this detail yet.";
export const TRUST_SECTION_ADVISORY_MESSAGE = "Review source records before publication.";
export const TRUST_SECTION_LAST_PULLED_UNAVAILABLE = "Last pulled: unavailable";
export const CAMPAIGN_FINANCE_NO_LINKED_COMMITTEES_MESSAGE =
  "No linked committee summaries are available yet.";
export const CAMPAIGN_FINANCE_NO_DONOR_VENDOR_TRANSACTIONS_MESSAGE =
  "No donor/vendor transactions are available yet.";

// Keep the freshness-note contract intentionally narrow and client-side for now.
// This avoids inventing a new backend field for a single urgent jurisdiction-specific warning.
//
// Indiana freshness banner retired 2026-04-26 after the IN re-verdict to
// weekly-or-better (see docs/research/in_freshness_recheck_2026_04_26.md).
// The plumbing is intentionally retained so the next jurisdiction-specific
// caveat can be added by a single one-line entry.
export const PHL_FRESHNESS_NOTE =
  "Philadelphia campaign finance bulk data has an observed ~27 day publication lag; this view may be weeks behind recent filings.";
const AL_FRESHNESS_NOTE =
  "Alabama campaign finance production data is currently a narrow committee-state slice; totals may be incomplete.";
const GA_FRESHNESS_NOTE =
  "Georgia campaign finance production data is currently a narrow committee-state slice; totals may be incomplete.";

const FRESHNESS_NOTES_BY_CAMPAIGN_FINANCE_JURISDICTION: Readonly<Record<string, string>> = {
  "state/AL": AL_FRESHNESS_NOTE,
  "state/GA": GA_FRESHNESS_NOTE,
  "municipality/PHL": PHL_FRESHNESS_NOTE
};

function buildSourceLabel(source: SourceInfo): string {
  if (source.jurisdiction) {
    return `${source.domain}/${source.jurisdiction}`;
  }

  return source.domain;
}

function parsePullDateTimestamp(value: string): number | null {
  const timestamp = Date.parse(value);

  if (Number.isNaN(timestamp)) {
    return null;
  }

  return timestamp;
}

// Freshness heuristic: data pulled within 7 days is "fresh", older is "stale",
// and unparseable/missing dates are "unknown". These thresholds are presentation-only
// and do not reflect any backend refresh schedule promise.
const FRESHNESS_THRESHOLD_DAYS = 7;
const MILLISECONDS_PER_DAY = 86_400_000;

type FreshestPullDate = { pullDate: string; timestamp: number };

function findFreshestPullDate(rows: TrustSectionRow[]): FreshestPullDate | null {
  let freshest: FreshestPullDate | null = null;

  for (const row of rows) {
    const timestamp = parsePullDateTimestamp(row.pullDate);

    if (timestamp !== null && (freshest === null || timestamp > freshest.timestamp)) {
      freshest = { pullDate: row.pullDate, timestamp };
    }
  }

  return freshest;
}

function buildLastPulledSummary(freshest: FreshestPullDate | null): string {
  if (freshest === null) {
    return TRUST_SECTION_LAST_PULLED_UNAVAILABLE;
  }

  const relative = formatRelativePullDate(freshest.pullDate);
  const absolute = formatAbsolutePullDate(freshest.pullDate);
  return `Last pulled: ${relative} (${absolute})`;
}

function deriveFreshnessSeverity(freshest: FreshestPullDate | null): FreshnessSeverity {
  if (freshest === null) {
    return "unknown";
  }

  const daysSincePull = Math.floor((Date.now() - freshest.timestamp) / MILLISECONDS_PER_DAY);
  return daysSincePull > FRESHNESS_THRESHOLD_DAYS ? "stale" : "fresh";
}

function buildTrustRows(sources: SourceInfo[]): TrustSectionRow[] {
  return sources.map((source) => {
    const sourcePath = buildSourceLabel(source);
    const recordUrl = sanitizeExternalUrl(source.record_url) ?? sanitizeExternalUrl(source.data_source_url);
    return {
      source: sourcePath,
      sourceName: source.data_source_name,
      sourceLabel: `${source.data_source_name} (${sourcePath})`,
      sourceRecordKey: source.source_record_key ?? "—",
      pullDate: source.pull_date,
      recordUrl
    };
  });
}

function buildFreshnessNote(sources: SourceInfo[]): string | null {
  for (const source of sources) {
    // The warning is specific to campaign-finance cadence evidence, not every Indiana detail page.
    if (source.domain !== "campaign_finance" || source.jurisdiction === null) {
      continue;
    }

    const note = FRESHNESS_NOTES_BY_CAMPAIGN_FINANCE_JURISDICTION[source.jurisdiction];
    if (note) {
      return note;
    }
  }

  return null;
}

export function buildLinkedCommitteeEmptyStateBanner(linkedCommitteeCount: number): string | null {
  return linkedCommitteeCount === 0 ? CAMPAIGN_FINANCE_NO_LINKED_COMMITTEES_MESSAGE : null;
}

export function buildDonorVendorEmptyStateBanner(donorVendorTransactionCount: number): string | null {
  return donorVendorTransactionCount === 0 ? CAMPAIGN_FINANCE_NO_DONOR_VENDOR_TRANSACTIONS_MESSAGE : null;
}

export function buildTrustSection(
  sources: SourceInfo[],
  options: BuildTrustSectionOptions = {}
): TrustSectionViewModel {
  const rows = buildTrustRows(sources);
  const freshest = findFreshestPullDate(rows);
  // Jurisdiction-specific warning copy is currently only intended for the
  // campaign-finance detail experience, not every consumer of the shared
  // trust-section builder.
  const freshnessNote = options.includeJurisdictionFreshnessNote ? buildFreshnessNote(sources) : null;

  return {
    rows,
    lastPulledSummary: buildLastPulledSummary(freshest),
    freshnessSeverity: deriveFreshnessSeverity(freshest),
    emptyMessage: rows.length === 0 ? TRUST_SECTION_EMPTY_MESSAGE : null,
    advisoryMessage: TRUST_SECTION_ADVISORY_MESSAGE,
    freshnessNote
  };
}
