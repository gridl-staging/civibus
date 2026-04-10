import { describe, expect, it } from "vitest";
import { buildTrustSection } from "$lib/detail-trust/presentation";
import type { CandidateDetailBundle, CommitteeDetailBundle } from "$lib/server/api/campaign-finance-detail";
import {
  buildCandidateDetailMetadata,
  buildCandidateDetailPresentation,
  buildCandidateFactRows,
  buildCandidateRoutePresentation,
  buildCommitteeDetailMetadata,
  buildCommitteeDetailMetadataFromBundle,
  buildCommitteeDetailPresentation,
  buildCommitteeFactRows,
  buildCommitteeRoutePresentation,
  buildCommitteeTransactionRows,
  buildFilingBreakdownPresentation,
  buildFundraisingSummaryPresentation,
  formatCurrency,
  getCampaignFinanceEmptyMessage
} from "./presentation";

const COMMITTEE_ID = "33333333-3333-4333-8333-333333333333";
const CANDIDATE_ID = "44444444-4444-4444-8444-444444444444";
const PERSON_ID = "11111111-1111-4111-8111-111111111111";
const ORG_ID = "22222222-2222-4222-8222-222222222222";
const FILING_ID = "66666666-6666-4666-8666-666666666666";

const DEFAULT_COMMITTEE_DETAIL = {
  id: COMMITTEE_ID,
  fec_committee_id: "C12345678",
  name: "Committee One",
  slug: "committee-one",
  slug_is_unique: true,
  organization_id: null,
  committee_type: null,
  committee_designation: null,
  party: null,
  state: null,
  city: null,
  zip_code: null,
  treasurer_name: null,
  sources: []
};

const DEFAULT_SUMMARY = {
  committee_id: COMMITTEE_ID,
  committee_name: "Committee One",
  total_raised: "125.00",
  total_spent: "50.00",
  net: "75.00",
  transaction_count: 1,
  jurisdiction: "federal/fec",
  data_through: "2026-03-19T00:00:00Z"
};

const DEFAULT_FILING_PERIOD = {
  filing_id: FILING_ID,
  filing_fec_id: "FEC-100",
  filing_name: "Q1 filing",
  report_type: "Q1",
  amendment_indicator: "N",
  coverage_start_date: "2026-01-01",
  coverage_end_date: "2026-03-31",
  receipt_date: "2026-04-10",
  total_raised: "125.00",
  total_spent: "50.00",
  net: "75.00",
  transaction_count: 1
};

const DEFAULT_FILING_BREAKDOWN = {
  committee_id: COMMITTEE_ID,
  committee_name: "Committee One",
  filings: [DEFAULT_FILING_PERIOD]
};

const DEFAULT_TRANSACTION = {
  id: "55555555-5555-4555-8555-555555555555",
  filing_id: FILING_ID,
  committee_id: COMMITTEE_ID,
  transaction_type: "contribution",
  transaction_identifier: "TX-1",
  transaction_date: "2026-03-19",
  amount: 125,
  contributor_name_raw: "Donor One",
  contributor_employer: null,
  contributor_occupation: null,
  contributor_city: null,
  contributor_state: null,
  contributor_zip: null,
  contributor_person_id: PERSON_ID,
  contributor_organization_id: ORG_ID,
  contributor_address_id: null,
  recipient_candidate_id: CANDIDATE_ID,
  recipient_committee_id: COMMITTEE_ID,
  memo_text: null,
  is_memo: false,
  amendment_indicator: "N",
  date_is_reliable: true
};

const DEFAULT_CANDIDATE_DETAIL = {
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
  sources: [] as Array<{
    domain: string;
    jurisdiction: string | null;
    data_source_name: string;
    data_source_url: string;
    source_record_key: string | null;
    record_url: string | null;
    pull_date: string;
  }>
};

const DEFAULT_CANDIDATE_SUMMARY = {
  candidate_id: CANDIDATE_ID,
  candidate_name: "Candidate One",
  total_raised: "0.00",
  total_spent: "0.00",
  net: "0.00",
  transaction_count: 0,
  committees: []
};

