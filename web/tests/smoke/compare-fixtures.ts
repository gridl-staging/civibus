/** Deterministic officeholder and campaign-finance fixtures for the compare smoke suite. */

const SELECTED_CYCLE = 2026;
const COVERAGE_START_DATE = "2025-01-01";
const COVERAGE_END_DATE = "2026-06-30";
const NO_REPORTED_MONEY = "No reported/loaded money.";

/**
 */
type FixtureConfig = {
  id: string;
  name: string;
  candidateId: string;
  fecCandidateId: string;
  searchQuery: string;
  office: "H" | "S" | "P";
  state: string;
  district: string | null;
  totals: {
    raised: string;
    spent: string;
    cashOnHand: string;
    netSelfFunding: string;
    smallDollarShare: string;
  };
  charts: {
    monthlyMax: string;
    sizeBucketMax: string;
    support: string;
    oppose: string;
  };
  nationalGeography?: boolean;
  contributionInsightsDelayMs?: number;
  contributionInsightsErrorStatus?: number;
  hasItemizedData?: boolean;
  candidateSummaryStatus?: number;
};

/**
 */
function buildPersonDetail(config: FixtureConfig) {
  const [firstName, ...lastNameParts] = config.name.split(" ");
  return {
    id: config.id,
    canonical_name: config.name,
    name_variants: [],
    first_name: firstName,
    middle_name: null,
    last_name: lastNameParts.join(" "),
    suffix: null,
    occupation: null,
    education: null,
    date_of_birth: null,
    year_of_birth: null,
    bio_text: null,
    bio_source_url: null,
    bio_license: null,
    bio_pulled_at: null,
    identifiers: { fec_candidate_id: config.fecCandidateId },
    primary_address_id: null,
    er_cluster_id: null,
    er_confidence: 1,
    portrait: null,
    sources: [
      {
        domain: "campaign_finance",
        jurisdiction: "federal/fec",
        data_source_name: "Federal Election Commission",
        data_source_url: "https://www.fec.gov/",
        source_record_key: config.fecCandidateId,
        record_url: `https://www.fec.gov/data/candidate/${config.fecCandidateId}/`,
        pull_date: "2026-07-01T00:00:00Z"
      }
    ]
  };
}

/**
 */
function buildCandidate(config: FixtureConfig) {
  return {
    id: config.candidateId,
    fec_candidate_id: config.fecCandidateId,
    name: config.name,
    slug: `compare-${config.name.toLowerCase().replaceAll(" ", "-")}`,
    slug_is_unique: true,
    person_id: config.id,
    party: null,
    office: config.office,
    state: config.state,
    district: config.district,
    incumbent_challenge: "I",
    principal_committee_id: null,
    sources: []
  };
}

function buildCandidateListItem(candidate: ReturnType<typeof buildCandidate>) {
  return {
    id: candidate.id,
    fec_candidate_id: candidate.fec_candidate_id,
    name: candidate.name,
    person_id: candidate.person_id,
    party: candidate.party,
    office: candidate.office,
    state: candidate.state,
    district: candidate.district,
    slug: candidate.slug,
    slug_is_unique: candidate.slug_is_unique
  };
}

/**
 */
