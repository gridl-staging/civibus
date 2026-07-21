import { describe, expect, it } from "vitest";
import { buildTrustSection, PHL_FRESHNESS_NOTE } from "$lib/detail-trust/presentation";
import type { CommitteeDetailBundle } from "$lib/server/api/campaign-finance-detail";
import {
  buildCandidateDetailMetadata,
  buildCandidateDetailShellPresentation,
  buildCandidateFactRows,
  buildCandidateRoutePresentation,
  buildCommitteeCycleSummaryRows,
  buildCommitteeDetailMetadata,
  buildCommitteeDetailMetadataFromBundle,
  buildCommitteeDetailShellPresentation,
  buildCommitteeFactRows,
  buildCommitteeDeferredOutsideSpending,
  buildCommitteeRoutePresentation,
  buildFundraisingSummaryPresentation,
  buildKeyMetrics,
  buildLinkedCandidateLinks,
  buildPaginatedCommitteeFilingBreakdown,
  COMMITTEE_FILINGS_PAGE_SIZE
} from "./presentation";
import type { CommitteeFilingBreakdown, FilingPeriodSummary } from "./contract";
import {
  CANDIDATE_ID,
  COMMITTEE_ID,
  DEFAULT_CANDIDATE_DETAIL,
  DEFAULT_COMMITTEE_DETAIL,
  DEFAULT_FILING_BREAKDOWN,
  DEFAULT_SUMMARY,
  FILING_ID,
  ORG_ID,
  PERSON_ID,
  buildCandidateBundle,
  buildCommitteeBundle
} from "./presentation_test_fixtures";

