export type CommitteeSummarySource = "fec_committee_summary" | "derived";

export const COMMITTEE_SUMMARY_SOURCE_LABELS: Record<CommitteeSummarySource, string> = {
  fec_committee_summary: "Official FEC committee summary",
  derived: "Derived from itemized transactions"
};

export function buildCommitteeItemizedCoverageNote(summary: {
  itemized_transaction_count: number;
  summary_source: CommitteeSummarySource;
}): string {
  const itemizedCount = summary.itemized_transaction_count;
  if (summary.summary_source === "fec_committee_summary") {
    return (
      `Itemized transactions loaded: ${itemizedCount}. ` +
      "Official totals above come directly from the FEC committee summary and are not derived from these transactions."
    );
  }

  return (
    `Itemized transactions loaded: ${itemizedCount}. ` +
    "Totals above are derived from these itemized transactions."
  );
}