function buildContributionInsights(config: FixtureConfig) {
  const hasData = config.hasItemizedData !== false;
  const itemizedTotal = hasData ? config.charts.monthlyMax : "0.00";
  const smallDollarShare = hasData ? config.totals.smallDollarShare : null;
  const nationalGeography = config.nationalGeography === true;

  return {
    person_id: config.id,
    has_data: hasData,
    metadata: {
      selected_cycle: SELECTED_CYCLE,
      coverage_start_date: COVERAGE_START_DATE,
      coverage_end_date: COVERAGE_END_DATE,
      available_cycles: [SELECTED_CYCLE],
      cycles_included: [SELECTED_CYCLE],
      committee_count: 1,
      approximate_geography: !nationalGeography,
      excluded_geography: nationalGeography ? "federal_executive" : null,
      caveats: []
    },
    monthly_totals: hasData
      ? [
          { month: "2026-01", total_amount: config.charts.monthlyMax, transaction_count: 10 },
          { month: "2026-02", total_amount: "125000.00", transaction_count: 4 }
        ]
      : [],
    itemized_size_buckets: hasData
      ? [
          {
            label: "$200 and under",
            min_amount: "0.01",
            max_amount: "200.00",
            total_amount: config.charts.sizeBucketMax,
            transaction_count: 12
          }
        ]
      : [],
    dollars_by_size: hasData
      ? [
          {
            label: "$1-$200 itemized",
            total_amount: config.charts.sizeBucketMax,
            source: "transactions" as const
          }
        ]
      : [],
    cycle_totals: hasData
      ? [
          {
            cycle: SELECTED_CYCLE,
            itemized_individual_contribution_amount: itemizedTotal,
            itemized_transaction_count: 14,
            unitemized_individual_contribution_amount: "0.00",
            total_individual_contribution_amount: itemizedTotal,
            source: "itemized_transactions" as const
          }
        ]
      : [],
    career_totals: {
      itemized_individual_contribution_amount: itemizedTotal,
      itemized_transaction_count: hasData ? 14 : 0,
      unitemized_individual_contribution_amount: "0.00",
      total_individual_contribution_amount: itemizedTotal,
      source: hasData ? ("itemized_transactions" as const) : ("none" as const)
    },
    geography: {
      by_state: hasData
        ? [
            { label: nationalGeography ? "California" : config.state, total_amount: itemizedTotal, transaction_count: 14 },
            { label: "Unknown", total_amount: "0.00", transaction_count: 0 }
          ]
        : [],
      by_district:
        hasData && !nationalGeography
          ? [
              { label: "In district", total_amount: itemizedTotal, transaction_count: 14 },
              { label: "Out of district", total_amount: "0.00", transaction_count: 0 },
              { label: "Unknown", total_amount: "0.00", transaction_count: 0 }
            ]
          : [],
      district_share: {
        in_district_amount: hasData && !nationalGeography ? itemizedTotal : null,
        out_of_district_amount: hasData && !nationalGeography ? "0.00" : null,
        unknown_district_amount: hasData && !nationalGeography ? "0.00" : null,
        share: hasData && !nationalGeography ? "1.0000" : null,
        available: hasData && !nationalGeography
      },
      geography_mode: hasData
        ? nationalGeography
          ? ("state_bars_only" as const)
          : ("district" as const)
        : ("excluded" as const),
      classified_amount: itemizedTotal,
      classified_transaction_count: hasData ? 14 : 0,
      unknown_amount: "0.00",
      unknown_transaction_count: 0
    },
    small_dollar_share: {
      small_dollar_amount: smallDollarShare === null ? null : "125000.00",
      total_contribution_amount: smallDollarShare === null ? null : itemizedTotal,
      share: smallDollarShare,
      available: smallDollarShare !== null
    }
  };
}

/**
 */
function buildCandidateSummary(config: FixtureConfig) {
  const raised = Number(config.totals.raised);
  const spent = Number(config.totals.spent);
  return {
    candidate_id: config.candidateId,
    candidate_name: config.name,
    selected_cycle: SELECTED_CYCLE,
    coverage_start_date: COVERAGE_START_DATE,
    coverage_end_date: COVERAGE_END_DATE,
    available_cycles: [SELECTED_CYCLE],
    total_raised: config.totals.raised,
    total_spent: config.totals.spent,
    net: String(raised - spent),
    transaction_count: 20,
    committees: [],
    cash_on_hand: config.totals.cashOnHand,
    net_self_funding: config.totals.netSelfFunding,
    debts_owed_by_committee: "0.00",
    summary_source: "fec_weball" as const,
    itemized_transaction_count: 14,
    receipt_source_composition: [],
    selected_cycle_coverage_complete: true,
    can_render_share: true,
    receipt_source_caveats: []
  };
}

function buildIndependentExpenditureSummary(config: FixtureConfig) {
  return {
    candidate_id: config.candidateId,
    selected_cycle: SELECTED_CYCLE,
    coverage_start_date: COVERAGE_START_DATE,
    coverage_end_date: COVERAGE_END_DATE,
    available_cycles: [SELECTED_CYCLE],
    support_total: config.charts.support,
    oppose_total: config.charts.oppose,
    support_count: 2,
    oppose_count: 1,
    top_spenders: [],
    excluded_outlier_count: 0
  };
}

