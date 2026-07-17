import type {
  CandidateDetailResponse,
  CandidateFundraisingSummary,
  IndependentExpenditureResponse,
  IndependentExpenditureSummary,
  PersonContributionInsights
} from "$lib/campaign-finance-detail/contract";
import type { EntityDetailBundle } from "$lib/server/api/entity-detail";
import type { PersonCandidateFinanceSection } from "$lib/server/api/campaign-finance-detail";
import { describe, expect, it } from "vitest";
import type { CompareColumn, ResolvedPersonMoneyBundle } from "./+page.server";
import { buildComparePresentation } from "./presentation";

const SELECTED_CYCLE_FIELDS = {
  selected_cycle: 2026,
  coverage_start_date: "2025-01-01",
  coverage_end_date: "2026-06-30",
  available_cycles: [2026]
};

function resolved<T>(value: T): Promise<T> {
  return value as unknown as Promise<T>;
}

function buildPerson(id: string, name: string): EntityDetailBundle {
  return {
    entityType: "person",
    detail: {
      id,
      canonical_name: name,
      name_variants: [],
      first_name: name.split(" ")[0] ?? null,
      middle_name: null,
      last_name: name.split(" ").slice(1).join(" ") || null,
      suffix: null,
      occupation: null,
      education: null,
      date_of_birth: null,
      year_of_birth: null,
      bio_text: null,
      bio_source_url: null,
      bio_license: null,
      bio_pulled_at: null,
      identifiers: {},
      primary_address_id: null,
      er_cluster_id: null,
      er_confidence: null,
      portrait: null,
      sources: [
        {
          domain: "campaign_finance",
          jurisdiction: "federal/fec",
          data_source_name: "FEC",
          data_source_url: "https://www.fec.gov",
          source_record_key: id,
          record_url: `https://example.test/person/${id}`,
          pull_date: "2026-07-01T00:00:00Z"
        }
      ]
    }
  };
}

function buildSummary(
  candidateId: string,
  overrides: Partial<CandidateFundraisingSummary> = {}
): CandidateFundraisingSummary {
  return {
    ...SELECTED_CYCLE_FIELDS,
    candidate_id: candidateId,
    candidate_name: `Candidate ${candidateId}`,
    total_raised: "1000.00",
    total_spent: "600.00",
    net: "400.00",
    transaction_count: 10,
    itemized_transaction_count: 8,
    cash_on_hand: "250.00",
    net_self_funding: "100.00",
    debts_owed_by_committee: "0.00",
    summary_source: "fec_weball",
    receipt_source_composition: [],
    selected_cycle_coverage_complete: true,
    can_render_share: true,
    receipt_source_caveats: [],
    committees: [],
    ...overrides
  };
}

function buildCandidate(candidateId: string, personId: string): CandidateDetailResponse {
  return {
    id: candidateId,
    fec_candidate_id: `H${candidateId}`,
    name: `Candidate ${candidateId}`,
    slug: candidateId,
    slug_is_unique: true,
    person_id: personId,
    party: null,
    office: "H",
    state: "NC",
    district: "01",
    incumbent_challenge: null,
    principal_committee_id: null,
    sources: []
  };
}

function buildIeSummary(overrides: Partial<IndependentExpenditureSummary> = {}): IndependentExpenditureSummary {
  return {
    ...SELECTED_CYCLE_FIELDS,
    candidate_id: "candidate",
    support_total: "400.00",
    oppose_total: "25.00",
    support_count: 2,
    oppose_count: 1,
    top_spenders: [],
    excluded_outlier_count: 0,
    ...overrides
  };
}

