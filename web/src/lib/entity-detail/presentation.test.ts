import { buildTrustSection } from "$lib/detail-trust/presentation";
import { describe, expect, it } from "vitest";
import {
  buildCanonicalDetailFacts,
  buildEntityDetailMetadata,
  buildEntityDetailMetadataFromDetail,
  buildEntityDetailPresentation,
  buildEntityDetailShellPresentation,
  buildIdentifierKeyMetrics,
  buildIdentifierRows,
  buildPersonContributionInsightsPresentation,
  buildPersonMoneyAtGlancePresentation,
  buildPersonMoneyAtGlanceSummary,
  getIdentifierEmptyMessage
} from "./presentation";

const PERSON_ID = "11111111-1111-4111-8111-111111111111";
const ORG_ID = "22222222-2222-4222-8222-222222222222";
const SELECTED_CYCLE_METADATA = {
  selected_cycle: 2026,
  available_cycles: [2022, 2024, 2026]
};

const SOURCES = [
  {
    domain: "campaign_finance",
    jurisdiction: "federal/fec",
    data_source_name: "FEC",
    data_source_url: "https://www.fec.gov",
    source_record_key: "person-1",
    record_url: "https://example.org/person-1",
    pull_date: "2026-03-19T00:00:00Z"
  }
];

const PERSON_DETAIL = {
  id: PERSON_ID,
  canonical_name: "Jane Doe",
  name_variants: ["J. Doe"],
  first_name: "Jane",
  middle_name: null,
  last_name: "Doe",
  suffix: null,
  occupation: "Attorney",
  education: "State University",
  date_of_birth: null,
  year_of_birth: 1980,
  bio_text: null,
  bio_source_url: null,
  bio_license: null,
  bio_pulled_at: null,
  identifiers: { fec_candidate_id: "H0NC01001" },
  primary_address_id: null,
  er_cluster_id: null,
  er_confidence: 0.93,
  sources: SOURCES
};

const ORG_DETAIL = {
  id: ORG_ID,
  canonical_name: "Civibus Action Org",
  name_variants: [],
  org_type: "pac",
  identifiers: { fec_committee_id: "C12345678", state_committee_id: "NC-001" },
  registered_state: "NC",
  formation_date: "2014-05-01",
  dissolution_date: null,
  primary_address_id: null,
  er_cluster_id: null,
  er_confidence: 0.88,
  sources: []
};

const CONTRIBUTION_INSIGHTS = {
  person_id: PERSON_ID,
  has_data: true,
  metadata: {
    ...SELECTED_CYCLE_METADATA,
    coverage_start_date: "2022-01-01",
    coverage_end_date: "2026-06-30",
    cycles_included: [2022, 2024, 2026],
    committee_count: 2,
    approximate_geography: true,
    excluded_geography: null,
    caveats: []
  },
  monthly_totals: [
    { month: "2026-01", total_amount: "100.00", transaction_count: 2 },
    { month: "2026-02", total_amount: "250.50", transaction_count: 3 }
  ],
  itemized_size_buckets: [
    {
      label: "$200 and under",
      min_amount: "0.01",
      max_amount: "200.00",
      total_amount: "175.00",
      transaction_count: 3
    },
    {
      label: "$200.01-$499.99",
      min_amount: "200.01",
      max_amount: "499.99",
      total_amount: "175.50",
      transaction_count: 2
    }
  ],
  dollars_by_size: [
    { label: "$200 and under", total_amount: "175.00", source: "transactions" as const },
    { label: "$200.01-$499.99", total_amount: "175.50", source: "transactions" as const }
  ],
  cycle_totals: [
    {
      cycle: 2024,
      itemized_individual_contribution_amount: "350.50",
      itemized_transaction_count: 5,
      unitemized_individual_contribution_amount: "125.00",
      total_individual_contribution_amount: "475.50",
      source: "mixed_sources" as const
    },
    {
      cycle: 2026,
      itemized_individual_contribution_amount: "250.50",
      itemized_transaction_count: 3,
      unitemized_individual_contribution_amount: "0.00",
      total_individual_contribution_amount: "250.50",
      source: "itemized_transactions" as const
    }
  ],
  career_totals: {
    itemized_individual_contribution_amount: "601.00",
    itemized_transaction_count: 8,
    unitemized_individual_contribution_amount: "125.00",
    total_individual_contribution_amount: "726.00",
    source: "mixed_sources" as const
  },
  geography: {
    by_state: [
      { label: "NC", total_amount: "300.00", transaction_count: 4 },
      { label: "VA", total_amount: "50.50", transaction_count: 1 },
      { label: "Unknown", total_amount: "25.00", transaction_count: 1 }
    ],
    by_district: [
      { label: "NC-01", total_amount: "275.00", transaction_count: 3 },
      { label: "Out of district", total_amount: "75.50", transaction_count: 2 }
    ],
    district_share: {
      in_district_amount: "275.00",
      out_of_district_amount: "75.50",
      unknown_district_amount: "25.00",
      share: "0.7846",
      available: true
    },
    geography_mode: "district" as const,
    classified_amount: "350.50",
    classified_transaction_count: 5,
    unknown_amount: "25.00",
    unknown_transaction_count: 1
  },
  small_dollar_share: {
    small_dollar_amount: "300.00",
    total_contribution_amount: "500.00",
    share: "0.6000",
    available: true
  }
};