/**
 */
function buildIndependentExpenditures(config: FixtureConfig) {
  return [
    {
      id: `${config.candidateId}-support`,
      filing_id: null,
      committee_id: `${config.candidateId}-committee-support`,
      committee_name: `${config.name} Support Committee`,
      amount: Number(config.charts.support),
      transaction_date: "2026-05-15",
      purpose: "Independent expenditure",
      dissemination_date: "2026-05-15",
      aggregate_amount: Number(config.charts.support),
      support_oppose: "S" as const
    },
    {
      id: `${config.candidateId}-oppose`,
      filing_id: null,
      committee_id: `${config.candidateId}-committee-oppose`,
      committee_name: `${config.name} Oppose Committee`,
      amount: Number(config.charts.oppose),
      transaction_date: "2026-05-16",
      purpose: "Independent expenditure",
      dissemination_date: "2026-05-16",
      aggregate_amount: Number(config.charts.oppose),
      support_oppose: "O" as const
    }
  ];
}

function moneyLabel(value: string): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(Number(value));
}

function percentLabel(value: string): string {
  return `${(Number(value) * 100).toFixed(1)}%`;
}

/**
 */
function buildOfficeholderFixture(config: FixtureConfig) {
  const candidate = buildCandidate(config);
  const hasSummary = config.candidateSummaryStatus !== 404;
  const moneyFails = config.contributionInsightsErrorStatus !== undefined;
  const hasItemizedData = config.hasItemizedData !== false;

  return {
    id: config.id,
    name: config.name,
    candidateId: config.candidateId,
    searchQuery: config.searchQuery,
    behavior: {
      contributionInsightsDelayMs: config.contributionInsightsDelayMs ?? 0,
      contributionInsightsErrorStatus: config.contributionInsightsErrorStatus ?? null,
      candidateSummaryStatus: config.candidateSummaryStatus ?? 200
    },
    expectedTotals: {
      "total-raised": hasSummary && !moneyFails ? moneyLabel(config.totals.raised) : NO_REPORTED_MONEY,
      "total-spent": hasSummary && !moneyFails ? moneyLabel(config.totals.spent) : NO_REPORTED_MONEY,
      "cash-on-hand": hasSummary && !moneyFails ? moneyLabel(config.totals.cashOnHand) : NO_REPORTED_MONEY,
      "ie-support": hasSummary && !moneyFails ? moneyLabel(config.charts.support) : NO_REPORTED_MONEY,
      "ie-oppose": hasSummary && !moneyFails ? moneyLabel(config.charts.oppose) : NO_REPORTED_MONEY,
      "small-dollar-share": hasItemizedData && !moneyFails
        ? percentLabel(config.totals.smallDollarShare)
        : NO_REPORTED_MONEY,
      "self-funded-share": hasSummary && !moneyFails
        ? percentLabel(String(Number(config.totals.netSelfFunding) / Number(config.totals.raised)))
        : NO_REPORTED_MONEY
    },
    person: buildPersonDetail(config),
    contributionInsights: buildContributionInsights(config),
    topDonors: hasItemizedData
      ? [{ name: `${config.name} Top Donor`, total_amount: "250000.00", transaction_count: 2 }]
      : [],
    topEmployers: hasItemizedData
      ? [{ employer: `${config.name} Top Employer`, total_amount: "175000.00", transaction_count: 2 }]
      : [],
    candidate,
    candidateList: {
      items: [buildCandidateListItem(candidate)],
      has_next: false,
      offset: 0,
      limit: 10
    },
    candidateSummary: hasSummary ? buildCandidateSummary(config) : null,
    independentExpenditureSummary: hasSummary
      ? buildIndependentExpenditureSummary(config)
      : null,
    independentExpenditures: hasSummary ? buildIndependentExpenditures(config) : []
  };
}

