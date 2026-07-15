import { describe, expect, it } from "vitest";
import {
  buildCandidateCompletenessWarnings,
  buildCandidateAggregateSummaryPresentation,
  buildCandidateCommitteeBreakdown,
  buildCandidateDeferredCommitteeBreakdown,
  buildCandidateDeferredFundraisingSummary,
  buildCandidateDeferredKeyMetrics,
  buildCandidateDeferredOutsideSpending,
  buildCommitteeDeferredFilingBreakdown,
  buildCommitteeDeferredFundraisingSummary,
  buildCommitteeDeferredHighSignalSummary,
  buildCommitteeDeferredKeyMetrics,
  buildCommitteeDeferredOutsideSpending,
  buildCommitteeDeferredTransactionRows,
  buildCommitteeTransactionRows,
  buildFilingBreakdownPresentation,
  buildFundraisingSummaryPresentation,
  buildKeyMetrics,
  buildOutsideSpendingPresentation,
  formatCurrency,
  getCampaignFinanceEmptyMessage
} from "./presentation";
import {
  CANDIDATE_ID,
  COMMITTEE_ID,
  DEFAULT_CANDIDATE_SUMMARY,
  DEFAULT_FILING_BREAKDOWN,
  DEFAULT_SELECTED_CYCLE_FIELDS,
  DEFAULT_SUMMARY,
  DEFAULT_TRANSACTION,
  FILING_ID,
  ORG_ID,
  PERSON_ID
} from "./presentation_test_fixtures";