const PERSON_TOP_DONORS = [
  { name: "High Dollar Donor", total_amount: "500.00", transaction_count: 4 },
  { name: "Second Dollar Donor", total_amount: "250.00", transaction_count: 2 }
];

const PERSON_TOP_EMPLOYERS = [
  { employer: "ACME CORP", total_amount: "600.00", transaction_count: 3 },
  { employer: "State University", total_amount: "150.00", transaction_count: 1 }
];

describe("entity detail presentation", () => {
  it("builds canonical person facts without internal ER confidence rows", () => {
    expect(buildCanonicalDetailFacts("person", PERSON_DETAIL)).toEqual([
      { label: "Canonical name", value: "Jane Doe" },
      { label: "First name", value: "Jane" },
      { label: "Last name", value: "Doe" },
      { label: "Occupation", value: "Attorney" },
      { label: "Education", value: "State University" },
      { label: "Year of birth", value: "1980" }
    ]);
  });

  it("builds canonical organization facts without internal ER confidence rows", () => {
    expect(buildCanonicalDetailFacts("org", ORG_DETAIL)).toEqual([
      { label: "Canonical name", value: "Civibus Action Org" },
      { label: "Organization type", value: "pac" },
      { label: "Registered state", value: "NC" },
      { label: "Formation date", value: "2014-05-01" }
    ]);
  });

  it("builds stable identifier rows and identifier-only metrics", () => {
    const identifierRows = buildIdentifierRows({
      zeta_id: "Z-1",
      alpha_id: "A-1"
    });

    expect(identifierRows).toEqual([
      { label: "alpha_id", value: "A-1" },
      { label: "zeta_id", value: "Z-1" }
    ]);
    expect(buildIdentifierKeyMetrics(identifierRows)).toEqual([
      { label: "Identifiers", value: "2" }
    ]);
  });

  it("builds public person shell section order with finance and no graph/civic internals", () => {
    const viewModel = buildEntityDetailShellPresentation({
      entityType: "person",
      detail: PERSON_DETAIL
    });

    expect(viewModel.sectionOrder).toEqual([
      "summary",
      "person-campaign-finance",
      "trust",
      "metrics",
      "records"
    ]);
    expect(viewModel.keyMetricRows).toEqual([{ label: "Identifiers", value: "1" }]);
    expect(viewModel.trustSection).toEqual(buildTrustSection(SOURCES));
    expect(viewModel).not.toHaveProperty("matchRows");
    expect(viewModel).not.toHaveProperty("neighborRows");
    expect(viewModel).not.toHaveProperty("technicalDisclosure");
    expect(viewModel).not.toHaveProperty("civicRecordSection");
  });

  it("builds public organization shell section order without finance or internals", () => {
    const viewModel = buildEntityDetailPresentation({
      entityType: "org",
      detail: ORG_DETAIL
    });

    expect(viewModel.sectionOrder).toEqual(["summary", "trust", "metrics", "records"]);
    expect(viewModel.keyMetricRows).toEqual([{ label: "Identifiers", value: "2" }]);
  });

  it("returns public empty-state messaging for missing identifiers", () => {
    const viewModel = buildEntityDetailShellPresentation({
      entityType: "person",
      detail: {
        ...PERSON_DETAIL,
        identifiers: {}
      }
    });

    expect(viewModel.identifierEmptyMessage).toBe(getIdentifierEmptyMessage());
  });

  it("builds selected-cycle money-at-a-glance rows from person finance summary values", () => {
    const firstSummary = {
      ...SELECTED_CYCLE_METADATA,
      coverage_start_date: "2025-01-01",
      coverage_end_date: "2026-12-31",
      candidate_id: "candidate-1",
      candidate_name: "Candidate One",
      total_raised: "125.00",
      total_spent: "75.00",
      net: "50.00",
      transaction_count: 2,
      itemized_transaction_count: 2,
      cash_on_hand: "25.00",
      net_self_funding: "5.00",
      debts_owed_by_committee: "10.00",
      summary_source: "fec_weball" as const,
      receipt_source_composition: [
        {
          label: "Gross individual contributions",
          total_amount: "90.00",
          source: "fec_committee_summary" as const
        },
        {
          label: "PAC/other committee contributions",
          total_amount: "35.00",
          source: "fec_committee_summary" as const
        }
      ],
      selected_cycle_coverage_complete: true,
      can_render_share: true,
      receipt_source_caveats: [],
      committees: []
    };

    expect(
      buildPersonMoneyAtGlancePresentation(firstSummary)
    ).toEqual({
      heading: "Money at a glance",
      cycleLabel: "2026 cycle",
      coverageLabel: "2025-01-01 to 2026-12-31",
      sourceLabel: "Official FEC candidate summary",
      cycleOptions: [
        { cycle: 2022, label: "2022", href: "?cycle=2022", selected: false },
        { cycle: 2024, label: "2024", href: "?cycle=2024", selected: false },
        { cycle: 2026, label: "2026", href: "?cycle=2026", selected: true }
      ],
      metricRows: [
        { label: "Total receipts", value: "$125.00" },
        { label: "Total disbursements", value: "$75.00" },
        { label: "Cash on hand", value: "$25.00" },
        { label: "Net self-funded", value: "$5.00" },
        { label: "Debts owed by the committee", value: "$10.00" }
      ],
      receiptComposition: {
        testId: "person-receipt-composition",
        cycle: 2026,
        coverageThrough: "2026-12-31",
        sources: [
          {
            label: "FEC candidate and committee summaries",
            href: "https://www.fec.gov/data/candidates/"
          }
        ],
        totalReceipts: 125,
        canPlot: true,
        caveat: "",
        rows: [
          {
            id: "gross_individual_contributions",
            label: "Gross individual contributions",
            amount: 90,
            denominator: 125,
            canPlot: true
          },
          {
            id: "pac_other_committee_contributions",
            label: "PAC/other committee contributions",
            amount: 35,
            denominator: 125,
            canPlot: true
          }
        ]
      }
    });

    expect(
      buildPersonMoneyAtGlancePresentation(
        buildPersonMoneyAtGlanceSummary([
          firstSummary,
          {
            ...firstSummary,
            candidate_id: "candidate-2",
            candidate_name: "Candidate Two",
            total_raised: "875.00",
            total_spent: "225.00",
            net: "650.00",
            transaction_count: 5,
            itemized_transaction_count: 4,
            cash_on_hand: "100.00",
            net_self_funding: "45.00",
            debts_owed_by_committee: "40.00",
            summary_source: "derived" as const
          }
        ])
      )
    ).toMatchObject({
      sourceLabel: "Mixed official FEC and derived summary data",
      metricRows: [
        { label: "Total receipts", value: "$1,000.00" },
        { label: "Total disbursements", value: "$300.00" },
        { label: "Cash on hand", value: "$125.00" },
        { label: "Net self-funded", value: "$50.00" },
        { label: "Debts owed by the committee", value: "$50.00" }
      ]
    });

    expect(
      buildPersonMoneyAtGlancePresentation(
        buildPersonMoneyAtGlanceSummary([
          firstSummary,
          {
            ...firstSummary,
            candidate_id: "candidate-3",
            candidate_name: "Candidate Three",
            total_raised: "875.00",
            total_spent: "225.00",
            net: "650.00",
            transaction_count: 5,
            itemized_transaction_count: 4,
            cash_on_hand: null,
            net_self_funding: null,
            debts_owed_by_committee: undefined
          }
        ])
      )
    ).toMatchObject({
      metricRows: [
        { label: "Total receipts", value: "$1,000.00" },
        { label: "Total disbursements", value: "$300.00" },
        { label: "Cash on hand", value: "Not available" },
        { label: "Net self-funded", value: "Not available" },
        { label: "Debts owed by the committee", value: "Not available" }
      ]
    });

    expect(() =>
      buildPersonMoneyAtGlanceSummary([
        firstSummary,
        {
          ...firstSummary,
          candidate_id: "candidate-4",
          candidate_name: "Candidate Four",
          selected_cycle: 2024
        }
      ])
    ).toThrow("Person money at a glance summaries must share one selected cycle.");

  });

  it("maps candidate receipt-source summaries into shared receipt composition props", () => {
    const firstSummary = {
      ...SELECTED_CYCLE_METADATA,
      coverage_start_date: "2025-01-01",
      coverage_end_date: "2026-12-31",
      candidate_id: "candidate-1",
      candidate_name: "Candidate One",
      total_raised: "125.00",
      total_spent: "75.00",
      net: "50.00",
      transaction_count: 2,
      itemized_transaction_count: 2,
      cash_on_hand: "25.00",
      net_self_funding: "5.00",
      debts_owed_by_committee: "10.00",
      summary_source: "fec_weball" as const,
      receipt_source_composition: [
        {
          label: "Gross individual contributions",
          total_amount: "90.00",
          source: "fec_committee_summary" as const
        },
        {
          label: "PAC/other committee contributions",
          total_amount: "35.00",
          source: "fec_committee_summary" as const
        }
      ],
      selected_cycle_coverage_complete: true,
      can_render_share: true,
      receipt_source_caveats: [],
      committees: []
    };
    const secondSummary = {
      ...firstSummary,
      candidate_id: "candidate-2",
      candidate_name: "Candidate Two",
      total_raised: "275.00",
      receipt_source_composition: [
        {
          label: "Gross individual contributions",
          total_amount: "180.00",
          source: "fec_committee_summary" as const
        },
        {
          label: "PAC/other committee contributions",
          total_amount: "95.00",
          source: "fec_committee_summary" as const
        }
      ],
      receipt_source_caveats: ["components_reconciled_from_committee_summaries"]
    };

    expect(
      buildPersonMoneyAtGlancePresentation(
        buildPersonMoneyAtGlanceSummary([firstSummary, secondSummary])
      ).receiptComposition
    ).toEqual({
      testId: "person-receipt-composition",
      cycle: 2026,
      coverageThrough: "2026-12-31",
      sources: [
        {
          label: "FEC candidate and committee summaries",
          href: "https://www.fec.gov/data/candidates/"
        }
      ],
      totalReceipts: 400,
      canPlot: true,
      caveat: "components_reconciled_from_committee_summaries",
      rows: [
        {
          id: "gross_individual_contributions",
          label: "Gross individual contributions",
          amount: 270,
          denominator: 400,
          canPlot: true
        },
        {
          id: "pac_other_committee_contributions",
          label: "PAC/other committee contributions",
          amount: 130,
          denominator: 400,
          canPlot: true
        }
      ]
    });
  });

  it("keeps negative receipt-source reconciliation components table-only", () => {
    const summary = buildPersonMoneyAtGlanceSummary([
      {
        ...SELECTED_CYCLE_METADATA,
        coverage_start_date: "2025-01-01",
        coverage_end_date: "2026-12-31",
        candidate_id: "candidate-1",
        candidate_name: "Candidate One",
        total_raised: "100.00",
        total_spent: "75.00",
        net: "25.00",
        transaction_count: 2,
        itemized_transaction_count: 2,
        cash_on_hand: "25.00",
        net_self_funding: "5.00",
        debts_owed_by_committee: "0.00",
        summary_source: "fec_weball" as const,
        receipt_source_composition: [
          {
            label: "Gross individual contributions",
            total_amount: "125.00",
            source: "fec_committee_summary" as const
          },
          {
            label: "Contribution refunds and offsets",
            total_amount: "-25.00",
            source: "fec_committee_summary" as const
          }
        ],
        selected_cycle_coverage_complete: true,
        can_render_share: false,
        receipt_source_caveats: ["negative_component_table_only"],
        committees: []
      }
    ]);

    expect(buildPersonMoneyAtGlancePresentation(summary).receiptComposition).toMatchObject({
      totalReceipts: 100,
      canPlot: false,
      caveat: "negative_component_table_only",
      rows: [
        expect.objectContaining({
          label: "Gross individual contributions",
          amount: 125,
          denominator: 100,
          canPlot: false
        }),
        expect.objectContaining({
          label: "Contribution refunds and offsets",
          amount: -25,
          denominator: 100,
          canPlot: false
        })
      ]
    });
  });

  it("maps contribution insights into headline copy and chart series", () => {
    const viewModel = buildPersonContributionInsightsPresentation(
      CONTRIBUTION_INSIGHTS,
      PERSON_TOP_DONORS,
      PERSON_TOP_EMPLOYERS
    );

    expect(viewModel.emptyMessage).toBeNull();
    expect(viewModel.topDonors).toEqual([
      {
        name: "High Dollar Donor",
        totalAmount: "$500.00",
        transactionCountLabel: "4 transactions",
        barPercent: 100
      },
      {
        name: "Second Dollar Donor",
        totalAmount: "$250.00",
        transactionCountLabel: "2 transactions",
        barPercent: 50
      }
    ]);
    expect(viewModel.topDonorsEmptyMessage).toBeNull();
    expect(viewModel.topEmployers).toEqual([
      {
        name: "ACME CORP",
        totalAmount: "$600.00",
        transactionCountLabel: "3 transactions",
        barPercent: 100
      },
      {
        name: "State University",
        totalAmount: "$150.00",
        transactionCountLabel: "1 transaction",
        barPercent: 25
      }
    ]);
    expect(viewModel.topEmployersEmptyMessage).toBeNull();
    expect(viewModel.topEmployerDisclaimer).toBe(
      "Top employers aggregate raw employer names from itemized individual contributions only."
    );
    expect(viewModel.topEmployerMethodologyReference).toBe(
      "They are not industry- or sector-coded; see Methodology for source-linking and evidence limitations."
    );
    expect(viewModel.defaultTotalSummaryKey).toBe("cycle");
    expect(viewModel.totalsEmptyMessage).toBeNull();
    expect(viewModel.totalSummaryViews).toEqual([
      {
        key: "cycle",
        label: "2026 cycle",
        amountLabel: "$250.50",
        itemizedAmountLabel: "$250.50",
        unitemizedAmountLabel: "$0.00",
        transactionCountLabel: "3 transactions",
        caveatMessage:
          "Only itemized individual contributions are included; unitemized totals are unavailable for this view."
      },
      {
        key: "career",
        label: "Recent history total (2022-2026)",
        amountLabel: "$726.00",
        itemizedAmountLabel: "$601.00",
        unitemizedAmountLabel: "$125.00",
        transactionCountLabel: "8 transactions",
        caveatMessage:
          "Totals combine itemized transactions with available committee-summary data; unitemized coverage may be incomplete."
      }
    ]);
    expect(viewModel.smallDollarHeadline).toBe("60%");
    expect(viewModel.smallDollarSummary).toBe("$300.00 of $500.00 from small-dollar sources");
    expect(viewModel.districtShareHeadline).toBe("78% in district");
    expect(viewModel.districtShareSummary).toBe(
      "$275.00 in district and $75.50 out of district; $25.00 unknown district excluded from the share."
    );
    expect(viewModel.coverageLabel).toBe("2022-01-01 to 2026-06-30");
    expect(viewModel.geographyNote).toContain("Census 119th-Congress / 2020-ZCTA approximation");
    expect(viewModel.unitemizedExclusionNote).toBe(
      "Unitemized contributions are excluded from count and geography charts."
    );
    expect(viewModel.monthlyContributions).toEqual({
      testId: "person-monthly-contributions",
      cycle: 2026,
      coverageThrough: "2026-06-30",
      sources: [
        {
          label: "FEC Schedule A itemized individual contributions",
          href: "https://www.fec.gov/data/receipts/individual-contributions/"
        }
      ],
      coveredMonths: [
        "2022-01",
        "2022-02",
        "2022-03",
        "2022-04",
        "2022-05",
        "2022-06",
        "2022-07",
        "2022-08",
        "2022-09",
        "2022-10",
        "2022-11",
        "2022-12",
        "2023-01",
        "2023-02",
        "2023-03",
        "2023-04",
        "2023-05",
        "2023-06",
        "2023-07",
        "2023-08",
        "2023-09",
        "2023-10",
        "2023-11",
        "2023-12",
        "2024-01",
        "2024-02",
        "2024-03",
        "2024-04",
        "2024-05",
        "2024-06",
        "2024-07",
        "2024-08",
        "2024-09",
        "2024-10",
        "2024-11",
        "2024-12",
        "2025-01",
        "2025-02",
        "2025-03",
        "2025-04",
        "2025-05",
        "2025-06",
        "2025-07",
        "2025-08",
        "2025-09",
        "2025-10",
        "2025-11",
        "2025-12",
        "2026-01",
        "2026-02",
        "2026-03",
        "2026-04",
        "2026-05",
        "2026-06"
      ],
      rows: [
        { month: "2026-01", amount: 100, transactionCount: 2, covered: true },
        { month: "2026-02", amount: 250.5, transactionCount: 3, covered: true }
      ]
    });
    expect(viewModel.sizeBuckets).toEqual({
      title: "Itemized contribution-size buckets",
      testId: "person-size-buckets",
      cycle: 2026,
      coverageThrough: "2026-06-30",
      sources: [
        {
          label: "FEC Schedule A itemized individual contributions",
          href: "https://www.fec.gov/data/receipts/individual-contributions/"
        }
      ],
      rowsByUnit: {
        dollars: [
          {
            id: "200_and_under",
            label: "$200 and under",
            amount: 175,
            transactionCount: 3,
            unit: "dollars",
            canPlot: true
          },
          {
            id: "200_01_499_99",
            label: "$200.01-$499.99",
            amount: 175.5,
            transactionCount: 2,
            unit: "dollars",
            canPlot: true
          },
          {
            id: "500_999_99",
            label: "$500-$999.99",
            amount: 0,
            transactionCount: 0,
            unit: "dollars",
            canPlot: true
          },
          {
            id: "1_000_1_999_99",
            label: "$1,000-$1,999.99",
            amount: 0,
            transactionCount: 0,
            unit: "dollars",
            canPlot: true
          },
          {
            id: "2_000_and_over",
            label: "$2,000 and over",
            amount: 0,
            transactionCount: 0,
            unit: "dollars",
            canPlot: true
          }
        ],
        reported_transactions: expect.arrayContaining([
          expect.objectContaining({
            id: "200_and_under",
            label: "$200 and under",
            unit: "reported_transactions"
          })
        ])
      }
    });
    expect(viewModel.geographyShare).toEqual({
      testId: "person-geography-share",
      cycle: 2026,
      coverageThrough: "2026-06-30",
      sources: [
        {
          label: "FEC Schedule A itemized individual contributions",
          href: "https://www.fec.gov/data/receipts/individual-contributions/"
        }
      ],
      mode: "district",
      approximationNote: "District geography uses a Census 119th-Congress / 2020-ZCTA approximation.",
      rows: [
        {
          id: "nc_01",
          label: "NC-01",
          amount: 275,
          transactionCount: 3,
          denominator: 375.5,
          approximate: true
        },
        {
          id: "out_of_district",
          label: "Out of district",
          amount: 75.5,
          transactionCount: 2,
          denominator: 375.5,
          approximate: true
        },
        {
          id: "unknown",
          label: "Unknown",
          amount: 25,
          transactionCount: 1,
          denominator: 375.5,
          approximate: true
        }
      ]
    });
    expect(viewModel.rankingLabels).toEqual({
      topDonors: "Top reported contributor names",
      topEmployers: "Top reported employer names"
    });
    expect(viewModel.topDonors[0]).toMatchObject({ barPercent: 100 });
    expect(viewModel.topDonors[1]).toMatchObject({ barPercent: 50 });
  });

  it("builds no-itemized-data empty state when cycle and career totals have no source", () => {
    const viewModel = buildPersonContributionInsightsPresentation(
      {
        ...CONTRIBUTION_INSIGHTS,
        cycle_totals: [],
        career_totals: {
          itemized_individual_contribution_amount: "0.00",
          itemized_transaction_count: 0,
          unitemized_individual_contribution_amount: "0.00",
          total_individual_contribution_amount: "0.00",
          source: "none"
        }
      },
      []
    );

    expect(viewModel.totalSummaryViews).toEqual([]);
    expect(viewModel.defaultTotalSummaryKey).toBeNull();
    expect(viewModel.totalsEmptyMessage).toBe(
      "No itemized individual-contribution totals are available yet."
    );
    expect(viewModel.topDonors).toEqual([]);
    expect(viewModel.topDonorsEmptyMessage).toBe("No donor rankings available.");
    expect(viewModel.topEmployers).toEqual([]);
    expect(viewModel.topEmployersEmptyMessage).toBe("No employer rankings available.");
  });

  it("keeps state geography as the preferred geography when district rows are absent", () => {
    const viewModel = buildPersonContributionInsightsPresentation({
      ...CONTRIBUTION_INSIGHTS,
      geography: { ...CONTRIBUTION_INSIGHTS.geography, by_district: [] },
      metadata: { ...CONTRIBUTION_INSIGHTS.metadata, approximate_geography: false }
    });

    expect(viewModel.geographyShare.mode).toBe("district");
    expect(viewModel.geographyShare.rows).toContainEqual(
      expect.objectContaining({ label: "Unknown" })
    );
    expect(viewModel.geographyNote).toBe("Contributor geography by state.");
  });

  it("shows unavailable copy when small-dollar share cannot be computed", () => {
    const viewModel = buildPersonContributionInsightsPresentation({
      ...CONTRIBUTION_INSIGHTS,
      small_dollar_share: {
        small_dollar_amount: null,
        total_contribution_amount: null,
        share: null,
        available: false
      }
    });

    expect(viewModel.smallDollarHeadline).toBe("Small-dollar share unavailable");
    expect(viewModel.smallDollarSummary).toBe("Committee summary totals are not available yet.");
  });

  it("shows dedicated unavailable copy when district share cannot be computed", () => {
    const viewModel = buildPersonContributionInsightsPresentation({
      ...CONTRIBUTION_INSIGHTS,
      geography: {
        ...CONTRIBUTION_INSIGHTS.geography,
        district_share: {
          in_district_amount: null,
          out_of_district_amount: null,
          unknown_district_amount: null,
          share: null,
          available: false
        }
      }
    });

    expect(viewModel.districtShareHeadline).toBe("District share unavailable");
    expect(viewModel.districtShareSummary).toBe(
      "District-share geography is unavailable until in-district and out-of-district itemized totals are available."
    );
    expect(viewModel.districtShareSummary).not.toBe("Committee summary totals are not available yet.");
  });

  it("maps contribution-insights caveats into specific empty messages", () => {
    expect(
      buildPersonContributionInsightsPresentation({
        ...CONTRIBUTION_INSIGHTS,
        has_data: false,
        metadata: { ...CONTRIBUTION_INSIGHTS.metadata, caveats: ["missing_committee_summary"] }
      }).emptyMessage
    ).toBe("Committee summary totals are required before dollars by size can be shown.");
    expect(
      buildPersonContributionInsightsPresentation({
        ...CONTRIBUTION_INSIGHTS,
        has_data: false,
        metadata: { ...CONTRIBUTION_INSIGHTS.metadata, caveats: ["missing_zcta_district"] }
      }).emptyMessage
    ).toBe("District geography is unavailable until ZCTA district reference data is loaded.");
  });

  it("maps real incomplete-data caveats without treating loaded insights as empty", () => {
    const viewModel = buildPersonContributionInsightsPresentation({
      ...CONTRIBUTION_INSIGHTS,
      has_data: true,
      metadata: {
        ...CONTRIBUTION_INSIGHTS.metadata,
        caveats: ["missing_committee_summary"]
      }
    });

    expect(viewModel.emptyMessage).toBeNull();
    expect(viewModel.caveatMessages).toEqual([
      "Committee summary totals are unavailable, so summary-backed unitemized dollars are not included."
    ]);
    expect(viewModel.sizeBuckets.rowsByUnit.dollars).toContainEqual(
      expect.objectContaining({ label: "$200 and under", amount: 175 })
    );
  });

  it("does not render loaded missing ZCTA caveats as top-panel unavailable copy when district rows exist", () => {
    const viewModel = buildPersonContributionInsightsPresentation({
      ...CONTRIBUTION_INSIGHTS,
      has_data: true,
      metadata: {
        ...CONTRIBUTION_INSIGHTS.metadata,
        approximate_geography: true,
        caveats: ["missing_zcta_district"]
      },
      geography: {
        ...CONTRIBUTION_INSIGHTS.geography,
        by_district: [
          { label: "In district", total_amount: "350.00", transaction_count: 3 },
          { label: "Out of district", total_amount: "201.00", transaction_count: 1 },
          { label: "Unknown district", total_amount: "75.00", transaction_count: 1 }
        ]
      }
    });

    expect(viewModel.emptyMessage).toBeNull();
    expect(viewModel.caveatMessages).toEqual([]);
    expect(viewModel.geographyShare.rows).toEqual([
      expect.objectContaining({ label: "In district", amount: 350 }),
      expect.objectContaining({ label: "Out of district", amount: 201 }),
      expect.objectContaining({ label: "Unknown district", amount: 75 }),
      expect.objectContaining({ label: "Unknown", amount: 25 })
    ]);
    expect(viewModel.geographyNote).toContain("Census 119th-Congress / 2020-ZCTA approximation");
  });

  it("keeps loaded missing ZCTA copy in the geography note for state-only fallback", () => {
    const viewModel = buildPersonContributionInsightsPresentation({
      ...CONTRIBUTION_INSIGHTS,
      has_data: true,
      metadata: {
        ...CONTRIBUTION_INSIGHTS.metadata,
        approximate_geography: true,
        caveats: ["missing_zcta_district"]
      },
      geography: {
        geography_mode: "state_bars_only",
        classified_amount: "551.00",
        classified_transaction_count: 4,
        unknown_amount: "0.00",
        unknown_transaction_count: 0,
        by_state: [
          { label: "NC", total_amount: "350.00", transaction_count: 3 },
          { label: "VA", total_amount: "201.00", transaction_count: 1 }
        ],
        by_district: [],
        district_share: {
          in_district_amount: null,
          out_of_district_amount: null,
          unknown_district_amount: null,
          share: null,
          available: false
        }
      }
    });

    expect(viewModel.emptyMessage).toBeNull();
    expect(viewModel.caveatMessages).toEqual([]);
    expect(viewModel.geographyShare.mode).toBe("state_bars_only");
    expect(viewModel.geographyNote).toBe(
      "District geography is unavailable until ZCTA district reference data is loaded."
    );
  });

  it("maps statewide geography mode without district approximation copy", () => {
    const viewModel = buildPersonContributionInsightsPresentation({
      ...CONTRIBUTION_INSIGHTS,
      metadata: {
        ...CONTRIBUTION_INSIGHTS.metadata,
        approximate_geography: false,
        caveats: []
      },
      geography: {
        geography_mode: "statewide",
        classified_amount: "400.00",
        classified_transaction_count: 4,
        unknown_amount: "50.00",
        unknown_transaction_count: 1,
        by_state: [{ label: "NC", total_amount: "400.00", transaction_count: 4 }],
        by_district: [],
        district_share: {
          in_district_amount: null,
          out_of_district_amount: null,
          unknown_district_amount: null,
          share: null,
          available: false
        }
      }
    });

    expect(viewModel.geographyShare).toMatchObject({
      mode: "statewide",
      approximationNote: "",
      rows: [
        expect.objectContaining({ label: "NC", amount: 400, denominator: 400 }),
        expect.objectContaining({ label: "Unknown", amount: 50, denominator: 400 })
      ]
    });
    expect(viewModel.geographyNote).toBe("Contributor geography by state.");
  });

  it("maps excluded-geography backend codes without exposing enum values", () => {
    expect(
      buildPersonContributionInsightsPresentation({
        ...CONTRIBUTION_INSIGHTS,
        has_data: false,
        metadata: {
          ...CONTRIBUTION_INSIGHTS.metadata,
          excluded_geography: "no_linked_candidate",
          caveats: []
        },
        monthly_totals: [],
        itemized_size_buckets: [],
        dollars_by_size: [],
        geography: {
          geography_mode: "excluded",
          classified_amount: "0.00",
          classified_transaction_count: 0,
          unknown_amount: "0.00",
          unknown_transaction_count: 0,
          by_state: [],
          by_district: [],
          district_share: {
            in_district_amount: null,
            out_of_district_amount: null,
            unknown_district_amount: null,
            share: null,
            available: false
          }
        },
        small_dollar_share: {
          small_dollar_amount: null,
          total_contribution_amount: null,
          share: null,
          available: false
        }
      }).emptyMessage
    ).toBe("No linked candidate is available for fundraising detail.");
    expect(
      buildPersonContributionInsightsPresentation({
        ...CONTRIBUTION_INSIGHTS,
        metadata: {
          ...CONTRIBUTION_INSIGHTS.metadata,
          approximate_geography: false,
          excluded_geography: "statewide_office",
          caveats: []
        },
        geography: { ...CONTRIBUTION_INSIGHTS.geography, by_district: [] }
      }).geographyNote
    ).toBe("Statewide offices use state-level fundraising geography.");
    expect(
      buildPersonContributionInsightsPresentation({
        ...CONTRIBUTION_INSIGHTS,
        metadata: {
          ...CONTRIBUTION_INSIGHTS.metadata,
          approximate_geography: false,
          excluded_geography: "federal_executive",
          caveats: []
        },
        geography: { ...CONTRIBUTION_INSIGHTS.geography, by_district: [] }
      }).geographyNote
    ).toBe("Federal executive offices use national fundraising geography.");
  });

  it("builds metadata descriptions from public identifier counts only", () => {
    expect(
      buildEntityDetailMetadata({
        entityType: "person",
        canonicalName: "Jane Doe",
        identifierCount: 1
      })
    ).toEqual({
      title: "Jane Doe | Person | Civibus",
      description: "Person profile with 1 identifier and source-linked records."
    });
    expect(
      buildEntityDetailMetadataFromDetail({
        entityType: "org",
        detail: ORG_DETAIL
      })
    ).toEqual({
      title: "Civibus Action Org | Organization | Civibus",
      description: "Organization profile with 2 identifiers and source-linked records."
    });
  });
});