function buildInsights(
  personId: string,
  smallDollarShare: string | null,
  overrides: Partial<PersonContributionInsights> = {}
): PersonContributionInsights {
  return {
    person_id: personId,
    has_data: true,
    metadata: {
      ...SELECTED_CYCLE_FIELDS,
      cycles_included: [2026],
      committee_count: 1,
      approximate_geography: false,
      excluded_geography: null,
      caveats: []
    },
    monthly_totals: [{ month: "2026-01", total_amount: "100.00", transaction_count: 2 }],
    itemized_size_buckets: [],
    dollars_by_size: [],
    cycle_totals: [],
    career_totals: {
      itemized_individual_contribution_amount: "100.00",
      itemized_transaction_count: 2,
      unitemized_individual_contribution_amount: "0.00",
      total_individual_contribution_amount: "100.00",
      source: "itemized_transactions"
    },
    geography: {
      by_state: [],
      by_district: [],
      district_share: {
        in_district_amount: null,
        out_of_district_amount: null,
        unknown_district_amount: null,
        share: null,
        available: false
      },
      geography_mode: "excluded",
      classified_amount: "0.00",
      classified_transaction_count: 0,
      unknown_amount: "0.00",
      unknown_transaction_count: 0
    },
    small_dollar_share: {
      small_dollar_amount: smallDollarShare === null ? null : "150.00",
      total_contribution_amount: smallDollarShare === null ? null : "1000.00",
      share: smallDollarShare,
      available: smallDollarShare !== null
    },
    ...overrides
  };
}

function buildSection(
  personId: string,
  candidateId: string,
  summary: CandidateFundraisingSummary | null,
  ieSummary: IndependentExpenditureSummary | null = null,
  ieTransactions: IndependentExpenditureResponse[] = []
): PersonCandidateFinanceSection {
  return {
    candidate: buildCandidate(candidateId, personId),
    summary: resolved(summary as CandidateFundraisingSummary),
    ieSummary,
    ieTransactions: resolved(ieTransactions),
    donorVendorTransactions: resolved([])
  };
}

function buildMoneyBundle(
  personId: string,
  sections: PersonCandidateFinanceSection[],
  smallDollarShare: string | null,
  insightsOverrides: Partial<PersonContributionInsights> = {}
): ResolvedPersonMoneyBundle {
  return {
    personFinanceSections: sections,
    personContributionInsights: buildInsights(personId, smallDollarShare, insightsOverrides),
    personTopDonors: [],
    personTopEmployers: []
  };
}

function fulfilled(value: ResolvedPersonMoneyBundle): PromiseFulfilledResult<ResolvedPersonMoneyBundle> {
  return { status: "fulfilled", value };
}

