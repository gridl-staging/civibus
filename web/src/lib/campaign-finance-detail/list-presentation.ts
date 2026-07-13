import { buildCandidateHref, buildCommitteeHref, type CandidateListItem, type CommitteeListItem } from "./contract";

export type CandidateListItemPresentation = {
  name: string;
  href: string;
  contextLine: string;
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
    name: item.name,
    href: buildCandidateHref(item),
    contextLine
  };
}

export function buildCommitteeListItemPresentation(
  item: CommitteeListItem
): CommitteeListItemPresentation {
  const contextLine = [item.committee_type, item.party, item.state]
    .filter(Boolean)
    .join(" \u00b7 ");

  return {
    name: item.name,
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
