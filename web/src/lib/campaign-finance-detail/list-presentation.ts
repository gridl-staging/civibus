import { buildCandidateHref, buildCommitteeHref, type CandidateListItem, type CommitteeListItem } from "./contract";
import { formatCandidatePublicName, formatOptionalCurrency, resolveCanonicalName } from "./presentation";

/** Label for the candidate browse money column. */
export const CANDIDATE_TOTAL_RAISED_LABEL = "Total raised";

export type CandidateListItemPresentation = {
  name: string;
  href: string;
  contextLine: string;
  totalRaisedLabel: string;
  /**
   * Formatted official total receipts, or the shared unknown copy when the
   * candidate has no loaded total. Never `$0.00` for a missing total.
   */
  totalRaisedValue: string;
};

export type CommitteeListItemPresentation = {
  name: string;
  href: string;
  contextLine: string;
};

export type PaginationContext = {
  label: string;
  hasPrevious: boolean;
  hasNext: boolean;
};

/**
 */
export function buildCandidateListItemPresentation(
  item: CandidateListItem
): CandidateListItemPresentation {
  // Candidate browse rows surface the route target alongside the compact
  // identity context users need to distinguish same-name records in the list.
  const location =
    item.state && item.district
      ? `${item.state}-${item.district}`
      : item.state ?? item.district;

  const contextLine = [item.party, item.office, location]
    .filter(Boolean)
    .join(" \u00b7 ");

  return {
    // cf.candidate.name arrives as the raw FEC filing string, which is shouted
    // uppercase. The shared identity-gated owner formats safe names (stopping
    // one human reading as two unrelated records across the browse list and
    // Person Detail) and keeps unsafe filings raw, matching the neutral
    // presentation their own detail page uses. Person-scoped and
    // include_unsafe_identity reads DO put unsafe rows through here, so the
    // gate is load-bearing, not theoretical.
    name: formatCandidatePublicName(item),
    href: buildCandidateHref(item),
    contextLine,
    totalRaisedLabel: CANDIDATE_TOTAL_RAISED_LABEL,
    // Delegates to the shared money owner so the browse list, the detail page,
    // and every other surface agree on formatting and on the unknown copy.
    totalRaisedValue: formatOptionalCurrency(item.total_receipts)
  };
}

export function buildCommitteeListItemPresentation(
  item: CommitteeListItem
): CommitteeListItemPresentation {
  const contextLine = [item.committee_type, item.party, item.state]
    .filter(Boolean)
    .join(" \u00b7 ");

  return {
    name: resolveCanonicalName(item.name, "Committee"),
    href: buildCommitteeHref(item),
    contextLine
  };
}

/**
 */
export function buildPaginationContext(
  offset: number,
  _limit: number,
  hasNext: boolean,
  currentItemCount: number
): PaginationContext {
  // Offset is zero-based in the API contract, but the browse label should read
  // in one-based inclusive ranges so users can orient themselves in the list.
  if (currentItemCount === 0) {
    return {
      label: "Showing 0\u20130",
      hasPrevious: offset > 0,
      hasNext
    };
  }

  const start = offset + 1;
  const end = offset + currentItemCount;

  return {
    label: `Showing ${start}\u2013${end}`,
    hasPrevious: offset > 0,
    hasNext
  };
}
