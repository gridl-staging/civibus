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
  buildPersonOutsideSpendingChartSeries,
  buildPersonSummaryChartSeries,
  getIdentifierEmptyMessage
} from "./presentation";

const PERSON_ID = "11111111-1111-4111-8111-111111111111";
const ORG_ID = "22222222-2222-4222-8222-222222222222";

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
      label: "$1-$199",
      min_amount: "1.00",
      max_amount: "199.99",
      total_amount: "175.00",
      transaction_count: 3
    },
    {
      label: "$200+",
      min_amount: "200.00",
      max_amount: null,
      total_amount: "175.50",
      transaction_count: 2
    }
  ],
  dollars_by_size: [
    { label: "Unitemized (<$200)", total_amount: "125.00", source: "committee_summary" as const },
    { label: "$1-$199", total_amount: "175.00", source: "transactions" as const },
    { label: "$200+", total_amount: "175.50", source: "transactions" as const }
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
      { label: "VA", total_amount: "50.50", transaction_count: 1 }
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
    }
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
      "trust",
      "metrics",
      "records",
      "person-campaign-finance"
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

  it("builds finance chart series from person finance values", () => {
    expect(
      buildPersonSummaryChartSeries({
        total_raised: "125.00",
        total_spent: "75.00",
        net: "50.00"
      })
    ).toEqual([
      {
        id: "finance",
        label: "Finance",
        points: [
          { x: "Raised", y: 125 },
          { x: "Spent", y: 75 },
          { x: "Net", y: 50 }
        ]
      }
    ]);
    expect(
      buildPersonOutsideSpendingChartSeries({
        support_total: "200.00",
        oppose_total: "80.00"
      })
    ).toEqual([
      {
        id: "outside-spending",
        label: "Outside spending",
        points: [
          { x: "Support", y: 200 },
          { x: "Oppose", y: 80 }
        ]
      }
    ]);
    expect(buildPersonOutsideSpendingChartSeries(null)).toEqual([]);
  });

  it("maps contribution insights into headline copy and chart series", () => {
    const viewModel = buildPersonContributionInsightsPresentation(
      CONTRIBUTION_INSIGHTS,
      PERSON_TOP_DONORS,
      PERSON_TOP_EMPLOYERS
    );

    expect(viewModel.emptyMessage).toBeNull();
    expect(viewModel.topDonors).toEqual([
      { name: "High Dollar Donor", totalAmount: "$500.00", transactionCountLabel: "4 transactions" },
      { name: "Second Dollar Donor", totalAmount: "$250.00", transactionCountLabel: "2 transactions" }
    ]);
    expect(viewModel.topDonorsEmptyMessage).toBeNull();
    expect(viewModel.topEmployers).toEqual([
      { name: "ACME CORP", totalAmount: "$600.00", transactionCountLabel: "3 transactions" },
      { name: "State University", totalAmount: "$150.00", transactionCountLabel: "1 transaction" }
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
        label: "Career",
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
    expect(viewModel.monthlyTotalsSeries).toEqual([
      {
        id: "monthly-totals",
        label: "Donations over time",
        points: [
          { x: "2026-01", y: 100 },
          { x: "2026-02", y: 250.5 }
        ]
      }
    ]);
    expect(viewModel.itemizedCountSeries).toEqual([
      {
        id: "itemized-counts",
        label: "Donation count by size bucket",
        points: [
          { x: "$1-$199", y: 3 },
          { x: "$200+", y: 2 }
        ]
      }
    ]);
    expect(viewModel.dollarsBySizeSeries).toEqual([
      {
        id: "dollars-by-size",
        label: "Dollars by size bucket",
        points: [
          { x: "Unitemized (<$200)", y: 125 },
          { x: "$1-$199", y: 175 },
          { x: "$200+", y: 175.5 }
        ]
      }
    ]);
    expect(viewModel.stateGeographySeries[0].points).toEqual([
      { x: "NC", y: 300 },
      { x: "VA", y: 50.5 }
    ]);
    expect(viewModel.districtGeographySeries[0].points).toEqual([
      { x: "NC-01", y: 275 },
      { x: "Out of district", y: 75.5 }
    ]);
    expect(viewModel.preferredGeographySeries).toBe(viewModel.districtGeographySeries);
    expect(viewModel.geographyNote).toContain("Census 119th-Congress / 2020-ZCTA approximation");
    expect(viewModel.unitemizedExclusionNote).toBe(
      "Unitemized contributions are excluded from count and geography charts."
    );
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

    expect(viewModel.preferredGeographySeries).toBe(viewModel.stateGeographySeries);
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
    expect(viewModel.dollarsBySizeSeries[0].points).toContainEqual({
      x: "$1-$199",
      y: 175
    });
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
    expect(viewModel.districtGeographySeries[0].points).toEqual([
      { x: "In district", y: 350 },
      { x: "Out of district", y: 201 },
      { x: "Unknown district", y: 75 }
    ]);
    expect(viewModel.preferredGeographySeries).toBe(viewModel.districtGeographySeries);
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
    expect(viewModel.preferredGeographySeries).toBe(viewModel.stateGeographySeries);
    expect(viewModel.geographyNote).toBe(
      "District geography is unavailable until ZCTA district reference data is loaded."
    );
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
