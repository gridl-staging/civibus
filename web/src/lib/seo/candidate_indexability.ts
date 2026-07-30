export type CandidateIndexabilityInput = Readonly<{
  has_official_total: boolean;
}>;

function isIndexable(item: CandidateIndexabilityInput): boolean {
  return item.has_official_total;
}

export const CANDIDATE_ROUTE_INDEXABILITY = Object.freeze({
  isIndexable,
  robots(item: CandidateIndexabilityInput): "noindex" | null {
    return isIndexable(item) ? null : "noindex";
  }
});