describe("campaign finance detail presentation", () => {
  it("builds committee fact rows including routable canonical organization links", () => {
    const rows = buildCommitteeFactRows({
      ...DEFAULT_COMMITTEE_DETAIL,
      organization_id: ORG_ID,
      committee_type: "Q",
      committee_designation: "P",
      party: "DEM",
      state: "NC",
      city: "Raleigh",
      zip_code: "27601",
      treasurer_name: "Treasurer One"
    });

    expect(rows).toContainEqual({
      label: "Canonical organization",
      value: `Organization record (${ORG_ID})`,
      href: `/org/${ORG_ID}`
    });
  });

  it("builds candidate fact rows with routable person and principal committee links", () => {
    const rows = buildCandidateFactRows({
      id: CANDIDATE_ID,
      fec_candidate_id: "H0NC01001",
      name: "Candidate One",
      slug: "candidate-one",
      slug_is_unique: true,
      person_id: PERSON_ID,
      party: "DEM",
      office: "H",
      state: "NC",
      district: "01",
      incumbent_challenge: "I",
      principal_committee_id: COMMITTEE_ID,
      sources: []
    });

    expect(rows).toContainEqual({
      label: "Canonical person",
      value: `Person record (${PERSON_ID})`,
      href: `/person/${PERSON_ID}`
    });
    expect(rows).toContainEqual({
      label: "Principal committee",
      value: `Committee record (${COMMITTEE_ID})`,
      href: `/committee/${COMMITTEE_ID}`
    });
  });

  it("builds committee trust-section data from the shared trust contract", () => {
    const sources = [
      {
        domain: "campaign_finance",
        jurisdiction: "federal/fec",
        data_source_name: "FEC",
        data_source_url: "https://www.fec.gov",
        source_record_key: "committee-1",
        record_url: "https://example.org/committee-1",
        pull_date: "2026-03-19T00:00:00Z"
      }
    ];
    const shell = buildCommitteeDetailShellPresentation({ ...DEFAULT_COMMITTEE_DETAIL, sources });

    expect(shell.trustSection).toEqual(buildTrustSection(sources));
  });

  it("builds candidate trust-section data from the shared trust contract when provenance is empty", () => {
    const shell = buildCandidateDetailShellPresentation(DEFAULT_CANDIDATE_DETAIL);

    expect(shell.trustSection).toEqual(buildTrustSection([]));
  });

  it("does not surface the retired Indiana freshness warning on campaign-finance detail pages", () => {
    // IN re-verdicted to weekly-or-better 2026-04-26
    // (see docs/reference/research/in_freshness_recheck_2026_04_26.md). The
    // Indiana-specific banner is retired; campaign-finance committee
    // and candidate shells must no longer surface it for IN sources.
    const sources = [
      {
        domain: "campaign_finance",
        jurisdiction: "state/IN",
        data_source_name: "Indiana Campaign Finance",
        data_source_url: "https://campaignfinance.in.gov/PublicSite/Reporting/DataDownload.aspx",
        source_record_key: "committee-1",
        record_url: "https://example.org/committee-1",
        pull_date: "2026-03-19T00:00:00Z"
      }
    ];

    const committeeShell = buildCommitteeDetailShellPresentation({ ...DEFAULT_COMMITTEE_DETAIL, sources });
    const candidateShell = buildCandidateDetailShellPresentation({ ...DEFAULT_CANDIDATE_DETAIL, sources });

    expect(committeeShell.trustSection.freshnessNote).toBeNull();
    expect(candidateShell.trustSection.freshnessNote).toBeNull();
  });

  it("surfaces the Philadelphia freshness warning on campaign-finance detail pages", () => {
    const sources = [
      {
        domain: "campaign_finance",
        jurisdiction: "municipality/PHL",
        data_source_name: "Philadelphia Campaign Finance",
        data_source_url: "https://opendataphilly.org/",
        source_record_key: "committee-1",
        record_url: "https://example.org/committee-1",
        pull_date: "2026-03-19T00:00:00Z"
      }
    ];

    const committeeShell = buildCommitteeDetailShellPresentation({ ...DEFAULT_COMMITTEE_DETAIL, sources });
    const candidateShell = buildCandidateDetailShellPresentation({ ...DEFAULT_CANDIDATE_DETAIL, sources });

    expect(committeeShell.trustSection.freshnessNote).toBe(PHL_FRESHNESS_NOTE);
    expect(candidateShell.trustSection.freshnessNote).toBe(PHL_FRESHNESS_NOTE);
  });

  it("does not duplicate route metadata inside the committee detail shell", () => {
    const shell = buildCommitteeDetailShellPresentation(DEFAULT_COMMITTEE_DETAIL);

    expect("metadata" in shell).toBe(false);
  });

  it("does not duplicate route metadata inside the candidate detail shell", () => {
    const shell = buildCandidateDetailShellPresentation(DEFAULT_CANDIDATE_DETAIL);

    expect("metadata" in shell).toBe(false);
  });

  it("builds committee metadata from canonical name", () => {
    expect(buildCommitteeDetailMetadata("Committee One")).toEqual({
      title: "Committee One | Committee | Civibus",
      description: "Committee profile from campaign-finance records."
    });
  });

  it("builds candidate metadata from canonical candidate name", () => {
    expect(buildCandidateDetailMetadata("Candidate One")).toEqual({
      title: "Candidate One | Candidate | Civibus",
      description: "Candidate profile from campaign-finance records."
    });
  });

  it("falls back to a generic committee canonical name when detail name is blank", () => {
    const shell = buildCommitteeDetailShellPresentation({ ...DEFAULT_COMMITTEE_DETAIL, name: "" });

    expect(shell.canonicalName).toBe("Committee");
  });

  it("falls back to a generic candidate canonical name when detail name is blank", () => {
    const shell = buildCandidateDetailShellPresentation({ ...DEFAULT_CANDIDATE_DETAIL, name: "" });

    expect(shell.canonicalName).toBe("Candidate");
  });

  it("builds committee route metadata from shell-only detail (no transaction count)", () => {
    expect(
      buildCommitteeDetailMetadataFromBundle({ detail: DEFAULT_COMMITTEE_DETAIL } as CommitteeDetailBundle)
    ).toEqual({
      title: "Committee One | Committee | Civibus",
      description: "Committee profile from campaign-finance records."
    });
  });

  it("falls back to generic committee metadata when detail name is empty", () => {
    expect(
      buildCommitteeDetailMetadataFromBundle({
        detail: { ...DEFAULT_COMMITTEE_DETAIL, name: "" }
      } as CommitteeDetailBundle)
    ).toEqual({
      title: "Committee | Committee | Civibus",
      description: "Committee profile from campaign-finance records."
    });
  });

  it("builds candidate route presentation for canonical and slug-collision route states", () => {
    const canonicalPresentation = buildCandidateRoutePresentation({
      routeKind: "canonical-detail",
      ...buildCandidateBundle()
    });
    const collisionPresentation = buildCandidateRoutePresentation({
      routeKind: "slug-collision",
      slug: "candidate-one",
      matches: [
        {
          id: CANDIDATE_ID,
          fec_candidate_id: "H0NC01001",
          name: "Candidate One",
          party: "DEM",
          office: "H",
          state: "NC",
          district: "01",
          slug: "candidate-one",
          slug_is_unique: true
        },
        {
          id: "99999999-9999-4999-8999-999999999999",
          fec_candidate_id: "H0NC01002",
          name: "Candidate Two",
          party: "DEM",
          office: "H",
          state: "NC",
          district: "02",
          slug: "candidate-one",
          slug_is_unique: false
        }
      ]
    });

    expect(canonicalPresentation.routeKind).toBe("canonical-detail");
    expect(canonicalPresentation.entityType).toBe("candidate");
    if (canonicalPresentation.routeKind === "canonical-detail") {
      expect(canonicalPresentation.shell.canonicalName).toBe("Candidate One");
      expect(canonicalPresentation.summary).toBeInstanceOf(Promise);
      expect(canonicalPresentation.ieTransactions).toBeInstanceOf(Promise);
      expect(canonicalPresentation.ieSummary).toBeInstanceOf(Promise);
      expect("detail" in canonicalPresentation).toBe(false);
    }
    expect(collisionPresentation).toEqual({
      routeKind: "slug-collision",
      entityType: "candidate",
      slug: "candidate-one",
      heading: 'Multiple candidates match "candidate-one"',
      chooserLabel: "Select a candidate record",
      matches: [
        {
          id: CANDIDATE_ID,
          name: "Candidate One",
          href: "/candidate/candidate-one"
        },
        {
          id: "99999999-9999-4999-8999-999999999999",
          name: "Candidate Two",
          href: "/candidate/99999999-9999-4999-8999-999999999999"
        }
      ]
    });
  });

  it("builds committee route presentation for canonical and slug-collision route states", () => {
    const canonicalPresentation = buildCommitteeRoutePresentation({
      routeKind: "canonical-detail",
      ...buildCommitteeBundle()
    });
    const collisionPresentation = buildCommitteeRoutePresentation({
      routeKind: "slug-collision",
      slug: "committee-one",
      matches: [
        {
          id: COMMITTEE_ID,
          fec_committee_id: "C12345678",
          name: "Committee One",
          committee_type: "Q",
          party: "DEM",
          state: "NC",
          slug: "committee-one",
          slug_is_unique: true
        },
        {
          id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
          fec_committee_id: "C00000000",
          name: "Committee Two",
          committee_type: "P",
          party: "DEM",
          state: "NC",
          slug: "committee-one",
          slug_is_unique: false
        }
      ]
    });

    expect(canonicalPresentation.routeKind).toBe("canonical-detail");
    expect(canonicalPresentation.entityType).toBe("committee");
    if (canonicalPresentation.routeKind === "canonical-detail") {
      expect(canonicalPresentation.shell.canonicalName).toBe("Committee One");
      expect(canonicalPresentation.transactions).toBeInstanceOf(Promise);
      expect(canonicalPresentation.summary).toBeInstanceOf(Promise);
      expect(canonicalPresentation.filingBreakdown).toBeInstanceOf(Promise);
      expect(canonicalPresentation.independentExpendituresMade).toBeInstanceOf(Promise);
      expect("detail" in canonicalPresentation).toBe(false);
    }
    expect(collisionPresentation).toEqual({
      routeKind: "slug-collision",
      entityType: "committee",
      slug: "committee-one",
      heading: 'Multiple committees match "committee-one"',
      chooserLabel: "Select a committee record",
      matches: [
        {
          id: COMMITTEE_ID,
          name: "Committee One",
          href: "/committee/committee-one"
        },
        {
          id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
          name: "Committee Two",
          href: "/committee/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        }
      ]
    });
  });

  it("emits a section order for committee detail with summary before trust before metrics before outside-spending before deep records", () => {
    const shell = buildCommitteeDetailShellPresentation(DEFAULT_COMMITTEE_DETAIL);

    expect(shell.sectionOrder).toEqual([
      "summary",
      "trust",
      "metrics",
      "outside-spending",
      "records"
    ]);
  });

  it("builds committee-made outside spending rows with person links and source-filing links", () => {
    const presentation = buildCommitteeDeferredOutsideSpending({
      committee_id: COMMITTEE_ID,
      support_total: "1500.00",
      oppose_total: "250.00",
      ie_transaction_count: 3,
      excluded_outlier_count: 1,
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
          support_total: "1500.00",
          oppose_total: "250.00",
          transaction_count: 3,
          sources: [
            {
              domain: "campaign_finance",
              jurisdiction: "federal/fec",
              data_source_name: "FEC Schedule E",
              data_source_url: "https://www.fec.gov",
              source_record_key: "schedule-e-source",
              record_url: "https://www.fec.gov/data/independent-expenditures/",
              pull_date: "2026-07-08T00:00:00Z"
            }
          ]
        }
      ]
    });

    expect(presentation).toEqual({
      supportTotal: "$1,500.00",
      opposeTotal: "$250.00",
      ieCountLabel: "3 expenditures",
      outlierNote: "1 reported independent expenditure was excluded from these totals as an outlier.",
      emptyMessage: null,
      targetRows: [
        {
          rowKey: CANDIDATE_ID,
          candidateName: "Target Candidate",
          targetHref: `/person/${PERSON_ID}`,
          context: "H · NC · District 01 · DEM",
          supportTotal: "$1,500.00",
          opposeTotal: "$250.00",
          transactionCountLabel: "3 expenditures"
        }
      ],
      sourceRows: [
        {
          rowKey: `${CANDIDATE_ID}:schedule-e-source:0`,
          candidateName: "Target Candidate",
          sourceName: "FEC Schedule E",
          sourceRecordKey: "schedule-e-source",
          href: "https://www.fec.gov/data/independent-expenditures/"
        }
      ]
    });
  });

  it("uses stable committee outside-spending row keys when target names repeat", () => {
    const presentation = buildCommitteeDeferredOutsideSpending({
      committee_id: COMMITTEE_ID,
      support_total: "300.00",
      oppose_total: "0.00",
      ie_transaction_count: 2,
      excluded_outlier_count: 0,
      targets: [
        {
          candidate_id: CANDIDATE_ID,
          fec_candidate_id: "H0NC01001",
          candidate_name: "Duplicate Name",
          person_id: PERSON_ID,
          party: "DEM",
          office: "H",
          state: "NC",
          district: "01",
          slug: "duplicate-name",
          slug_is_unique: false,
          support_total: "100.00",
          oppose_total: "0.00",
          transaction_count: 1,
          sources: [
            {
              domain: "campaign_finance",
              jurisdiction: "federal/fec",
              data_source_name: "FEC Schedule E",
              data_source_url: "https://www.fec.gov",
              source_record_key: "same-source-key",
              record_url: "https://www.fec.gov/data/independent-expenditures/one/",
              pull_date: "2026-07-08T00:00:00Z"
            }
          ]
        },
        {
          candidate_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
          fec_candidate_id: "H0NC01002",
          candidate_name: "Duplicate Name",
          person_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
          party: "REP",
          office: "H",
          state: "NC",
          district: "02",
          slug: "duplicate-name",
          slug_is_unique: false,
          support_total: "200.00",
          oppose_total: "0.00",
          transaction_count: 1,
          sources: [
            {
              domain: "campaign_finance",
              jurisdiction: "federal/fec",
              data_source_name: "FEC Schedule E",
              data_source_url: "https://www.fec.gov",
              source_record_key: "same-source-key",
              record_url: "https://www.fec.gov/data/independent-expenditures/two/",
              pull_date: "2026-07-08T00:00:00Z"
            }
          ]
        }
      ]
    });

    expect(presentation.targetRows.map((row) => row.rowKey)).toEqual([
      CANDIDATE_ID,
      "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    ]);
    expect(presentation.sourceRows.map((row) => row.rowKey)).toEqual([
      `${CANDIDATE_ID}:same-source-key:0`,
      "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa:same-source-key:0"
    ]);
  });

  it("emits a section order for candidate detail with summary before trust before metrics before outside-spending before records", () => {
    const shell = buildCandidateDetailShellPresentation(DEFAULT_CANDIDATE_DETAIL);

    expect(shell.sectionOrder).toEqual([
      "summary",
      "trust",
      "metrics",
      "outside-spending",
      "records"
    ]);
  });

  it("keeps official positive committee totals in key metrics when itemized transactions are absent", () => {
    const summary = {
      ...DEFAULT_SUMMARY,
      total_raised: "1000000.00",
      total_spent: "500000.00",
      net: "500000.00",
      transaction_count: 0,
      itemized_transaction_count: 0,
      cycle_summaries: [],
      summary_source: "fec_committee_summary" as const
    };

    const metrics = buildKeyMetrics(summary);

    expect(metrics).toEqual([
      { label: "Total raised", value: "$1,000,000.00" },
      { label: "Total spent", value: "$500,000.00" },
      { label: "Itemized transactions loaded", value: "0" }
    ]);
  });

  it("labels the committee summary source and itemized coverage note distinctly from official totals", () => {
    const officialSummary = {
      ...DEFAULT_SUMMARY,
      total_raised: "1000000.00",
      total_spent: "500000.00",
      net: "500000.00",
      transaction_count: 0,
      itemized_transaction_count: 0,
      cycle_summaries: [],
      summary_source: "fec_committee_summary" as const
    };
    const derivedSummary = {
      ...DEFAULT_SUMMARY,
      transaction_count: 3,
      itemized_transaction_count: 3,
      summary_source: "derived" as const
    };

    const officialPresentation = buildFundraisingSummaryPresentation(officialSummary);
    const derivedPresentation = buildFundraisingSummaryPresentation(derivedSummary);

    expect(officialPresentation.summarySourceLabel).toBe("Official FEC committee summary");
    expect(officialPresentation.itemizedCoverageNote).toBe(
      "Itemized transactions loaded: 0. Official totals above come directly from the FEC committee summary and are not derived from these transactions."
    );
    expect(derivedPresentation.summarySourceLabel).toBe("Derived from itemized transactions");
    expect(derivedPresentation.itemizedCoverageNote).toBe(
      "Itemized transactions loaded: 3. Totals above are derived from these itemized transactions."
    );
  });

  it("formats committee cycle summary rows with coverage ranges and currency-formatted totals", () => {
    const rows = buildCommitteeCycleSummaryRows({
      ...DEFAULT_SUMMARY,
      cycle_summaries: [
        {
          cycle: 2026,
          total_receipts: "500000.00",
          total_disbursements: "250000.00",
          cash_on_hand: "250000.00",
          coverage_start_date: "2025-01-01",
          coverage_end_date: "2026-06-30"
        },
        {
          cycle: 2024,
          total_receipts: "800000.00",
          total_disbursements: "780000.00",
          cash_on_hand: null,
          coverage_start_date: null,
          coverage_end_date: null
        }
      ]
    });

    expect(rows).toEqual([
      {
        cycle: 2026,
        cycleLabel: "2026",
        coveragePeriod: "2025-01-01 to 2026-06-30",
        totalReceipts: "$500,000.00",
        totalDisbursements: "$250,000.00",
        cashOnHand: "$250,000.00"
      },
      {
        cycle: 2024,
        cycleLabel: "2024",
        coveragePeriod: "—",
        totalReceipts: "$800,000.00",
        totalDisbursements: "$780,000.00",
        cashOnHand: "—"
      }
    ]);
  });

  it("builds linked-candidate links using slug-aware canonical candidate routes", () => {
    const links = buildLinkedCandidateLinks({
      ...DEFAULT_COMMITTEE_DETAIL,
      linked_candidates: [
        {
          id: CANDIDATE_ID,
          fec_candidate_id: "H0LA04001",
          name: "Mike Johnson",
          party: "REP",
          office: "H",
          state: "LA",
          district: "04",
          slug: "mike-johnson",
          slug_is_unique: true
        },
        {
          id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
          fec_candidate_id: "H0LA04002",
          name: "Other Candidate",
          party: null,
          office: "H",
          state: "LA",
          district: null,
          slug: "other-candidate",
          slug_is_unique: false
        }
      ]
    });

    expect(links).toEqual([
      {
        candidateId: CANDIDATE_ID,
        name: "Mike Johnson",
        context: "H · LA · District 04 · REP",
        href: "/candidate/mike-johnson"
      },
      {
        candidateId: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
        name: "Other Candidate",
        context: "H · LA",
        href: "/candidate/eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
      }
    ]);
  });

  it("includes linked-candidate presentations on the committee shell so the summary section can link out", () => {
    const shell = buildCommitteeDetailShellPresentation({
      ...DEFAULT_COMMITTEE_DETAIL,
      linked_candidates: [
        {
          id: CANDIDATE_ID,
          fec_candidate_id: "H0LA04001",
          name: "Mike Johnson",
          party: "REP",
          office: "H",
          state: "LA",
          district: "04",
          slug: "mike-johnson",
          slug_is_unique: true
        }
      ]
    });

    expect(shell.linkedCandidates).toEqual([
      {
        candidateId: CANDIDATE_ID,
        name: "Mike Johnson",
        context: "H · LA · District 04 · REP",
        href: "/candidate/mike-johnson"
      }
    ]);
  });

});

// Local fixture builders for the client-paginated filing table seam. The 60-row
// fixture is deliberately supplied out of coverage-date order so ordering bugs
// (e.g. rendering raw API order or reversing the chronological trend array)
// cannot pass by accident.
function makeFilingRow(sequence: number, coverageEndDate: string | null): FilingPeriodSummary {
  const filingId = `filing-${String(sequence).padStart(3, "0")}`;
  return {
    filing_id: filingId,
    filing_fec_id: `FEC-${filingId}`,
    filing_name: `${filingId} name`,
    report_type: "Q1",
    amendment_indicator: "N",
    coverage_start_date: coverageEndDate,
    coverage_end_date: coverageEndDate,
    receipt_date: coverageEndDate,
    total_raised: "0.00",
    total_spent: "0.00",
    net: "0.00",
    transaction_count: 0,
    cash_on_hand: "0.00",
    row_id: `${filingId}:N`
  };
}

// Distinct dates that increase monotonically with the sequence number, so a
// higher filing-NNN identity is strictly newer. 2015-01 through 2019-12 covers
// 60 distinct month-ends without spilling past a two-digit month.
function monotonicCoverageEndDate(sequence: number): string {
  const year = 2015 + Math.floor((sequence - 1) / 12);
  const month = String(((sequence - 1) % 12) + 1).padStart(2, "0");
  return `${year}-${month}-28`;
}

// Reorders 1..count via an index permutation (stride 37 is coprime with 60),
// producing a stable but clearly non-sorted API order.
function buildUnorderedFilings(count: number): FilingPeriodSummary[] {
  const orderedRows = Array.from({ length: count }, (_, index) =>
    makeFilingRow(index + 1, monotonicCoverageEndDate(index + 1))
  );
  return Array.from({ length: count }, (_, index) => orderedRows[(index * 37) % count]);
}

function rowIdentities(rows: { filingId: string }[]): string[] {
  return rows.map((row) => row.filingId);
}

describe("buildPaginatedCommitteeFilingBreakdown", () => {
  const SIXTY_ROW_BREAKDOWN: CommitteeFilingBreakdown = {
    committee_id: "cmte-60",
    committee_name: "Sixty Filing Committee",
    total_filings: 60,
    store_limit: 200,
    filings: buildUnorderedFilings(60)
  };

  it("exports the 25-row page size", () => {
    expect(COMMITTEE_FILINGS_PAGE_SIZE).toBe(25);
  });

  it("formats each row's coverage period, dates, and currency", () => {
    const page = buildPaginatedCommitteeFilingBreakdown(DEFAULT_FILING_BREAKDOWN, null);

    expect(page.rows).toEqual([
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
    ]);
  });

  it("renders newest-first page 1 with an honest recent-vs-all-time label", () => {
    const page = buildPaginatedCommitteeFilingBreakdown(SIXTY_ROW_BREAKDOWN, null);

    expect(page.rows).toHaveLength(25);
    expect(page.rows[0].filingId).toBe("filing-060");
    expect(page.rows[24].filingId).toBe("filing-036");
    expect(page.normalizedOffset).toBe(0);
    expect(page.emptyMessage).toBeNull();
    expect(page.label).toBe("Showing 1–25 of 60 most recent · 60 total filings");
    expect(page.pagination.hasPrevious).toBe(false);
    expect(page.pagination.hasNext).toBe(true);
  });

  it("renders the middle page 2 with both previous and next controls", () => {
    const page = buildPaginatedCommitteeFilingBreakdown(SIXTY_ROW_BREAKDOWN, "25");

    expect(page.rows).toHaveLength(25);
    expect(page.rows[0].filingId).toBe("filing-035");
    expect(page.rows[24].filingId).toBe("filing-011");
    expect(page.normalizedOffset).toBe(25);
    expect(page.label).toBe("Showing 26–50 of 60 most recent · 60 total filings");
    expect(page.pagination.hasPrevious).toBe(true);
    expect(page.pagination.hasNext).toBe(true);
  });

  it("renders the final 10-row page 3 with no next control", () => {
    const page = buildPaginatedCommitteeFilingBreakdown(SIXTY_ROW_BREAKDOWN, "50");

    expect(page.rows).toHaveLength(10);
    expect(page.rows[0].filingId).toBe("filing-010");
    expect(page.rows[9].filingId).toBe("filing-001");
    expect(page.normalizedOffset).toBe(50);
    expect(page.label).toBe("Showing 51–60 of 60 most recent · 60 total filings");
    expect(page.pagination.hasPrevious).toBe(true);
    expect(page.pagination.hasNext).toBe(false);
  });

  it("labels a bounded 200-row recent window against a large all-time count", () => {
    const breakdown: CommitteeFilingBreakdown = {
      committee_id: "cmte-200",
      committee_name: "Bounded Window Committee",
      total_filings: 220706,
      store_limit: 200,
      filings: buildUnorderedFilings(200)
    };

    const page = buildPaginatedCommitteeFilingBreakdown(breakdown, null);

    expect(page.rows).toHaveLength(25);
    expect(page.label).toBe("Showing 1–25 of 200 most recent · 220,706 total filings");
    expect(page.pagination.hasNext).toBe(true);
  });

  it("returns the empty-window presentation with no label or controls", () => {
    const page = buildPaginatedCommitteeFilingBreakdown(
      { committee_id: "cmte-empty", committee_name: "Empty Committee", filings: [] },
      "50"
    );

    expect(page.rows).toHaveLength(0);
    expect(page.emptyMessage).toBe("No filing-period fundraising data available.");
    expect(page.label).toBeNull();
    expect(page.normalizedOffset).toBe(0);
    expect(page.pagination.hasPrevious).toBe(false);
    expect(page.pagination.hasNext).toBe(false);
  });

  it("orders equal coverage-end dates by their original API order", () => {
    const breakdown: CommitteeFilingBreakdown = {
      committee_id: "cmte-ties",
      committee_name: "Equal Date Committee",
      filings: [
        makeFilingRow(1, "2021-06-30"),
        makeFilingRow(2, "2021-06-30")
      ]
    };

    const page = buildPaginatedCommitteeFilingBreakdown(breakdown, null);

    expect(rowIdentities(page.rows)).toEqual(["filing-001", "filing-002"]);
  });

  it("sorts undated filings after dated ones while keeping their API order", () => {
    const breakdown: CommitteeFilingBreakdown = {
      committee_id: "cmte-undated",
      committee_name: "Undated Committee",
      filings: [
        makeFilingRow(1, null),
        makeFilingRow(2, "2021-06-30"),
        makeFilingRow(3, "not-a-date")
      ]
    };

    const page = buildPaginatedCommitteeFilingBreakdown(breakdown, null);

    expect(rowIdentities(page.rows)).toEqual(["filing-002", "filing-001", "filing-003"]);
  });

  it("orders newest-first with ties, undated, and invalid dates in a single window", () => {
    const breakdown: CommitteeFilingBreakdown = {
      committee_id: "cmte-shared-ordering",
      committee_name: "Shared Ordering Committee",
      filings: [
        makeFilingRow(1, null),
        makeFilingRow(2, "2021-06-30"),
        makeFilingRow(3, "not-a-date"),
        makeFilingRow(4, "2022-01-31"),
        makeFilingRow(5, "2021-06-30"),
        makeFilingRow(6, null)
      ]
    };

    expect(rowIdentities(buildPaginatedCommitteeFilingBreakdown(breakdown, null).rows)).toEqual([
      "filing-004",
      "filing-002",
      "filing-005",
      "filing-001",
      "filing-003",
      "filing-006"
    ]);
  });

  it("normalizes malformed offsets to the first page", () => {
    for (const rawOffset of [undefined, null, "", "abc", "25.5", "+25", "-25", "-5"]) {
      const page = buildPaginatedCommitteeFilingBreakdown(SIXTY_ROW_BREAKDOWN, rawOffset);
      expect(page.normalizedOffset).toBe(0);
      expect(page.rows[0].filingId).toBe("filing-060");
    }
  });

  it("rounds positive offsets down to the nearest page boundary", () => {
    expect(buildPaginatedCommitteeFilingBreakdown(SIXTY_ROW_BREAKDOWN, "10").normalizedOffset).toBe(0);
    expect(buildPaginatedCommitteeFilingBreakdown(SIXTY_ROW_BREAKDOWN, "26").normalizedOffset).toBe(25);
    expect(buildPaginatedCommitteeFilingBreakdown(SIXTY_ROW_BREAKDOWN, "26").rows[0].filingId).toBe(
      "filing-035"
    );
  });

  it("clamps beyond-window offsets to the last non-empty page boundary", () => {
    expect(buildPaginatedCommitteeFilingBreakdown(SIXTY_ROW_BREAKDOWN, "75").normalizedOffset).toBe(50);
    expect(buildPaginatedCommitteeFilingBreakdown(SIXTY_ROW_BREAKDOWN, "100000").normalizedOffset).toBe(
      50
    );
  });

  it("clamps digit-only offsets beyond JS number range to the last non-empty page boundary", () => {
    const overflowingOffset = "9".repeat(400);
    expect(Number.isFinite(Number(overflowingOffset))).toBe(false);
    expect(
      buildPaginatedCommitteeFilingBreakdown(SIXTY_ROW_BREAKDOWN, overflowingOffset).normalizedOffset
    ).toBe(50);
  });

  it("clamps any offset to zero for an empty window", () => {
    const page = buildPaginatedCommitteeFilingBreakdown(
      { committee_id: "cmte-empty", committee_name: "Empty Committee", filings: [] },
      "100"
    );
    expect(page.normalizedOffset).toBe(0);
  });
});
