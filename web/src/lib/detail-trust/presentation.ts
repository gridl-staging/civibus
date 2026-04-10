/** Presentation helpers for source provenance and freshness sections. */
import type { SourceInfo } from "$lib/entity-detail/contract";
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
};

export const TRUST_SECTION_EMPTY_MESSAGE = "No source records are available for this detail yet.";
export const TRUST_SECTION_ADVISORY_MESSAGE = "Review source records before publication.";
export const TRUST_SECTION_LAST_PULLED_UNAVAILABLE = "Last pulled: unavailable";

function buildSourceLabel(source: SourceInfo): string {
  if (source.jurisdiction) {
    return `${source.domain}/${source.jurisdiction}`;
  }

  return source.domain;
}

/** Allows only HTTP(S) record links to render as outbound source URLs. */
function sanitizeExternalRecordUrl(value: string | null): string | null {
  if (!value) {
    return null;
  }

  try {
    const parsed = new URL(value);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return null;
    }

    return parsed.toString();
  } catch {
    return null;
  }
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
    return {
      source: sourcePath,
      sourceName: source.data_source_name,
      sourceLabel: `${source.data_source_name} (${sourcePath})`,
      sourceRecordKey: source.source_record_key ?? "—",
      pullDate: source.pull_date,
      recordUrl: sanitizeExternalRecordUrl(source.record_url)
    };
  });
}

export function buildTrustSection(sources: SourceInfo[]): TrustSectionViewModel {
  const rows = buildTrustRows(sources);
  const freshest = findFreshestPullDate(rows);

  return {
    rows,
    lastPulledSummary: buildLastPulledSummary(freshest),
    freshnessSeverity: deriveFreshnessSeverity(freshest),
    emptyMessage: rows.length === 0 ? TRUST_SECTION_EMPTY_MESSAGE : null,
    advisoryMessage: TRUST_SECTION_ADVISORY_MESSAGE
  };
}