function buildCandidateBundle(overrides: Partial<CandidateDetailBundle> = {}): CandidateDetailBundle {
  return {
    detail: DEFAULT_CANDIDATE_DETAIL,
    summary: DEFAULT_CANDIDATE_SUMMARY,
    ieTransactions: [],
    ieSummary: null,
    ...overrides
  };
}

function buildCommitteeBundle(overrides: Partial<CommitteeDetailBundle> = {}): CommitteeDetailBundle {
  return {
    detail: DEFAULT_COMMITTEE_DETAIL,
    transactions: [],
    summary: DEFAULT_SUMMARY,
    filingBreakdown: DEFAULT_FILING_BREAKDOWN,
    ...overrides
  };
}

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
      dataThrough: "2026-03-19"
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
          totalRaised: "$125.00",
          totalSpent: "$50.00",
          net: "$75.00",
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
        recipientCommitteeLabel: "View recipient committee record"
      }
    ]);
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
    const presentation = buildCommitteeDetailPresentation(
      buildCommitteeBundle({
        detail: {
          ...DEFAULT_COMMITTEE_DETAIL,
          sources
        }
      })
    );

    expect(presentation.trustSection).toEqual(buildTrustSection(sources));
  });

  it("builds candidate trust-section data from the shared trust contract when provenance is empty", () => {
    const presentation = buildCandidateDetailPresentation(buildCandidateBundle());

    expect(presentation.trustSection).toEqual(buildTrustSection([]));
  });

  it("does not duplicate route metadata inside the committee detail view model", () => {
    const presentation = buildCommitteeDetailPresentation(buildCommitteeBundle());

    expect("metadata" in presentation).toBe(false);
  });

  it("does not duplicate route metadata inside the candidate detail view model", () => {
    const presentation = buildCandidateDetailPresentation(buildCandidateBundle());

    expect("metadata" in presentation).toBe(false);
  });

  it("returns stable empty messaging for committee transactions", () => {
    expect(getCampaignFinanceEmptyMessage()).toBe("No recent committee transactions found.");
  });

  it("builds committee view-model empty transaction message when backend slice is empty", () => {
    const presentation = buildCommitteeDetailPresentation(buildCommitteeBundle());

    expect(presentation.transactionRows).toEqual([]);
    expect(presentation.transactionEmptyMessage).toBe("No recent committee transactions found.");
  });

  it("builds committee metadata from canonical name and transaction count", () => {
    expect(buildCommitteeDetailMetadata("Committee One", 3)).toEqual({
      title: "Committee One | Committee | Civibus",
      description: "Committee profile with 3 recent transactions."
    });
  });

  it("builds candidate metadata from canonical candidate name", () => {
    expect(buildCandidateDetailMetadata("Candidate One")).toEqual({
      title: "Candidate One | Candidate | Civibus",
      description: "Candidate profile from campaign-finance records."
    });
  });

  it("falls back to committee summary name when committee detail name is empty", () => {
    const presentation = buildCommitteeDetailPresentation(
      buildCommitteeBundle({
        detail: {
          ...DEFAULT_COMMITTEE_DETAIL,
          name: ""
        },
        summary: {
          ...DEFAULT_SUMMARY,
          committee_name: "Committee Summary Name"
        }
      })
    );

    expect(presentation.canonicalName).toBe("Committee Summary Name");
  });

  it("falls back to candidate summary name when candidate detail name is empty", () => {
    const presentation = buildCandidateDetailPresentation(
      buildCandidateBundle({
        detail: {
          ...DEFAULT_CANDIDATE_DETAIL,
          name: ""
        },
        summary: {
          ...DEFAULT_CANDIDATE_SUMMARY,
          candidate_name: "Candidate Empty"
        }
      })
    );

    expect(presentation.canonicalName).toBe("Candidate Empty");
    expect(buildCandidateDetailMetadata(presentation.canonicalName).title).toBe(
      "Candidate Empty | Candidate | Civibus"
    );
  });

  it("builds committee route metadata directly from the loaded bundle", () => {
    expect(
      buildCommitteeDetailMetadataFromBundle(
        buildCommitteeBundle({
          transactions: [DEFAULT_TRANSACTION]
        })
      )
    ).toEqual({
      title: "Committee One | Committee | Civibus",
      description: "Committee profile with 1 recent transaction."
    });
  });

  it("falls back to committee summary name when committee bundle metadata sees an empty detail name", () => {
    expect(
      buildCommitteeDetailMetadataFromBundle(
        buildCommitteeBundle({
          detail: {
            ...DEFAULT_COMMITTEE_DETAIL,
            name: ""
          },
          summary: {
            ...DEFAULT_SUMMARY,
            committee_name: "Committee Summary Name"
          }
        })
      )
    ).toEqual({
      title: "Committee Summary Name | Committee | Civibus",
      description: "Committee profile with 0 recent transactions."
    });
  });

  it("builds committee route metadata with pluralized zero-transaction wording", () => {
    expect(buildCommitteeDetailMetadataFromBundle(buildCommitteeBundle())).toEqual({
      title: "Committee One | Committee | Civibus",
      description: "Committee profile with 0 recent transactions."
    });
  });

  it("builds candidate presentation with aggregate fundraising totals from summary", () => {
    const bundle = buildCandidateBundle({
      summary: {
        candidate_id: CANDIDATE_ID,
        candidate_name: "Candidate One",
        total_raised: "5000.00",
        total_spent: "2000.00",
        net: "3000.00",
        transaction_count: 42,
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
      }
    });

    const presentation = buildCandidateDetailPresentation(bundle);

    expect(presentation.fundraisingSummary).toEqual({
      totalRaised: "$5,000.00",
      totalSpent: "$2,000.00",
      net: "$3,000.00",
      transactionCount: 42
    });
    expect(presentation.committeeBreakdown).toHaveLength(2);
    expect(presentation.committeeBreakdown[0]).toEqual({
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
    expect(presentation.committeeBreakdown[1]).toEqual({
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

  it("builds candidate presentation with empty committees as empty breakdown", () => {
    const presentation = buildCandidateDetailPresentation(buildCandidateBundle());

    expect(presentation.fundraisingSummary).toEqual({
      totalRaised: "$0.00",
      totalSpent: "$0.00",
      net: "$0.00",
      transactionCount: 0
    });
    expect(presentation.committeeBreakdown).toEqual([]);
  });

  it("builds candidate presentation with null data_through and jurisdiction", () => {
    const bundle = buildCandidateBundle({
      summary: {
        candidate_id: CANDIDATE_ID,
        candidate_name: "Candidate One",
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
      }
    });

    const presentation = buildCandidateDetailPresentation(bundle);

    expect(presentation.committeeBreakdown[0].jurisdiction).toBe("—");
    expect(presentation.committeeBreakdown[0].dataThrough).toBe("—");
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

  it("adds an explanatory outside-spending block to candidate presentation", () => {
    const presentation = buildCandidateDetailPresentation(
      buildCandidateBundle({
        ieSummary: {
          candidate_id: CANDIDATE_ID,
          support_total: "100.00",
          oppose_total: "50.00",
          support_count: 1,
          oppose_count: 1,
          top_spenders: []
        }
      })
    );

    const outsideSpending = presentation.outsideSpending as unknown as Record<string, unknown>;
    expect(outsideSpending.explanatoryBlock).toBe(
      "Outside spending is independent and not controlled by the candidate committee."
    );
  });

  it("includes transaction-level outside-spending rows when IE data exists", () => {
    const presentation = buildCandidateDetailPresentation(
      buildCandidateBundle({
        ieSummary: {
          candidate_id: CANDIDATE_ID,
          support_total: "100.00",
          oppose_total: "50.00",
          support_count: 1,
          oppose_count: 1,
          top_spenders: []
        },
        ieTransactions: [
          {
            id: "77777777-7777-4777-8777-777777777777",
            filing_id: null,
            committee_id: COMMITTEE_ID,
            committee_name: "Independent Expenditure Committee",
            amount: 100,
            transaction_date: "2026-03-19",
            purpose: "Independent expenditure",
            dissemination_date: "2026-03-20",
            aggregate_amount: 100,
            support_oppose: "S"
          }
        ]
      } as any)
    );

    const outsideSpending = presentation.outsideSpending as unknown as {
      transactionRows?: Array<Record<string, unknown>>;
    };
    expect(outsideSpending.transactionRows).toEqual([
      {
        date: "2026-03-19",
        disseminationDate: "2026-03-20",
        spender: "Independent Expenditure Committee",
        spenderHref: `/committee/${COMMITTEE_ID}`,
        stance: "Support",
        amount: "$100.00"
      }
    ]);
  });

  it("uses an outside-spending unavailable message when IE summary is missing", () => {
    const presentation = buildCandidateDetailPresentation(
      buildCandidateBundle({
        ieSummary: null
      })
    );

    expect(presentation.outsideSpending.emptyMessage).toBe(
      "Outside-spending data is not yet available for this candidate. Coverage may be incomplete."
    );
  });

  it("uses a no-activity outside-spending message when summary totals are zero", () => {
    const presentation = buildCandidateDetailPresentation(
      buildCandidateBundle({
        ieSummary: {
          candidate_id: CANDIDATE_ID,
          support_total: "0.00",
          oppose_total: "0.00",
          support_count: 0,
          oppose_count: 0,
          top_spenders: []
        },
        ieTransactions: []
      })
    );

    expect(presentation.outsideSpending.emptyMessage).toBe(
      "No outside spending is reported in available filings. Coverage may be incomplete."
    );
  });

  it("emits a section order for committee detail with summary before trust before metrics before deep records", () => {
    const presentation = buildCommitteeDetailPresentation(buildCommitteeBundle());

    expect(presentation.sectionOrder).toEqual([
      "summary",
      "trust",
      "metrics",
      "records"
    ]);
  });

  it("emits a section order for candidate detail with summary before trust before metrics before outside-spending before records", () => {
    const presentation = buildCandidateDetailPresentation(buildCandidateBundle());

    expect(presentation.sectionOrder).toEqual([
      "summary",
      "trust",
      "metrics",
      "outside-spending",
      "records"
    ]);
  });

  it("builds committee key metrics from fundraising totals and transaction count", () => {
    const presentation = buildCommitteeDetailPresentation(
      buildCommitteeBundle({
        summary: {
          ...DEFAULT_SUMMARY,
          total_raised: "5000.00",
          total_spent: "2000.00",
          transaction_count: 42
        }
      })
    );

    expect(presentation.keyMetrics).toEqual([
      { label: "Total raised", value: "$5,000.00" },
      { label: "Total spent", value: "$2,000.00" },
      { label: "Transactions", value: "42" }
    ]);
  });

  it("builds candidate key metrics from aggregate fundraising totals", () => {
    const presentation = buildCandidateDetailPresentation(
      buildCandidateBundle({
        summary: {
          ...DEFAULT_CANDIDATE_SUMMARY,
          total_raised: "10000.00",
          total_spent: "3000.00",
          transaction_count: 100
        }
      })
    );

    expect(presentation.keyMetrics).toEqual([
      { label: "Total raised", value: "$10,000.00" },
      { label: "Total spent", value: "$3,000.00" },
      { label: "Transactions", value: "100" }
    ]);
  });

  it("provides a next-step empty message when committee has no filings and no transactions", () => {
    const presentation = buildCommitteeDetailPresentation(
      buildCommitteeBundle({
        transactions: [],
        filingBreakdown: {
          ...DEFAULT_FILING_BREAKDOWN,
          filings: []
        }
      })
    );

    expect(presentation.filingBreakdown.emptyMessage).toBe(
      "No filing-period fundraising data available."
    );
    expect(presentation.transactionEmptyMessage).toBe(
      "No recent committee transactions found."
    );
  });
});