export const compareOfficeholders = [
  buildOfficeholderFixture({
    id: "10000000-0000-4000-8000-000000000001",
    name: "Avery Delayed",
    candidateId: "10000000-0000-4000-8000-000000000101",
    fecCandidateId: "H6NC00001",
    searchQuery: "avery compare",
    office: "H",
    state: "NC",
    district: "01",
    totals: {
      raised: "5000000.00",
      spent: "3000000.00",
      cashOnHand: "1000000.00",
      netSelfFunding: "500000.00",
      smallDollarShare: "0.1250"
    },
    charts: {
      monthlyMax: "1000000.00",
      sizeBucketMax: "700000.00",
      support: "400000.00",
      oppose: "25000.00"
    },
    contributionInsightsDelayMs: 1200
  }),
  buildOfficeholderFixture({
    id: "20000000-0000-4000-8000-000000000002",
    name: "Blair National",
    candidateId: "20000000-0000-4000-8000-000000000102",
    fecCandidateId: "P6US00002",
    searchQuery: "blair compare",
    office: "P",
    state: "US",
    district: null,
    totals: {
      raised: "2000000.00",
      spent: "1500000.00",
      cashOnHand: "200000.00",
      netSelfFunding: "50000.00",
      smallDollarShare: "0.2500"
    },
    charts: {
      monthlyMax: "250000.00",
      sizeBucketMax: "300000.00",
      support: "100000.00",
      oppose: "300000.00"
    },
    nationalGeography: true
  }),
  buildOfficeholderFixture({
    id: "30000000-0000-4000-8000-000000000003",
    name: "Casey No Data",
    candidateId: "30000000-0000-4000-8000-000000000103",
    fecCandidateId: "S6VT00003",
    searchQuery: "casey compare",
    office: "S",
    state: "VT",
    district: null,
    totals: {
      raised: "0.00",
      spent: "0.00",
      cashOnHand: "0.00",
      netSelfFunding: "0.00",
      smallDollarShare: "0.0000"
    },
    charts: { monthlyMax: "0.00", sizeBucketMax: "0.00", support: "0.00", oppose: "0.00" },
    hasItemizedData: false,
    candidateSummaryStatus: 404
  }),
  buildOfficeholderFixture({
    id: "40000000-0000-4000-8000-000000000004",
    name: "Devon Money Error",
    candidateId: "40000000-0000-4000-8000-000000000104",
    fecCandidateId: "H6OR00004",
    searchQuery: "devon compare",
    office: "H",
    state: "OR",
    district: "03",
    totals: {
      raised: "750000.00",
      spent: "500000.00",
      cashOnHand: "125000.00",
      netSelfFunding: "0.00",
      smallDollarShare: "0.1000"
    },
    charts: {
      monthlyMax: "100000.00",
      sizeBucketMax: "80000.00",
      support: "50000.00",
      oppose: "10000.00"
    },
    contributionInsightsErrorStatus: 503
  })
] as const;

export const compareFixtureById = new Map(compareOfficeholders.map((fixture) => [fixture.id, fixture]));
export const compareFixtureByCandidateId = new Map(
  compareOfficeholders.map((fixture) => [fixture.candidateId, fixture])
);
export const compareFixtureBySearchQuery = new Map(
  compareOfficeholders.map((fixture) => [fixture.searchQuery, fixture])
);

export const compareExpectedChartScales = {
  monthlyContributions: { value: 1_000_000, label: "$1,000,000.00" },
  sizeBucketDollars: { value: 700_000, label: "$700,000.00" },
  outsideSpending: { value: 400_000, label: "$400,000.00" }
} as const;

export const compareMetricRows = [
  { id: "total-raised", label: "Total receipts" },
  { id: "total-spent", label: "Total disbursements" },
  { id: "cash-on-hand", label: "Cash on hand" },
  { id: "ie-support", label: "Outside spending supporting" },
  { id: "ie-oppose", label: "Outside spending opposing" },
  { id: "small-dollar-share", label: "Small-dollar share" },
  { id: "self-funded-share", label: "Self-funded share" }
] as const;

export const compareUnknownPersonId = "99999999-9999-4999-8999-999999999999";
export const compareNationalGeographyCopy =
  "Geography basis: Federal executive offices use national fundraising geography.";
export const compareNoItemizedCopy = "Itemized contribution rows are not loaded yet.";
export const compareNoSummaryCopy = "No official candidate summary is loaded for this column.";