describe("campaign finance deferred detail presentation", () => {
  it("formats currency for zero, large values, and negatives", () => {
    expect(formatCurrency(0)).toBe("$0.00");
    expect(formatCurrency(1234567.8)).toBe("$1,234,567.80");
    expect(formatCurrency(-90.12)).toBe("-$90.12");
  });

  it("builds fundraising summary presentation with formatted currency", () => {
    expect(buildFundraisingSummaryPresentation(DEFAULT_SUMMARY)).toEqual({
      totalRaised: "$125.00",
      totalSpent: "$50.00",
      net: "$75.00",
      transactionCount: 1,
      jurisdiction: "federal/fec",
      dataThrough: "2026-03-19",
      summarySourceLabel: "Derived from itemized transactions",
      itemizedCoverageNote:
        "Itemized transactions loaded: 1. Totals above are derived from these itemized transactions."
    });
  });

  it("builds filing breakdown presentation with formatted coverage, dates, and currency", () => {
    expect(buildFilingBreakdownPresentation(DEFAULT_FILING_BREAKDOWN)).toEqual({
      rows: [
        {
          filingId: FILING_ID,
          filingFecId: "FEC-100",
          filingName: "Q1 filing",
          reportType: "Q1",
          amendmentIndicator: "N",
          coveragePeriod: "2026-01-01 to 2026-03-31",
          receiptDate: "2026-04-10",
          totalReceipts: "$125.00",
          totalDisbursements: "$50.00",
          cashOnHand: "$75.00",
          transactionCount: 1
        }
      ],
      emptyMessage: null
    });
  });

  it("builds compact committee transaction rows with contributor person/org links and slug-aware recipient hrefs", () => {
    const rows = buildCommitteeTransactionRows([DEFAULT_TRANSACTION], {
      candidateById: {
        [CANDIDATE_ID]: {
          id: CANDIDATE_ID,
          slug: "candidate-one",
          slug_is_unique: true
        }
      },
      committeeById: {
        [COMMITTEE_ID]: {
          id: COMMITTEE_ID,
          slug: "committee-one",
          slug_is_unique: true
        }
      }
    });

    expect(rows).toEqual([
      {
        id: DEFAULT_TRANSACTION.id,
        date: "2026-03-19",
        amount: "125.00",
        transactionType: "contribution",
        contributorName: "Donor One",
        contributorPersonHref: `/person/${PERSON_ID}`,
        contributorPersonLabel: "View contributor person record",
        contributorOrgHref: `/org/${ORG_ID}`,
        contributorOrgLabel: "View contributor organization record",
        recipientCandidateHref: "/candidate/candidate-one",
        recipientCandidateLabel: "View recipient candidate record",
        recipientCommitteeHref: "/committee/committee-one",
        recipientCommitteeLabel: "View recipient committee record",
        ieStance: "—",
        disseminationDate: "—",
        aggregateAmount: "—"
      }
    ]);
  });

  it("returns stable empty messaging for committee transactions", () => {
    expect(getCampaignFinanceEmptyMessage()).toBe("No recent committee transactions found.");
  });

  it("builds empty transaction rows and empty message from standalone builders", () => {
    const rows = buildCommitteeTransactionRows([]);

    expect(rows).toEqual([]);
    expect(getCampaignFinanceEmptyMessage()).toBe("No recent committee transactions found.");
  });

  it("builds candidate aggregate fundraising totals and committee breakdown from summary", () => {
    const summary = {
      ...DEFAULT_CANDIDATE_SUMMARY,
      total_raised: "5000.00",
      total_spent: "2000.00",
      net: "3000.00",
      transaction_count: 42,
      itemized_transaction_count: 42,
      cash_on_hand: null,
      summary_source: "derived" as const,
      committees: [
        {
          ...DEFAULT_SUMMARY,
          committee_name: "Committee Alpha",
          slug: "committee-alpha",
          slug_is_unique: true,
          total_raised: "3000.00",
          total_spent: "1200.00",
          net: "1800.00",
          transaction_count: 25,
          data_through: "2026-03-15"
        },
        {
          ...DEFAULT_SUMMARY,
          committee_id: "99999999-9999-4999-8999-999999999999",
          committee_name: "Committee Beta",
          total_raised: "2000.00",
          total_spent: "800.00",
          net: "1200.00",
          transaction_count: 17,
          jurisdiction: "state/nc",
          data_through: "2026-03-10"
        }
      ]
    };

    const fundraisingSummary = buildCandidateAggregateSummaryPresentation(summary);
    const committeeBreakdown = buildCandidateCommitteeBreakdown(summary);

    expect(fundraisingSummary).toEqual({
      totalRaised: "$5,000.00",
      totalSpent: "$2,000.00",
      net: "$3,000.00",
      transactionCount: 42
    });
    expect(committeeBreakdown).toHaveLength(2);
    expect(committeeBreakdown[0]).toEqual({
      committeeId: COMMITTEE_ID,
      committeeName: "Committee Alpha",
      committeeHref: "/committee/committee-alpha",
      totalRaised: "$3,000.00",
      totalSpent: "$1,200.00",
      net: "$1,800.00",
      transactionCount: 25,
      jurisdiction: "federal/fec",
      dataThrough: "2026-03-15"
    });
    expect(committeeBreakdown[1]).toEqual({
      committeeId: "99999999-9999-4999-8999-999999999999",
      committeeName: "Committee Beta",
      committeeHref: "/committee/99999999-9999-4999-8999-999999999999",
      totalRaised: "$2,000.00",
      totalSpent: "$800.00",
      net: "$1,200.00",
      transactionCount: 17,
      jurisdiction: "state/nc",
      dataThrough: "2026-03-10"
    });
  });

  it("builds empty candidate aggregate summary and empty committee breakdown", () => {
    const fundraisingSummary = buildCandidateAggregateSummaryPresentation(DEFAULT_CANDIDATE_SUMMARY);
    const committeeBreakdown = buildCandidateCommitteeBreakdown(DEFAULT_CANDIDATE_SUMMARY);

    expect(fundraisingSummary).toEqual({
      totalRaised: "$0.00",
      totalSpent: "$0.00",
      net: "$0.00",
      transactionCount: 0
    });
    expect(committeeBreakdown).toEqual([]);
  });

  it("builds an L10 completeness warning when no candidate transactions were loaded", () => {
    expect(buildCandidateCompletenessWarnings(DEFAULT_CANDIDATE_SUMMARY, null)).toEqual([
      {
        message: "No transactions loaded for this candidate yet. Coverage may be incomplete.",
        methodologyHref: "/methodology"
      }
    ]);
  });

  it("builds an L10 completeness warning when the candidate total deviates from the anchor reference", () => {
    expect(
      buildCandidateCompletenessWarnings(
        {
          ...DEFAULT_CANDIDATE_SUMMARY,
          total_raised: "250.00",
          total_spent: "80.00",
          net: "170.00",
          transaction_count: 5
        },
        {
          totalRaised: "1000.00",
          sourceLabel: "NC SBOE anchor",
          methodologyHref: "/methodology",
          deviationThresholdRatio: 0.2
        }
      )
    ).toEqual([
      {
        message:
          "Civibus shows $250.00 raised, but the NC SBOE anchor reference is $1,000.00. Coverage may be incomplete.",
        methodologyHref: "/methodology"
      }
    ]);
  });

  it("builds candidate committee breakdown with null data_through and jurisdiction", () => {
    const summary = {
      ...DEFAULT_CANDIDATE_SUMMARY,
      total_raised: "100.00",
      total_spent: "50.00",
      net: "50.00",
      transaction_count: 1,
      committees: [
        {
          ...DEFAULT_SUMMARY,
          jurisdiction: null,
          data_through: null
        }
      ]
    };

    const committeeBreakdown = buildCandidateCommitteeBreakdown(summary);

    expect(committeeBreakdown[0].jurisdiction).toBe("—");
    expect(committeeBreakdown[0].dataThrough).toBe("—");
  });

  it("builds candidate deferred sections from resolved bundle payloads", async () => {
    const summary = await Promise.resolve({
      ...DEFAULT_CANDIDATE_SUMMARY,
      total_raised: "5000.00",
      total_spent: "2000.00",
      net: "3000.00",
      transaction_count: 42,
      committees: [{ ...DEFAULT_SUMMARY, total_raised: "5000.00", total_spent: "2000.00", net: "3000.00" }]
    });

    expect(buildCandidateDeferredFundraisingSummary(summary)).toEqual({
      totalRaised: "$5,000.00",
      totalSpent: "$2,000.00",
      net: "$3,000.00",
      transactionCount: 42
    });
    expect(buildCandidateDeferredCommitteeBreakdown(summary)).toHaveLength(1);
    expect(buildCandidateDeferredKeyMetrics(summary)).toEqual([
      { label: "Total raised", value: "$5,000.00" },
      { label: "Total spent", value: "$2,000.00" },
      { label: "Itemized transactions loaded", value: "42" }
    ]);
    expect(
      buildCandidateDeferredOutsideSpending(
        {
          ...DEFAULT_SELECTED_CYCLE_FIELDS,
          candidate_id: CANDIDATE_ID,
          support_total: "100.00",
          oppose_total: "0.00",
          support_count: 1,
          oppose_count: 0,
          top_spenders: [],
          excluded_outlier_count: 0
        },
        []
      ).explanatoryBlock
    ).toBe("Outside spending is independent and not controlled by the candidate committee.");
  });

  it("builds committee deferred sections from resolved bundle payloads", async () => {
    const summary = await Promise.resolve(DEFAULT_SUMMARY);
    const filingBreakdown = await Promise.resolve(DEFAULT_FILING_BREAKDOWN);
    const transactions = await Promise.resolve([DEFAULT_TRANSACTION]);

    expect(buildCommitteeDeferredFundraisingSummary(summary)).toEqual({
      totalRaised: "$125.00",
      totalSpent: "$50.00",
      net: "$75.00",
      transactionCount: 1,
      jurisdiction: "federal/fec",
      dataThrough: "2026-03-19",
      summarySourceLabel: "Derived from itemized transactions",
      itemizedCoverageNote:
        "Itemized transactions loaded: 1. Totals above are derived from these itemized transactions."
    });
    expect(buildCommitteeDeferredFilingBreakdown(filingBreakdown).rows).toHaveLength(1);
    expect(
      buildCommitteeDeferredTransactionRows(transactions, {
        candidateById: {
          [CANDIDATE_ID]: { id: CANDIDATE_ID, slug: "candidate-one", slug_is_unique: true }
        },
        committeeById: {
          [COMMITTEE_ID]: { id: COMMITTEE_ID, slug: "committee-one", slug_is_unique: true }
        }
      })
    ).toHaveLength(1);
    expect(buildCommitteeDeferredKeyMetrics(summary)).toEqual([
      { label: "Total raised", value: "$125.00" },
      { label: "Total spent", value: "$50.00" },
      { label: "Itemized transactions loaded", value: "1" }
    ]);

    expect(buildCommitteeDeferredHighSignalSummary(summary, filingBreakdown)).toEqual({
      receiptSplit: [
        { label: "Cash receipts", value: "$100.00" },
        { label: "In-kind receipts", value: "$15.00" },
        { label: "Loans", value: "$10.00" },
        { label: "Contributions", value: "$125.00" }
      ],
      topDonors: [{ name: "Donor One", totalAmount: "$80.00", transactionCountLabel: "2 transactions" }],
      topVendors: [{ name: "Vendor One", totalAmount: "$50.00", transactionCountLabel: "1 transaction" }],
      spendCategories: [
        { category: "media", totalAmount: "$25.00", transactionCountLabel: "1 transaction" }
      ],
      spendCategoriesEmptyMessage: null,
      cashOnHandTrend: {
        cycle: 2026,
        coverageThrough: "2026-12-31",
        sources: [],
        points: [{ periodEnd: "2026-03-31", amount: 75, missingIntervalBefore: false }]
      }
    });
  });

  it("normalizes committee filing cash-on-hand points from real coverage periods only", () => {
    const highSignal = buildCommitteeDeferredHighSignalSummary(DEFAULT_SUMMARY, {
      ...DEFAULT_FILING_BREAKDOWN,
      filings: [
        {
          ...DEFAULT_FILING_BREAKDOWN.filings[0],
          filing_id: "later",
          filing_fec_id: "FEC-200",
          coverage_start_date: "2026-05-01",
          coverage_end_date: "2026-06-30",
          receipt_date: "2026-07-15",
          cash_on_hand: "250.50",
          row_id: "later:N"
        },
        {
          ...DEFAULT_FILING_BREAKDOWN.filings[0],
          filing_id: "receipt-fallback-forbidden",
          filing_fec_id: "FEC-150",
          coverage_start_date: null,
          coverage_end_date: null,
          receipt_date: "2026-05-01",
          cash_on_hand: "175.00",
          row_id: "receipt-fallback-forbidden:N"
        },
        {
          ...DEFAULT_FILING_BREAKDOWN.filings[0],
          filing_id: "earlier",
          filing_fec_id: "FEC-100",
          coverage_start_date: "2026-01-01",
          coverage_end_date: "2026-03-31",
          cash_on_hand: "75.00",
          row_id: "earlier:N"
        },
        {
          ...DEFAULT_FILING_BREAKDOWN.filings[0],
          filing_id: "invalid-money",
          filing_fec_id: "FEC-999",
          coverage_start_date: "2026-07-01",
          coverage_end_date: "2026-09-30",
          cash_on_hand: "not-a-number",
          row_id: "invalid-money:N"
        }
      ]
    });

    expect(highSignal.cashOnHandTrend.points).toEqual([
      { periodEnd: "2026-03-31", amount: 75, missingIntervalBefore: false },
      { periodEnd: "2026-06-30", amount: 250.5, missingIntervalBefore: true }
    ]);
  });

  it("builds committee deferred outside-spending empty and populated states", () => {
    expect(
      buildCommitteeDeferredOutsideSpending({
        committee_id: COMMITTEE_ID,
        support_total: "0.00",
        oppose_total: "0.00",
        ie_transaction_count: 0,
        excluded_outlier_count: 0,
        targets: []
      })
    ).toEqual({
      supportTotal: "$0.00",
      opposeTotal: "$0.00",
      ieCountLabel: "0 expenditures",
      outlierNote: null,
      targetRows: [],
      sourceRows: [],
      emptyMessage: "This committee reported no independent expenditures"
    });

    const populated = buildCommitteeDeferredOutsideSpending({
      committee_id: COMMITTEE_ID,
      support_total: "200.00",
      oppose_total: "25.00",
      ie_transaction_count: 2,
      excluded_outlier_count: 2,
      targets: [
        {
          candidate_id: CANDIDATE_ID,
          fec_candidate_id: "H0NC01001",
          candidate_name: "Target Candidate",
          person_id: PERSON_ID,
          party: "DEM",
          office: "H",
          state: "NC",
          district: "01",
          slug: "target-candidate",
          slug_is_unique: true,
          support_total: "200.00",
          oppose_total: "25.00",
          transaction_count: 2,
          sources: []
        }
      ]
    });

    expect(populated.emptyMessage).toBeNull();
    expect(populated.ieCountLabel).toBe("2 expenditures");
    expect(populated.outlierNote).toBe(
      "2 reported independent expenditures were excluded from these totals as outliers."
    );
    expect(populated.targetRows[0].targetHref).toBe(`/person/${PERSON_ID}`);
  });

  it("builds explicit no-category and no-trend states when committee category data is unavailable", () => {
    const summary = {
      ...DEFAULT_SUMMARY,
      spend_categories: null
    };

    const highSignal = buildCommitteeDeferredHighSignalSummary(summary, {
      ...DEFAULT_FILING_BREAKDOWN,
      filings: [
        {
          ...DEFAULT_FILING_BREAKDOWN.filings[0],
          cash_on_hand: null
        }
      ]
    });

    expect(highSignal.spendCategories).toEqual([]);
    expect(highSignal.spendCategoriesEmptyMessage).toBe("Spend categories are not available for this committee.");
    expect(highSignal.cashOnHandTrend).toEqual({
      cycle: 2026,
      coverageThrough: "2026-12-31",
      sources: [],
      points: []
    });
  });

  it("maps IE-specific committee transaction fields through presenter-owned rows", () => {
    const rows = buildCommitteeTransactionRows([
      {
        ...DEFAULT_TRANSACTION,
        support_oppose: "S" as const,
        dissemination_date: "2026-03-20",
        aggregate_amount: 200
      }
    ]);

    expect(rows[0].ieStance).toBe("Support");
    expect(rows[0].disseminationDate).toBe("2026-03-20");
    expect(rows[0].aggregateAmount).toBe("$200.00");
  });

  it("adds an explanatory outside-spending block when IE data exists", () => {
    const outsideSpending = buildOutsideSpendingPresentation(
      {
        ...DEFAULT_SELECTED_CYCLE_FIELDS,
        candidate_id: CANDIDATE_ID,
        support_total: "100.00",
        oppose_total: "50.00",
        support_count: 1,
        oppose_count: 1,
        top_spenders: [],
        excluded_outlier_count: 0
      },
      []
    );

    expect(outsideSpending.explanatoryBlock).toBe(
      "Outside spending is independent and not controlled by the candidate committee."
    );
  });

  it("includes transaction-level outside-spending rows when IE data exists", () => {
    const filingId = "66666666-6666-4666-8666-666666666666";
    const outsideSpending = buildOutsideSpendingPresentation(
      {
        ...DEFAULT_SELECTED_CYCLE_FIELDS,
        candidate_id: CANDIDATE_ID,
        support_total: "100.00",
        oppose_total: "50.00",
        support_count: 1,
        oppose_count: 1,
        top_spenders: [],
        excluded_outlier_count: 0
      },
      [
        {
          id: "77777777-7777-4777-8777-777777777777",
          filing_id: filingId,
          committee_id: COMMITTEE_ID,
          committee_name: "Independent Expenditure Committee",
          amount: 100,
          transaction_date: "2026-03-19",
          purpose: "Independent expenditure",
          dissemination_date: "2026-03-20",
          aggregate_amount: 100,
          support_oppose: "S" as const
        }
      ]
    );

    expect(outsideSpending.transactionRows).toEqual([
      {
        rowKey: "77777777-7777-4777-8777-777777777777",
        date: "2026-03-19",
        disseminationDate: "2026-03-20",
        spender: "Independent Expenditure Committee",
        spenderHref: `/committee/${COMMITTEE_ID}`,
        stance: "Support",
        amount: "$100.00",
        sourceHref: `/v1/filings/${filingId}`
      }
    ]);
  });

  it("uses an outside-spending unavailable message when IE summary is missing", () => {
    const outsideSpending = buildOutsideSpendingPresentation(null, []);

    expect(outsideSpending.emptyMessage).toBe(
      "Outside-spending data is not yet available for this candidate. Coverage may be incomplete."
    );
  });

  it("uses a no-activity outside-spending message when summary totals are zero", () => {
    const outsideSpending = buildOutsideSpendingPresentation(
      {
        ...DEFAULT_SELECTED_CYCLE_FIELDS,
        candidate_id: CANDIDATE_ID,
        support_total: "0.00",
        oppose_total: "0.00",
        support_count: 0,
        oppose_count: 0,
        top_spenders: [],
        excluded_outlier_count: 0
      },
      []
    );

    expect(outsideSpending.explanatoryBlock).toBe(
      "Outside spending is independent and not controlled by the candidate committee."
    );
    expect(outsideSpending.emptyMessage).toBe(
      "No outside spending is reported in available filings. Coverage may be incomplete."
    );
  });

  it("builds key metrics from fundraising totals and transaction count", () => {
    const keyMetrics = buildKeyMetrics({
      total_raised: "5000.00",
      total_spent: "2000.00",
      transaction_count: 42
    });

    expect(keyMetrics).toEqual([
      { label: "Total raised", value: "$5,000.00" },
      { label: "Total spent", value: "$2,000.00" },
      { label: "Itemized transactions loaded", value: "42" }
    ]);
  });

  it("builds key metrics from candidate aggregate fundraising totals", () => {
    const keyMetrics = buildKeyMetrics({
      total_raised: "10000.00",
      total_spent: "3000.00",
      transaction_count: 100
    });

    expect(keyMetrics).toEqual([
      { label: "Total raised", value: "$10,000.00" },
      { label: "Total spent", value: "$3,000.00" },
      { label: "Itemized transactions loaded", value: "100" }
    ]);
  });

  it("provides empty messages from filing breakdown and transaction row builders", () => {
    const filingPresentation = buildFilingBreakdownPresentation({
      ...DEFAULT_FILING_BREAKDOWN,
      filings: []
    });
    const transactionRows = buildCommitteeTransactionRows([]);

    expect(filingPresentation.emptyMessage).toBe("No filing-period fundraising data available.");
    expect(transactionRows).toEqual([]);
    expect(getCampaignFinanceEmptyMessage()).toBe("No recent committee transactions found.");
  });
});