describe("compare presentation", () => {
  it("builds ordered shared-scale rows with exact labels, copy, and provenance", async () => {
    const columns: CompareColumn[] = [
      { personId: "ada", person: buildPerson("ada", "Ada North"), money: resolved({} as ResolvedPersonMoneyBundle) },
      { personId: "ben", person: buildPerson("ben", "Ben South"), money: resolved({} as ResolvedPersonMoneyBundle) }
    ];
    const outcomes: PromiseSettledResult<ResolvedPersonMoneyBundle>[] = [
      fulfilled(
        buildMoneyBundle(
          "ada",
          [
            buildSection(
              "ada",
              "ada-1",
              buildSummary("ada-1", {
                total_raised: "1200.00",
                total_spent: "700.00",
                cash_on_hand: "300.00",
                net_self_funding: "300.00",
                coverage_end_date: "2026-04-30"
              }),
              buildIeSummary({ support_total: "400.00", oppose_total: "25.00" })
            )
          ],
          "0.1250"
        )
      ),
      fulfilled(
        buildMoneyBundle(
          "ben",
          [
            buildSection(
              "ben",
              "ben-1",
              buildSummary("ben-1", {
                total_raised: "2000.00",
                total_spent: "1500.00",
                cash_on_hand: "200.00",
                net_self_funding: "50.00",
                coverage_end_date: "2026-05-31"
              }),
              buildIeSummary({ support_total: "100.00", oppose_total: "300.00" })
            )
          ],
          "0.2500"
        )
      )
    ];

    const presentation = await buildComparePresentation(columns, outcomes);

    expect(presentation.answerFirstSummary).toBe(
      "Ben South has the most total receipts at $2,000.00; Ada North has the most outside support at $400.00."
    );
    expect(presentation.dataThroughLabel).toBe("Data through 2026-05-31");
    expect(presentation.fairnessCopy).toBe(
      "Compare each officeholder within that person's selected cycle, using official FEC summaries when available and itemized records where summaries are not yet loaded."
    );
    expect(presentation.fairnessCopy).not.toContain("same selected cycle");
    expect(presentation.provenanceCopy).toContain("Federal Election Commission");
    expect(presentation.columns.map((column) => column.name)).toEqual(["Ada North", "Ben South"]);
    expect(presentation.columns.every((column) => column.status === "ready")).toBe(true);
    expect(presentation.columns[0].provenanceLinks[0]).toEqual({
      label: "FEC",
      href: "https://example.test/person/ada"
    });
    expect(
      presentation.charts.map((chart) =>
        chart.outsideSpending?.rows.map((row) => [row.id, row.label, row.amount])
      )
    ).toEqual([
      [
        ["ada-1-support-spending", "Support spending", 400],
        ["ada-1-oppose-spending", "Oppose spending", 25]
      ],
      [
        ["ben-1-support-spending", "Support spending", 100],
        ["ben-1-oppose-spending", "Oppose spending", 300]
      ]
    ]);

    expect(presentation.rows.map((row) => [row.id, row.label, row.scaleMax])).toEqual([
      ["total-raised", "Total receipts", 2000],
      ["total-spent", "Total disbursements", 1500],
      ["cash-on-hand", "Cash on hand", 300],
      ["ie-support", "Outside spending supporting", 400],
      ["ie-oppose", "Outside spending opposing", 300],
      ["small-dollar-share", "Small-dollar share", 0.25],
      ["self-funded-share", "Self-funded share", 0.25]
    ]);
    expect(
      presentation.rows.map((row) => row.cells.map((cell) => [cell.state, cell.label, cell.value]))
    ).toEqual([
      [
        ["available", "$1,200.00", 1200],
        ["available", "$2,000.00", 2000]
      ],
      [
        ["available", "$700.00", 700],
        ["available", "$1,500.00", 1500]
      ],
      [
        ["available", "$300.00", 300],
        ["available", "$200.00", 200]
      ],
      [
        ["available", "$400.00", 400],
        ["available", "$100.00", 100]
      ],
      [
        ["available", "$25.00", 25],
        ["available", "$300.00", 300]
      ],
      [
        ["available", "12.5%", 0.125],
        ["available", "25.0%", 0.25]
      ],
      [
        ["available", "25.0%", 0.25],
        ["available", "2.5%", 0.025]
      ]
    ]);
  });

  it("keeps unavailable and failed columns out of numeric maxima instead of converting them to zero", async () => {
    const columns: CompareColumn[] = [
      { personId: "ready", person: buildPerson("ready", "Ready Person"), money: resolved({} as ResolvedPersonMoneyBundle) },
      { personId: "partial", person: buildPerson("partial", "Partial Person"), money: resolved({} as ResolvedPersonMoneyBundle) },
      { personId: "failed", person: buildPerson("failed", "Failed Person"), money: resolved({} as ResolvedPersonMoneyBundle) }
    ];
    const outcomes: PromiseSettledResult<ResolvedPersonMoneyBundle>[] = [
      fulfilled(
        buildMoneyBundle(
          "ready",
          [
            buildSection(
              "ready",
              "ready-1",
              buildSummary("ready-1", { total_raised: "1000.00", net_self_funding: "100.00" })
            )
          ],
          "0.1000"
        )
      ),
      fulfilled(
        buildMoneyBundle(
          "partial",
          [
            buildSection(
              "partial",
              "partial-1",
              buildSummary("partial-1", { total_raised: "500.00", net_self_funding: "20.00" })
            ),
            buildSection("partial", "partial-2", null)
          ],
          null
        )
      ),
      { status: "rejected", reason: new Error("money unavailable") }
    ];

    const presentation = await buildComparePresentation(columns, outcomes);
    const selfFundedRow = presentation.rows.find((row) => row.id === "self-funded-share");
    const smallDollarRow = presentation.rows.find((row) => row.id === "small-dollar-share");

    expect(presentation.columns.map((column) => column.status)).toEqual(["ready", "ready", "error"]);
    expect(presentation.charts.map((chart) => chart.outsideSpending)).toEqual([null, null, null]);
    expect(selfFundedRow?.scaleMax).toBe(0.1);
    expect(selfFundedRow?.cells.map((cell) => [cell.state, cell.label, cell.value])).toEqual([
      ["available", "10.0%", 0.1],
      ["unavailable", "Not available", null],
      ["unavailable", "Not available", null]
    ]);
    expect(smallDollarRow?.scaleMax).toBe(0.1);
    expect(smallDollarRow?.cells.map((cell) => [cell.state, cell.label, cell.value])).toEqual([
      ["available", "10.0%", 0.1],
      ["unavailable", "Not available", null],
      ["unavailable", "Not available", null]
    ]);
  });

  it("shares one chart scale per chart row across columns and excludes failed columns", async () => {
    const columns: CompareColumn[] = [
      { personId: "ada", person: buildPerson("ada", "Ada North"), money: resolved({} as ResolvedPersonMoneyBundle) },
      { personId: "ben", person: buildPerson("ben", "Ben South"), money: resolved({} as ResolvedPersonMoneyBundle) },
      { personId: "failed", person: buildPerson("failed", "Failed Person"), money: resolved({} as ResolvedPersonMoneyBundle) }
    ];
    const outcomes: PromiseSettledResult<ResolvedPersonMoneyBundle>[] = [
      fulfilled(
        buildMoneyBundle(
          "ada",
          [
            buildSection(
              "ada",
              "ada-1",
              buildSummary("ada-1"),
              buildIeSummary({ support_total: "400.00", oppose_total: "25.00" })
            )
          ],
          "0.1250",
          {
            monthly_totals: [
              { month: "2026-01", total_amount: "100.00", transaction_count: 2 },
              { month: "2026-02", total_amount: "250.00", transaction_count: 3 }
            ],
            itemized_size_buckets: [
              { label: "$500-$999.99", min_amount: "500.00", max_amount: "999.99", total_amount: "700.00", transaction_count: 4 }
            ]
          }
        )
      ),
      fulfilled(
        buildMoneyBundle(
          "ben",
          [
            buildSection(
              "ben",
              "ben-1",
              buildSummary("ben-1"),
              buildIeSummary({ support_total: "100.00", oppose_total: "300.00" })
            )
          ],
          "0.2500",
          {
            monthly_totals: [{ month: "2026-01", total_amount: "900.00", transaction_count: 9 }],
            itemized_size_buckets: [
              { label: "$2,000 and over", min_amount: "2000.00", max_amount: null, total_amount: "300.00", transaction_count: 2 }
            ]
          }
        )
      ),
      { status: "rejected", reason: new Error("money unavailable") }
    ];

    const presentation = await buildComparePresentation(columns, outcomes);

    // Hand-calculated across the two fulfilled columns only:
    // monthly max(100, 250, 900) = 900; size-bucket dollars max(700, 300) = 700;
    // outside spending max(|400|, |25|, |100|, |300|) = 400.
    expect(presentation.chartScales.monthlyContributions).toEqual({ max: 900, maxLabel: "$900.00" });
    expect(presentation.chartScales.sizeBucketDollars).toEqual({ max: 700, maxLabel: "$700.00" });
    expect(presentation.chartScales.outsideSpending).toEqual({ max: 400, maxLabel: "$400.00" });
    expect(presentation.columns.map((column) => column.status)).toEqual(["ready", "ready", "error"]);
    expect(presentation.charts[2].contributionInsights).toBeNull();
  });

  it("reports an unavailable chart scale when no column has plottable chart data", async () => {
    const columns: CompareColumn[] = [
      { personId: "ada", person: buildPerson("ada", "Ada North"), money: resolved({} as ResolvedPersonMoneyBundle) }
    ];
    const outcomes: PromiseSettledResult<ResolvedPersonMoneyBundle>[] = [
      fulfilled(
        buildMoneyBundle("ada", [buildSection("ada", "ada-1", buildSummary("ada-1"))], "0.1250", {
          monthly_totals: [],
          itemized_size_buckets: []
        })
      )
    ];

    const presentation = await buildComparePresentation(columns, outcomes);

    expect(presentation.chartScales.monthlyContributions.max).toBe(0);
    expect(presentation.chartScales.sizeBucketDollars.max).toBe(0);
    expect(presentation.chartScales.outsideSpending.max).toBe(0);
  });
});
