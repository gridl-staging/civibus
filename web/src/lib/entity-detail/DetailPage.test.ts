import { readFileSync } from "node:fs";
import { render } from "svelte/server";
import { describe, expect, it, vi } from "vitest";
import type { PersonCandidateFinanceSection } from "$lib/server/api/campaign-finance-detail";
import type { EntityDetailPageBundle } from "$lib/server/api/entity-detail";
import DetailPage from "./DetailPage.svelte";

vi.mock("$app/navigation", () => ({
  goto: vi.fn()
}));

const PERSON_ID = "11111111-1111-4111-8111-111111111111";
const CANDIDATE_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee";
const COMMITTEE_ID = "ffffffff-ffff-4fff-8fff-ffffffffffff";
const FILING_ID = "66666666-6666-4666-8666-666666666666";
const SELECTED_CYCLE_FIELDS = {
  selected_cycle: 2026,
  coverage_start_date: "2025-01-01",
  coverage_end_date: "2026-12-31",
  available_cycles: [2022, 2024, 2026]
};

const CONTRIBUTION_INSIGHTS = {
  person_id: PERSON_ID,
  has_data: true,
  metadata: {
    ...SELECTED_CYCLE_FIELDS,
    coverage_start_date: "2022-01-01",
    coverage_end_date: "2026-06-30",
    cycles_included: [2022, 2024, 2026],
    committee_count: 1,
    approximate_geography: true,
    excluded_geography: null,
    caveats: []
  },
  monthly_totals: [{ month: "2026-01", total_amount: "100.00", transaction_count: 1 }],
  itemized_size_buckets: [
    {
      label: "$200 and under",
      min_amount: "0.01",
      max_amount: "200.00",
      total_amount: "100.00",
      transaction_count: 1
    }
  ],
  dollars_by_size: [
    { label: "$200 and under", total_amount: "100.00", source: "transactions" as const }
  ],
  cycle_totals: [
    {
      cycle: 2026,
      itemized_individual_contribution_amount: "100.00",
      itemized_transaction_count: 1,
      unitemized_individual_contribution_amount: "125.00",
      total_individual_contribution_amount: "225.00",
      source: "mixed_sources" as const
    }
  ],
  career_totals: {
    itemized_individual_contribution_amount: "200.00",
    itemized_transaction_count: 2,
    unitemized_individual_contribution_amount: "125.00",
    total_individual_contribution_amount: "325.00",
    source: "mixed_sources" as const
  },
  geography: {
    by_state: [{ label: "NC", total_amount: "100.00", transaction_count: 1 }],
    by_district: [{ label: "NC-01", total_amount: "100.00", transaction_count: 1 }],
    district_share: {
      in_district_amount: "100.00",
      out_of_district_amount: "0.00",
      unknown_district_amount: "0.00",
      share: "1.0000",
      available: true
    },
    geography_mode: "district" as const,
    classified_amount: "100.00",
    classified_transaction_count: 1,
    unknown_amount: "0.00",
    unknown_transaction_count: 0
  },
  small_dollar_share: {
    small_dollar_amount: "225.00",
    total_contribution_amount: "225.00",
    share: "1.0000",
    available: true
  }
};

const PERSON_TOP_DONORS = [
  { name: "Largest Person Donor", total_amount: "500.00", transaction_count: 4 },
  { name: "Second Person Donor", total_amount: "250.00", transaction_count: 2 }
];

const PERSON_TOP_EMPLOYERS = [
  { employer: "ACME CORP", total_amount: "600.00", transaction_count: 3 },
  { employer: "State University", total_amount: "150.00", transaction_count: 1 }
];

function asSettled<T>(value: T): Promise<T> {
  return value as unknown as Promise<T>;
}

function buildLoadedMoneyHeadline() {
  return {
    kind: "loaded" as const,
    summary: {
      ...SELECTED_CYCLE_FIELDS,
      candidate_id: "person",
      candidate_name: "Person aggregate",
      total_raised: "1000.00",
      total_spent: "600.00",
      net: "400.00",
      transaction_count: 3,
      itemized_transaction_count: 3,
      cash_on_hand: null,
      net_self_funding: null,
      debts_owed_by_committee: "45.00",
      summary_source: "derived" as const,
      receipt_source_composition: [
        {
          label: "Gross individual contributions",
          total_amount: "900.00",
          source: "fec_committee_summary" as const
        },
        {
          label: "PAC/other committee contributions",
          total_amount: "100.00",
          source: "fec_committee_summary" as const
        }
      ],
      selected_cycle_coverage_complete: true,
      can_render_share: true,
      receipt_source_caveats: [],
      committees: []
    }
  };
}

function buildPersonFinanceSection(
  overrides: Partial<PersonCandidateFinanceSection> = {}
): PersonCandidateFinanceSection {
  return {
    candidate: {
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
    },
    summary: asSettled({
      ...SELECTED_CYCLE_FIELDS,
      candidate_id: CANDIDATE_ID,
      candidate_name: "Candidate One",
      total_raised: "1000.00",
      total_spent: "600.00",
      net: "400.00",
      transaction_count: 3,
      itemized_transaction_count: 3,
      cash_on_hand: null,
      net_self_funding: null,
      debts_owed_by_committee: "45.00",
      summary_source: "derived" as const,
      receipt_source_composition: [
        {
          label: "Gross individual contributions",
          total_amount: "900.00",
          source: "fec_committee_summary" as const
        },
        {
          label: "PAC/other committee contributions",
          total_amount: "100.00",
          source: "fec_committee_summary" as const
        }
      ],
      selected_cycle_coverage_complete: true,
      can_render_share: true,
      receipt_source_caveats: [],
      committees: [
        {
          ...SELECTED_CYCLE_FIELDS,
          committee_id: COMMITTEE_ID,
          committee_name: "Friends of Candidate One",
          slug: "friends-of-candidate-one",
          slug_is_unique: true,
          total_raised: "750.00",
          total_spent: "400.00",
          net: "350.00",
          transaction_count: 2,
          jurisdiction: "NC",
          data_through: "2026-03-31",
          cash_receipts_total: "700.00",
          in_kind_receipts_total: "20.00",
          loan_receipts_total: "30.00",
          contribution_receipts_total: "710.00",
          top_donors: [],
          top_vendors: [],
          spend_categories: null,
          itemized_transaction_count: 2,
          cycle_summaries: [],
          summary_source: "derived" as const,
          receipt_source_composition: [
            {
              label: "Gross individual contributions",
              total_amount: "650.00",
              source: "fec_committee_summary" as const
            },
            {
              label: "PAC/other committee contributions",
              total_amount: "100.00",
              source: "fec_committee_summary" as const
            }
          ],
          selected_cycle_coverage_complete: true,
          can_render_share: true,
          receipt_source_caveats: [],
          debts_owed_by_committee: "45.00"
        }
      ]
    }),
    ieTransactions: asSettled([
      {
        id: "ie-1",
        filing_id: FILING_ID,
        committee_id: COMMITTEE_ID,
        committee_name: "Outside Group A",
        amount: 1250,
        transaction_date: "2026-02-01",
        purpose: "Digital ads",
        dissemination_date: "2026-02-02",
        aggregate_amount: null,
        support_oppose: "S"
      }
    ]),
    ieSummary: {
      ...SELECTED_CYCLE_FIELDS,
      candidate_id: CANDIDATE_ID,
      support_total: "1250.00",
      oppose_total: "200.00",
      support_count: 1,
      oppose_count: 1,
      excluded_outlier_count: 0,
      top_spenders: [
        {
          committee_id: COMMITTEE_ID,
          committee_name: "Outside Group A",
          support_oppose: "S",
          total_amount: "1250.00",
          transaction_count: 1
        }
      ]
    },
    donorVendorTransactions: asSettled([
      {
        id: "tx-1",
        filing_id: "filing-1",
        committee_id: COMMITTEE_ID,
        transaction_type: "CONTRIBUTION",
        transaction_identifier: null,
        transaction_date: "2026-01-15",
        amount: 125.5,
        contributor_name_raw: "Acme Donor LLC",
        contributor_employer: null,
        contributor_occupation: null,
        contributor_city: null,
        contributor_state: null,
        contributor_zip: null,
        contributor_person_id: null,
        contributor_organization_id: null,
        contributor_address_id: null,
        recipient_candidate_id: CANDIDATE_ID,
        recipient_committee_id: COMMITTEE_ID,
        memo_text: null,
        is_memo: false,
        amendment_indicator: "N",
        date_is_reliable: true
      }
    ]),
    ...overrides
  };
}

function buildPersonPageBundle(
  overrides: Partial<EntityDetailPageBundle> = {}
): EntityDetailPageBundle {
  return {
    entityType: "person",
    detail: {
      id: PERSON_ID,
      canonical_name: "Jane Doe",
      name_variants: [],
      first_name: "Jane",
      middle_name: null,
      last_name: "Doe",
      suffix: null,
      occupation: "Attorney",
      education: "State University",
      date_of_birth: null,
      year_of_birth: 1985,
      bio_text: null,
      bio_source_url: null,
      bio_license: null,
      bio_pulled_at: null,
      identifiers: { fec_candidate_id: "H0NC01001" },
      primary_address_id: null,
      er_cluster_id: null,
      er_confidence: null,
      portrait: {
        status: "active",
        rights_status: "licensed",
        source_image_url: "https://images.example.org/jane-doe.jpg",
        mime_type: "image/jpeg",
        width_px: 512,
        height_px: 512
      },
      sources: []
    },
    personFinanceSections: asSettled([]),
    personContributionInsights: asSettled(CONTRIBUTION_INSIGHTS),
    personTopDonors: asSettled(PERSON_TOP_DONORS),
    personTopEmployers: asSettled(PERSON_TOP_EMPLOYERS),
    ...overrides
  };
}

describe("entity detail page rendering", () => {
  it("renders public person detail with identifier metrics and no ER/graph/civic internals", () => {
    const rendered = render(DetailPage, {
      props: { data: buildPersonPageBundle() }
    });

    expect(rendered.body).toContain("Portrait of Jane Doe");
    expect(rendered.body).toContain("<h3>Core attributes</h3>");
    expect(rendered.body).toContain("<dt>Identifiers</dt>");
    expect(rendered.body).toContain("<dd>1</dd>");
    expect(rendered.body).toContain('data-testid="entity-metric-identifiers"');
    expect(rendered.body).not.toContain("ER matches");
    expect(rendered.body).not.toContain("Graph relationships");
    expect(rendered.body).not.toContain("Civic Record");
    expect(rendered.body).not.toContain("Officeholding timeline");
    expect(rendered.body).not.toContain("Entity internals");
  });

  it("renders a route-owned compare entry point when a person compare href is provided", () => {
    const rendered = render(DetailPage, {
      props: {
        data: buildPersonPageBundle(),
        compareHref: "/compare?people=11111111-1111-4111-8111-111111111111"
      }
    });

    expect(rendered.body).toContain("Compare");
    expect(rendered.body).toContain(
      'href="/compare?people=11111111-1111-4111-8111-111111111111"'
    );
  });

  it("renders public organization detail without person finance or graph sections", () => {
    const data: EntityDetailPageBundle = {
      entityType: "org",
      detail: {
        id: "22222222-2222-4222-8222-222222222222",
        canonical_name: "Civibus Action Org",
        name_variants: [],
        org_type: "pac",
        identifiers: {},
        registered_state: "NC",
        formation_date: "2014-05-01",
        dissolution_date: null,
        primary_address_id: null,
        er_cluster_id: null,
        er_confidence: null,
        sources: []
      }
    };

    const rendered = render(DetailPage, { props: { data } });

    expect(rendered.body).toContain("Civibus Action Org");
    expect(rendered.body).toContain("No identifiers are available yet.");
    expect(rendered.body).not.toContain("Campaign finance");
    expect(rendered.body).not.toContain("Entity internals");
  });

  it("renders person bio section with source link and mapped license label", () => {
    const rendered = render(DetailPage, {
      props: {
        data: buildPersonPageBundle({
          detail: {
            ...buildPersonPageBundle().detail,
            bio_text: "Jane Doe is serving her third term in office.",
            bio_source_url: "https://www.ncleg.gov/Members/Biography/H/57",
            bio_license: "licensed",
            bio_pulled_at: "2026-04-29T14:30:00Z"
          }
        })
      }
    });

    expect(rendered.body).toContain("<h3>Biography</h3>");
    expect(rendered.body).toContain("Jane Doe is serving her third term in office.");
    expect(rendered.body).toContain('href="https://www.ncleg.gov/Members/Biography/H/57"');
    expect(rendered.body).toContain('rel="noopener noreferrer"');
    expect(rendered.body).toContain("Licensed (CC BY-SA)");
  });

  it("does not render a clickable bio link for unsafe bio source URL schemes", () => {
    const rendered = render(DetailPage, {
      props: {
        data: buildPersonPageBundle({
          detail: {
            ...buildPersonPageBundle().detail,
            bio_text: "Jane Doe is serving her third term in office.",
            bio_source_url: "javascript:alert(1)",
            bio_license: "unknown",
            bio_pulled_at: "2026-04-29T14:30:00Z"
          }
        })
      }
    });

    expect(rendered.body).not.toContain('href="javascript:alert(1)"');
    expect(rendered.body).toContain("Biography source unavailable");
  });

  it("renders person campaign-finance sections from the existing finance owner shape", () => {
    const rendered = render(DetailPage, {
      props: {
        data: buildPersonPageBundle({
          personFinanceSections: asSettled([buildPersonFinanceSection()])
        })
      }
    });

    expect(rendered.body).toContain("<h3>Campaign finance</h3>");
    expect(rendered.body).toContain("Candidate One");
    expect(rendered.body).toContain("Money at a glance");
    expect(rendered.body).toContain('aria-label="Election cycle"');
    expect(rendered.body.match(/aria-label="Election cycle"/g)).toHaveLength(1);
    expect(rendered.body).toContain('aria-current="page"');
    expect(rendered.body).toContain('href="?cycle=2022"');
    expect(rendered.body).toContain('href="?cycle=2024"');
    expect(rendered.body).toContain('href="?cycle=2026"');
    expect(rendered.body).toContain("2026 cycle");
    expect(rendered.body).toContain("Coverage");
    expect(rendered.body).toContain("2025-01-01 to 2026-12-31");
    expect(rendered.body).toContain("Source");
    expect(rendered.body).toContain("Derived from itemized transactions");
    expect(rendered.body).toContain("Total receipts");
    expect(rendered.body).toContain("$1,000.00");
    expect(rendered.body).toContain("Total disbursements");
    expect(rendered.body).toContain("$600.00");
    expect(rendered.body).toContain("Cash on hand");
    expect(rendered.body).toContain("Not available");
    expect(rendered.body).toContain("Debts owed by the committee");
    expect(rendered.body).toContain("$45.00");
    expect(rendered.body).toContain("Friends of Candidate One");
    expect(rendered.body).toContain("Acme Donor LLC");
    expect(rendered.body).toContain("2026-01-15");
    expect(rendered.body).toContain("CONTRIBUTION");
    expect(rendered.body).toContain("<h4>Fundraising detail</h4>");
    expect(rendered.body).toContain("100%");
    expect(rendered.body).toContain("$225.00 of $225.00 from small-dollar sources");
    expect(rendered.body).toContain("<h5>Individual contribution totals</h5>");
    expect(rendered.body).toContain("2026 cycle");
    expect(rendered.body).toContain("$225.00");
    expect(rendered.body).toContain("Recent history total (2022-2026)");
    expect(rendered.body).toContain(
      "Totals combine itemized transactions with available committee-summary data; unitemized coverage may be incomplete."
    );
    expect(rendered.body).toContain("Sources of receipts");
    expect(rendered.body).toContain("Receipt components disclose $1,000.00 in total receipts for the 2026 cycle.");
    expect(rendered.body).toContain("Itemized individual contributions by month");
    expect(rendered.body).toContain("Itemized individual contributions total $100.00 in the 2026 cycle.");
    expect(rendered.body).toContain("Itemized contribution-size buckets");
    expect(rendered.body).toContain("Dollars | Reported transactions");
    expect(rendered.body).toContain("Geography");
    expect(rendered.body).toContain("View chart data");
    expect(rendered.body).toContain("Unknown is included in the visible geography denominator.");
    expect(rendered.body).not.toContain("outside the classified geography denominator");
    expect(rendered.body).not.toContain("Donation count by size bucket");
    expect(rendered.body).not.toContain("Dollars by size bucket");
    expect(rendered.body).not.toContain("Fundraising geography");
    expect(rendered.body).toContain("District share");
    expect(rendered.body).toContain("100% in district");
    expect(rendered.body).toContain("$100.00 in district and $0.00 out of district.");
    expect(rendered.body).toContain("<h5>Top reported contributor names</h5>");
    expect(rendered.body).toContain("detail__rank-bar");
    expect(rendered.body).toContain("Largest Person Donor");
    expect(rendered.body).toContain("$500.00");
    expect(rendered.body).toContain("Second Person Donor");
    expect(rendered.body).toContain("<h5>Top reported employer names</h5>");
    expect(rendered.body).toContain("Top employers aggregate raw employer names from itemized individual contributions only.");
    expect(rendered.body).toContain("They are not industry- or sector-coded; see Methodology for source-linking and evidence limitations.");
    expect(rendered.body).toContain('data-testid="person-top-employers-scroll"');
    expect(rendered.body).toContain("ACME CORP");
    expect(rendered.body).toContain("$600.00");
    expect(rendered.body).toContain("State University");
    expect(rendered.body).toContain("$200 and under");
    expect(rendered.body).toContain("Unitemized contributions are excluded from count and geography charts.");
    expect(rendered.body).toContain('<h4 id="person-outside-spending">Outside spending</h4>');
    expect(rendered.body).toContain('data-testid="person-outside-spending"');
    expect(rendered.body).toContain('aria-label="Zero-centered support and oppose spending comparison"');
    expect(rendered.body).not.toContain(["Finance", "chart:"].join(" "));
    expect(rendered.body).not.toContain(["Career", "total"].join(" "));

    const coreAttributesIndex = rendered.body.indexOf("<h3>Core attributes</h3>");
    const campaignFinanceIndex = rendered.body.indexOf("<h3>Campaign finance</h3>");
    const keyMetricsIndex = rendered.body.indexOf("<h3>Key metrics</h3>");
    const identifiersIndex = rendered.body.indexOf("<h3>Identifiers</h3>");
    const moneyAtGlanceIndex = rendered.body.indexOf("Money at a glance");
    const detailIndex = rendered.body.indexOf("<h4>Fundraising detail</h4>");
    const linkedCommitteesIndex = rendered.body.indexOf("<h4>Linked committees</h4>");
    const receiptsIndex = rendered.body.indexOf("Total receipts", moneyAtGlanceIndex);
    const disbursementsIndex = rendered.body.indexOf("Total disbursements", receiptsIndex);
    const cashOnHandIndex = rendered.body.indexOf("Cash on hand", disbursementsIndex);
    const debtsOwedIndex = rendered.body.indexOf("Debts owed by the committee", cashOnHandIndex);
    expect(coreAttributesIndex).toBeGreaterThan(-1);
    expect(campaignFinanceIndex).toBeGreaterThan(coreAttributesIndex);
    expect(keyMetricsIndex).toBeGreaterThan(campaignFinanceIndex);
    expect(identifiersIndex).toBeGreaterThan(keyMetricsIndex);
    expect(moneyAtGlanceIndex).toBeGreaterThan(campaignFinanceIndex);
    expect(receiptsIndex).toBeGreaterThan(moneyAtGlanceIndex);
    expect(disbursementsIndex).toBeGreaterThan(receiptsIndex);
    expect(cashOnHandIndex).toBeGreaterThan(disbursementsIndex);
    expect(debtsOwedIndex).toBeGreaterThan(cashOnHandIndex);
    expect(detailIndex).toBeGreaterThan(-1);
    expect(detailIndex).toBeGreaterThan(moneyAtGlanceIndex);
    expect(linkedCommitteesIndex).toBeGreaterThan(detailIndex);
  });

  it("renders finance-rich Money at a glance in non-script markup before deferred sections settle", () => {
    const rendered = render(DetailPage, {
      props: {
        data: buildPersonPageBundle({
          personMoneyHeadline: buildLoadedMoneyHeadline(),
          personFinanceSections: new Promise(() => {}),
          personContributionInsights: new Promise(() => {}),
          personTopDonors: new Promise(() => {}),
          personTopEmployers: new Promise(() => {})
        })
      }
    });

    expect(rendered.body).toContain("Jane Doe");
    expect(rendered.body).toContain("Money at a glance");
    expect(rendered.body).toContain("2026 cycle");
    expect(rendered.body).toContain("Coverage");
    expect(rendered.body).toContain("2025-01-01 to 2026-12-31");
    expect(rendered.body).toContain("Source");
    expect(rendered.body).toContain("Derived from itemized transactions");
    expect(rendered.body).toContain("Total receipts");
    expect(rendered.body).toContain("$1,000.00");
    expect(rendered.body).toContain("Total disbursements");
    expect(rendered.body).toContain("$600.00");
    expect(rendered.body).toContain("Cash on hand");
    expect(rendered.body).toContain("Not available");
    expect(rendered.body).toContain("Debts owed by the committee");
    expect(rendered.body).toContain("$45.00");
    expect(rendered.body).toContain('href="#person-outside-spending"');
    expect(rendered.body).toContain("Outside spending details");
    expect(rendered.body).toContain("Finance data loading");
    expect(rendered.body.match(/<h4>Money at a glance<\/h4>/g)).toHaveLength(1);
  });

  it("renders no-linked-candidacy headline copy without waiting for finance sections", () => {
    const rendered = render(DetailPage, {
      props: {
        data: buildPersonPageBundle({
          personMoneyHeadline: {
            kind: "no_linked_candidate",
            message: "No campaign-finance candidacies are linked yet."
          },
          personFinanceSections: new Promise(() => {})
        })
      }
    });

    expect(rendered.body).toContain("Jane Doe");
    expect(rendered.body).toContain("No campaign-finance candidacies are linked yet.");
    expect(rendered.body).toContain("Finance data loading");
  });

  it("renders missing-summary unavailable copy without fabricating zero headline values", () => {
    const rendered = render(DetailPage, {
      props: {
        data: buildPersonPageBundle({
          personMoneyHeadline: {
            kind: "missing_summary",
            message: "Selected-cycle money summary is not available yet.",
            selectedCycle: 2026
          },
          personFinanceSections: new Promise(() => {})
        })
      }
    });

    expect(rendered.body).toContain("Selected-cycle money summary is not available yet.");
    expect(rendered.body).toContain("2026 cycle");
    expect(rendered.body).not.toContain("<dd>$0.00</dd>");
    expect(rendered.body).not.toContain("Total receipts");
  });

  it("keeps identity and headline visible when a deferred non-headline section rejects", () => {
    const rendered = render(DetailPage, {
      props: {
        data: buildPersonPageBundle({
          personMoneyHeadline: buildLoadedMoneyHeadline(),
          personFinanceSections: asSettled([buildPersonFinanceSection()]),
          personContributionInsights: Promise.reject(new Error("insights unavailable"))
        })
      }
    });

    expect(rendered.body).toContain("Jane Doe");
    expect(rendered.body).toContain("Money at a glance");
    expect(rendered.body).toContain("Finance data loading");
  });

  it("renders selected-cycle money as page-wide content before candidate cards", () => {
    const source = readFileSync(new URL("./DetailPage.svelte", import.meta.url), "utf8");
    const financePanelIndex = source.indexOf('{:else if sectionKey === "person-campaign-finance"}');
    const financeSectionsThenIndex = source.indexOf("{:then personFinanceSections}", financePanelIndex);
    const moneyPresentationIndex = source.indexOf("{@render moneyAtGlance(", financeSectionsThenIndex);
    const candidateLoopIndex = source.indexOf("{#each personFinanceSections as section", financeSectionsThenIndex);

    expect(financePanelIndex).toBeGreaterThan(-1);
    expect(financeSectionsThenIndex).toBeGreaterThan(financePanelIndex);
    expect(moneyPresentationIndex).toBeGreaterThan(financeSectionsThenIndex);
    expect(moneyPresentationIndex).toBeLessThan(candidateLoopIndex);
    expect(source).not.toContain(["sectionIndex", "=== 0"].join(" "));
    expect(source).not.toContain("personFinanceSections[0].summary");

    const rendered = render(DetailPage, {
      props: {
        data: buildPersonPageBundle({
          personFinanceSections: asSettled([
            buildPersonFinanceSection(),
            buildPersonFinanceSection({
              candidate: {
                ...buildPersonFinanceSection().candidate,
                id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeee02",
                name: "Candidate Two",
                slug: "candidate-two"
              },
              summary: asSettled({
                ...SELECTED_CYCLE_FIELDS,
                candidate_id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeee02",
                candidate_name: "Candidate Two",
                total_raised: "2500.00",
                total_spent: "1200.00",
                net: "1300.00",
                transaction_count: 4,
                itemized_transaction_count: 4,
                cash_on_hand: "700.00",
                net_self_funding: "125.00",
                debts_owed_by_committee: "55.00",
                summary_source: "fec_weball" as const,
                receipt_source_composition: [
                  {
                    label: "Gross individual contributions",
                    total_amount: "2400.00",
                    source: "fec_committee_summary" as const
                  },
                  {
                    label: "PAC/other committee contributions",
                    total_amount: "100.00",
                    source: "fec_committee_summary" as const
                  }
                ],
                selected_cycle_coverage_complete: true,
                can_render_share: true,
                receipt_source_caveats: [],
                committees: []
              })
            })
          ])
        })
      }
    });
    const campaignFinanceIndex = rendered.body.indexOf("<h3>Campaign finance</h3>");
    const moneyAtGlanceIndex = rendered.body.indexOf("Money at a glance", campaignFinanceIndex);
    const firstCandidateCardIndex = rendered.body.indexOf("Candidate One", campaignFinanceIndex);

    expect(rendered.body.match(/<h4>Money at a glance<\/h4>/g)).toHaveLength(1);
    expect(rendered.body.match(/aria-label="Election cycle"/g)).toHaveLength(1);
    expect(moneyAtGlanceIndex).toBeGreaterThan(campaignFinanceIndex);
    expect(moneyAtGlanceIndex).toBeLessThan(firstCandidateCardIndex);
    const moneyAtGlanceBlock = rendered.body.slice(moneyAtGlanceIndex, firstCandidateCardIndex);
    expect(moneyAtGlanceBlock).toContain("$3,500.00");
    expect(moneyAtGlanceBlock).toContain("$1,800.00");
    expect(moneyAtGlanceBlock).toContain("Not available");
    expect(moneyAtGlanceBlock).toContain("$100.00");
    expect(moneyAtGlanceBlock).toContain("Mixed official FEC and derived summary data");
    expect(moneyAtGlanceBlock).not.toContain("$1,000.00");
  });

  it("keeps the campaign-finance panel heading unique while finance sections stream", () => {
    const rendered = render(DetailPage, {
      props: {
        data: buildPersonPageBundle({
          personFinanceSections: new Promise(() => {})
        })
      }
    });

    expect(rendered.body.split("<h3>Campaign finance</h3>").length - 1).toBe(1);
  });

  it("keeps the fundraising detail heading unique while contribution insights stream", () => {
    const rendered = render(DetailPage, {
      props: {
        data: buildPersonPageBundle({
          personFinanceSections: asSettled([buildPersonFinanceSection()]),
          personContributionInsights: new Promise(() => {})
        })
      }
    });

    expect(rendered.body.match(/<h[34]>Fundraising detail<\/h[34]>/g)).toHaveLength(1);
    expect(rendered.body).toContain("<h3>Finance data loading</h3>");
    expect(rendered.body).not.toContain("<h3>Fundraising detail loading</h3>");
  });

  it("renders ranked reported contributor names in total-desc order without replacing the donor/vendor feed", () => {
    const rendered = render(DetailPage, {
      props: {
        data: buildPersonPageBundle({
          personFinanceSections: asSettled([buildPersonFinanceSection()])
        })
      }
    });

    const topDonorsIndex = rendered.body.indexOf("<h5>Top reported contributor names</h5>");
    const largestDonorIndex = rendered.body.indexOf("Largest Person Donor", topDonorsIndex);
    const secondDonorIndex = rendered.body.indexOf("Second Person Donor", topDonorsIndex);
    const donorVendorIndex = rendered.body.indexOf("<h4>Donors and vendors</h4>");
    const chronologicalDonorIndex = rendered.body.indexOf("Acme Donor LLC", donorVendorIndex);

    expect(topDonorsIndex).toBeGreaterThan(-1);
    expect(largestDonorIndex).toBeGreaterThan(topDonorsIndex);
    expect(secondDonorIndex).toBeGreaterThan(largestDonorIndex);
    expect(rendered.body).toContain("<th>Reported contributor name</th><th>Total</th><th>Transactions</th>");
    expect(rendered.body).not.toContain(
      "<th>Reported contributor name</th><th>Total</th><th>Transactions</th><th>Transactions</th>"
    );
    expect(donorVendorIndex).toBeGreaterThan(topDonorsIndex);
    expect(chronologicalDonorIndex).toBeGreaterThan(donorVendorIndex);
  });

  it("renders ranked Top employers near reported contributor names without replacing the donor/vendor feed", () => {
    const rendered = render(DetailPage, {
      props: {
        data: buildPersonPageBundle({
          personFinanceSections: asSettled([buildPersonFinanceSection()])
        })
      }
    });

    const topDonorsIndex = rendered.body.indexOf("<h5>Top reported contributor names</h5>");
    const topEmployersIndex = rendered.body.indexOf("<h5>Top reported employer names</h5>", topDonorsIndex);
    const acmeIndex = rendered.body.indexOf("ACME CORP", topEmployersIndex);
    const universityIndex = rendered.body.indexOf("State University", topEmployersIndex);
    const donorVendorIndex = rendered.body.indexOf("<h4>Donors and vendors</h4>");
    const chronologicalDonorIndex = rendered.body.indexOf("Acme Donor LLC", donorVendorIndex);

    expect(topEmployersIndex).toBeGreaterThan(topDonorsIndex);
    expect(acmeIndex).toBeGreaterThan(topEmployersIndex);
    expect(universityIndex).toBeGreaterThan(acmeIndex);
    expect(rendered.body).toContain("<th>Employer</th><th>Total</th><th>Transactions</th>");
    const topEmployersTable = rendered.body.match(
      /data-testid="person-top-employers-scroll"[\s\S]*?<table>([\s\S]*?)<\/table>/
    )?.[1];
    expect(topEmployersTable).toBeDefined();
    expect(topEmployersTable?.match(/<thead>/g)).toHaveLength(1);
    expect(donorVendorIndex).toBeGreaterThan(topEmployersIndex);
    expect(chronologicalDonorIndex).toBeGreaterThan(donorVendorIndex);
  });

  it("renders no-itemized-data and no-ranked-donors empty states", () => {
    const rendered = render(DetailPage, {
      props: {
        data: buildPersonPageBundle({
          personFinanceSections: asSettled([buildPersonFinanceSection()]),
          personTopDonors: asSettled([]),
          personTopEmployers: asSettled([]),
          personContributionInsights: asSettled({
            ...CONTRIBUTION_INSIGHTS,
            cycle_totals: [],
            career_totals: {
              itemized_individual_contribution_amount: "0.00",
              itemized_transaction_count: 0,
              unitemized_individual_contribution_amount: "0.00",
              total_individual_contribution_amount: "0.00",
              source: "none"
            }
          })
        })
      }
    });

    expect(rendered.body).toContain("No itemized individual-contribution totals are available yet.");
    expect(rendered.body).toContain("No donor rankings available.");
    expect(rendered.body).toContain("No employer rankings available.");
  });

  it("renders person outside spending through the shared chart contract", () => {
    const rendered = render(DetailPage, {
      props: {
        data: buildPersonPageBundle({
          personFinanceSections: asSettled([buildPersonFinanceSection()])
        })
      }
    });

    const outsideSpendingIndex = rendered.body.indexOf('<h4 id="person-outside-spending">Outside spending</h4>');
    const chartIndex = rendered.body.indexOf('data-testid="person-outside-spending"', outsideSpendingIndex);
    const plotIndex = rendered.body.indexOf('data-testid="person-outside-spending-plot"', chartIndex);
    const supportIndex = rendered.body.indexOf("Support spending", plotIndex);
    const opposeIndex = rendered.body.indexOf("Oppose spending", plotIndex);
    const topSpendersIndex = rendered.body.indexOf("<h5>Top spenders</h5>", chartIndex);
    const spenderIndex = rendered.body.indexOf("Outside Group A", topSpendersIndex);

    expect(outsideSpendingIndex).toBeGreaterThan(-1);
    expect(chartIndex).toBeGreaterThan(outsideSpendingIndex);
    expect(plotIndex).toBeGreaterThan(chartIndex);
    expect(supportIndex).toBeGreaterThan(plotIndex);
    expect(opposeIndex).toBeGreaterThan(plotIndex);
    expect(rendered.body).toContain('data-zero-centered="true"');
    expect(rendered.body).toContain('data-domain-min="-1250"');
    expect(rendered.body).toContain('data-domain-max="1250"');
    expect(rendered.body).toContain("Outside spending reports $1,250.00 in support spending and $200.00 in oppose spending for the 2026 cycle.");
    expect(rendered.body).not.toContain("Outside spending chart: Candidate One");
    expect(topSpendersIndex).toBeGreaterThan(chartIndex);
    expect(spenderIndex).toBeGreaterThan(topSpendersIndex);
    expect(rendered.body).toContain("$1,250.00");
  });

  it("renders selected-cycle IE drilldown tables with committee and source filing links", () => {
    const rendered = render(DetailPage, {
      props: {
        data: buildPersonPageBundle({
          personFinanceSections: asSettled([buildPersonFinanceSection()])
        })
      }
    });

    const moneyAtGlanceIndex = rendered.body.indexOf("<h4>Money at a glance</h4>");
    const outsideSpendingIndex = rendered.body.indexOf('<h4 id="person-outside-spending">Outside spending</h4>');
    const topSpendersIndex = rendered.body.indexOf('data-testid="person-ie-top-spenders-scroll"', outsideSpendingIndex);
    const transactionsIndex = rendered.body.indexOf('data-testid="person-ie-transactions-scroll"', topSpendersIndex);

    expect(moneyAtGlanceIndex).toBeGreaterThan(-1);
    expect(rendered.body).toContain('href="#person-outside-spending"');
    expect(rendered.body).toContain("Outside spending details");
    expect(outsideSpendingIndex).toBeGreaterThan(moneyAtGlanceIndex);
    expect(topSpendersIndex).toBeGreaterThan(outsideSpendingIndex);
    expect(transactionsIndex).toBeGreaterThan(topSpendersIndex);
    expect(rendered.body).toContain("<th>Spender</th><th>Stance</th><th>Total</th><th>Expenditures</th>");
    expect(rendered.body).toContain(
      `<td><a href="/committee/${COMMITTEE_ID}">Outside Group A</a></td><td>Support</td><td>$1,250.00</td><td>1 expenditure</td>`
    );
    expect(rendered.body).toContain(
      "<th>Date</th><th>Spender</th><th>Stance</th><th>Amount</th><th>Dissemination date</th><th>Source</th>"
    );
    expect(rendered.body).toContain(`<a href="/v1/filings/${FILING_ID}">Source filing</a>`);
    expect(rendered.body).toContain(
      "Outside spending is independent and not controlled by the candidate committee."
    );
    expect(rendered.body).not.toContain("Red spending");
    expect(rendered.body).not.toContain("Blue spending");
    expect(rendered.body).not.toContain("coordination");
  });

  it("keeps one-sided outside spending centered on the shared symmetric scale", () => {
    const rendered = render(DetailPage, {
      props: {
        data: buildPersonPageBundle({
          personFinanceSections: asSettled([
            buildPersonFinanceSection({
              ieSummary: {
                ...SELECTED_CYCLE_FIELDS,
                candidate_id: CANDIDATE_ID,
                support_total: "1250.00",
                oppose_total: "0.00",
                support_count: 1,
                oppose_count: 0,
                excluded_outlier_count: 0,
                top_spenders: [
                  {
                    committee_id: COMMITTEE_ID,
                    committee_name: "Outside Group A",
                    support_oppose: "S",
                    total_amount: "1250.00",
                    transaction_count: 1
                  }
                ]
              },
              ieTransactions: asSettled([])
            })
          ])
        })
      }
    });

    expect(rendered.body).toContain('data-testid="person-outside-spending-plot"');
    expect(rendered.body).toContain('data-domain-min="-1250"');
    expect(rendered.body).toContain('data-domain-max="1250"');
    expect(rendered.body).toContain("Support spending");
    expect(rendered.body).toContain("Oppose spending");
  });

  it("keeps oppose-only outside spending centered on the shared symmetric scale", () => {
    const rendered = render(DetailPage, {
      props: {
        data: buildPersonPageBundle({
          personFinanceSections: asSettled([
            buildPersonFinanceSection({
              ieSummary: {
                ...SELECTED_CYCLE_FIELDS,
                candidate_id: CANDIDATE_ID,
                support_total: "0.00",
                oppose_total: "980.00",
                support_count: 0,
                oppose_count: 2,
                excluded_outlier_count: 0,
                top_spenders: [
                  {
                    committee_id: COMMITTEE_ID,
                    committee_name: "Outside Group A",
                    support_oppose: "O",
                    total_amount: "980.00",
                    transaction_count: 2
                  }
                ]
              },
              ieTransactions: asSettled([])
            })
          ])
        })
      }
    });

    expect(rendered.body).toContain('data-testid="person-outside-spending-plot"');
    expect(rendered.body).toContain('data-domain-min="-980"');
    expect(rendered.body).toContain('data-domain-max="980"');
    expect(rendered.body).toContain("Support spending");
    expect(rendered.body).toContain("Oppose spending");
  });

  it("suppresses the shared outside-spending plot for unavailable and all-zero states", () => {
    const emptyStates = [
      {
        label: "unavailable",
        ieSummary: null,
        expectedCopy:
          "Outside-spending data is not yet available for this candidate. Coverage may be incomplete."
      },
      {
        label: "all-zero",
        ieSummary: {
          ...SELECTED_CYCLE_FIELDS,
          candidate_id: CANDIDATE_ID,
          support_total: "0.00",
          oppose_total: "0.00",
          support_count: 0,
          oppose_count: 0,
          excluded_outlier_count: 0,
          top_spenders: []
        },
        expectedCopy:
          "No outside spending is reported in available filings. Coverage may be incomplete."
      }
    ];

    for (const state of emptyStates) {
      const rendered = render(DetailPage, {
        props: {
          data: buildPersonPageBundle({
            personFinanceSections: asSettled([
              buildPersonFinanceSection({
                candidate: {
                  ...buildPersonFinanceSection().candidate,
                  id: `${state.label}-${CANDIDATE_ID}`
                },
                ieSummary: state.ieSummary,
                ieTransactions: asSettled([])
              })
            ])
          })
        }
      });

      expect(rendered.body).toContain('<h4 id="person-outside-spending">Outside spending</h4>');
      expect(rendered.body).toContain(state.expectedCopy);
      expect(rendered.body).not.toContain('data-testid="person-outside-spending-plot"');
      expect(rendered.body).not.toContain("Outside spending chart: Candidate One");
      expect(rendered.body).toContain("Donors and vendors");
    }
  });

  it("keeps adjacent finance sections visible when outside-spending transactions reject", () => {
    const rendered = render(DetailPage, {
      props: {
        data: buildPersonPageBundle({
          personFinanceSections: asSettled([
            buildPersonFinanceSection({
              ieTransactions: Promise.reject(new Error("IE transactions unavailable"))
            })
          ])
        })
      }
    });

    expect(rendered.body).toContain("Friends of Candidate One");
    expect(rendered.body).toContain("Acme Donor LLC");
    expect(rendered.body).toContain('<h4 id="person-outside-spending">Outside spending</h4>');
    expect(rendered.body).toContain('<section class="skeleton-panel" aria-label="Outside spending" aria-busy="true">');
    expect(rendered.body).not.toContain('data-testid="person-outside-spending-plot"');
  });

  it("renders contribution-insights caveat states without hiding adjacent finance sections", () => {
    const insightStates = [
      {
        key: "missing_committee_summary",
        message:
          "Committee summary totals are unavailable, so summary-backed unitemized dollars are not included.",
        hasData: true,
        caveats: ["missing_committee_summary"],
        excludedGeography: null
      },
      {
        key: "itemized_summary_reconciliation_unavailable",
        message:
          "Itemized totals cannot be reconciled to committee summary totals, so this view uses itemized-only contribution facts.",
        hasData: true,
        caveats: ["itemized_summary_reconciliation_unavailable"],
        excludedGeography: null
      },
      {
        key: "itemized_summary_reconciliation_mismatch",
        message:
          "Itemized totals do not match committee summary totals, so this view uses itemized-only contribution facts.",
        hasData: true,
        caveats: ["itemized_summary_reconciliation_mismatch"],
        excludedGeography: null
      },
      {
        key: "missing_zcta_district",
        message: "District geography is unavailable until ZCTA district reference data is loaded.",
        hasData: false,
        caveats: ["missing_zcta_district"],
        excludedGeography: null
      },
      {
        key: "statewide_office",
        message: "Statewide offices use state-level fundraising geography.",
        hasData: true,
        caveats: [],
        excludedGeography: "statewide_office"
      },
      {
        key: "federal_executive",
        message: "Federal executive offices use national fundraising geography.",
        hasData: true,
        caveats: [],
        excludedGeography: "federal_executive"
      }
    ];

    for (const state of insightStates) {
      const data = buildPersonPageBundle({
        personContributionInsights: asSettled({
          ...CONTRIBUTION_INSIGHTS,
          has_data: state.hasData,
          metadata: {
            ...CONTRIBUTION_INSIGHTS.metadata,
            caveats: state.caveats,
            excluded_geography: state.excludedGeography
          },
          geography: { ...CONTRIBUTION_INSIGHTS.geography, by_district: [] }
        }),
        personFinanceSections: asSettled([
          buildPersonFinanceSection({
            candidate: {
              ...buildPersonFinanceSection().candidate,
              id: `${state.key}-candidate`,
              name: "Candidate One"
            }
          })
        ])
      });

      const rendered = render(DetailPage, { props: { data } });

      expect(rendered.body).toContain(state.message);
      expect(rendered.body).not.toContain("statewide_office");
      expect(rendered.body).not.toContain("federal_executive");
      expect(rendered.body).not.toContain("no_linked_candidate");
      if (state.key === "missing_committee_summary") {
        expect(rendered.body).toContain("Itemized contribution-size buckets");
        expect(rendered.body).not.toContain(
          "Committee summary totals are required before dollars by size can be shown."
        );
      }
      expect(rendered.body).toContain("Jane Doe");
      expect(rendered.body).toContain("Friends of Candidate One");
      expect(rendered.body).toContain("Acme Donor LLC");
      expect(rendered.body).toContain('<h4 id="person-outside-spending">Outside spending</h4>');
    }
  });

  it("renders no-linked-candidate contribution insights on the real empty-candidate path", () => {
    const rendered = render(DetailPage, {
      props: {
        data: buildPersonPageBundle({
          personFinanceSections: asSettled([]),
          personContributionInsights: asSettled({
            ...CONTRIBUTION_INSIGHTS,
            has_data: false,
            metadata: {
              ...CONTRIBUTION_INSIGHTS.metadata,
              committee_count: 0,
              excluded_geography: "no_linked_candidate"
            },
            monthly_totals: [],
            itemized_size_buckets: [],
            dollars_by_size: [],
            cycle_totals: [],
            career_totals: {
              itemized_individual_contribution_amount: "0.00",
              itemized_transaction_count: 0,
              unitemized_individual_contribution_amount: "0.00",
              total_individual_contribution_amount: "0.00",
              source: "none"
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
              geography_mode: "excluded" as const,
              classified_amount: "0.00",
              classified_transaction_count: 0,
              unknown_amount: "0.00",
              unknown_transaction_count: 0
            },
            small_dollar_share: {
              small_dollar_amount: null,
              total_contribution_amount: null,
              share: null,
              available: false
            }
          })
        })
      }
    });

    expect(rendered.body).toContain("<h3>Campaign finance</h3>");
    expect(rendered.body).toContain("<h4>Fundraising detail</h4>");
    expect(rendered.body).toContain("No linked candidate is available for fundraising detail.");
    expect(rendered.body).toContain("No campaign-finance candidacies are linked yet.");
    expect(rendered.body).toContain("Jane Doe");
    expect(rendered.body).not.toContain("Candidate One");
  });

  it("renders person-scoped contribution insights once without candidate-specific chart labels", () => {
    const rendered = render(DetailPage, {
      props: {
        data: buildPersonPageBundle({
          personFinanceSections: asSettled([
            buildPersonFinanceSection(),
            buildPersonFinanceSection({
              candidate: {
                ...buildPersonFinanceSection().candidate,
                id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeee02",
                name: "Candidate Two",
                slug: "candidate-two"
              }
            })
          ])
        })
      }
    });

    expect(rendered.body).toContain("Candidate One");
    expect(rendered.body).toContain("Candidate Two");
    expect(rendered.body.match(/<h4>Fundraising detail<\/h4>/g)).toHaveLength(1);
    expect(rendered.body).toContain("Itemized individual contributions by month");
    expect(rendered.body).toContain("Itemized contribution-size buckets");
    expect(rendered.body).toContain("Geography");
    expect(rendered.body).not.toContain("Donations over time for Candidate One");
    expect(rendered.body).not.toContain("Donations over time for Candidate Two");
  });

  it("keeps the person-scoped contribution-insights stream available while linked-candidate sections resolve", () => {
    const source = readFileSync(new URL("./DetailPage.svelte", import.meta.url), "utf8");
    const financePanelIndex = source.indexOf('{:else if sectionKey === "person-campaign-finance"}');
    const financeSectionsAwaitIndex = source.indexOf("{#await personFinanceSections}", financePanelIndex);
    const pendingFundraisingDetailIndex = source.indexOf(
      "{@render fundraisingDetail()}",
      financeSectionsAwaitIndex
    );
    const financeSectionsThenIndex = source.indexOf(
      "{:then personFinanceSections}",
      financeSectionsAwaitIndex
    );

    expect(financePanelIndex).toBeGreaterThan(-1);
    expect(financeSectionsAwaitIndex).toBeGreaterThan(financePanelIndex);
    expect(pendingFundraisingDetailIndex).toBeGreaterThan(financeSectionsAwaitIndex);
    expect(pendingFundraisingDetailIndex).toBeLessThan(financeSectionsThenIndex);
  });

  it("keeps person-scoped contribution insights visible when candidate summary rejects", () => {
    const source = readFileSync(new URL("./DetailPage.svelte", import.meta.url), "utf8");
    const financePanelIndex = source.indexOf('{:else if sectionKey === "person-campaign-finance"}');
    const financeSectionsThenIndex = source.indexOf("{:then personFinanceSections}", financePanelIndex);
    const fundraisingDetailIndex = source.indexOf("{@render fundraisingDetail()}", financeSectionsThenIndex);
    const candidateLoopIndex = source.indexOf("{#each personFinanceSections as section", financeSectionsThenIndex);
    const summaryAwaitIndex = source.indexOf("{#await buildMoneyAtGlanceSummary(sections)}");
    const summaryCatchIndex = source.indexOf("{:catch}", summaryAwaitIndex);
    const selectedCycleSummaryUnavailableIndex = source.indexOf(
      "Selected-cycle money summary is temporarily unavailable.",
      summaryCatchIndex
    );
    const linkedCommitteesIndex = source.indexOf("<h4>Linked committees</h4>", summaryCatchIndex);

    expect(financePanelIndex).toBeGreaterThan(-1);
    expect(fundraisingDetailIndex).toBeGreaterThan(financeSectionsThenIndex);
    expect(fundraisingDetailIndex).toBeLessThan(candidateLoopIndex);
    expect(summaryAwaitIndex).toBeGreaterThan(-1);
    expect(summaryCatchIndex).toBeGreaterThan(summaryAwaitIndex);
    expect(selectedCycleSummaryUnavailableIndex).toBeGreaterThan(summaryCatchIndex);
    expect(linkedCommitteesIndex).toBeGreaterThan(summaryCatchIndex);

    const data = buildPersonPageBundle({
      personFinanceSections: asSettled([
        buildPersonFinanceSection({
          summary: Promise.reject(new Error("summary unavailable"))
        })
      ])
    });

    const rendered = render(DetailPage, { props: { data } });
    const fundraisingDetailIndexInBody = rendered.body.indexOf("<h4>Fundraising detail</h4>");
    const linkedCommitteesIndexInBody = rendered.body.indexOf("<h4>Linked committees</h4>");

    expect(rendered.body).toContain("<h4>Fundraising detail</h4>");
    expect(rendered.body).toContain("100%");
    expect(rendered.body).toContain("Candidate One");
    expect(rendered.body).toContain("Acme Donor LLC");
    expect(rendered.body).toContain('<h4 id="person-outside-spending">Outside spending</h4>');
    expect(linkedCommitteesIndexInBody).toBeGreaterThan(fundraisingDetailIndexInBody);
  });

  it("keeps person-scoped contribution insights visible while candidate sections are pending or rejected", () => {
    const source = readFileSync(new URL("./DetailPage.svelte", import.meta.url), "utf8");
    const financeSectionsAwaitIndex = source.indexOf("{#await personFinanceSections}");
    const financeSectionsCatchIndex = source.indexOf("{:catch}", financeSectionsAwaitIndex);
    const catchFundraisingDetailIndex = source.indexOf(
      "{@render fundraisingDetail()}",
      financeSectionsCatchIndex
    );
    const sectionsUnavailableIndex = source.indexOf(
      "Campaign-finance sections are temporarily unavailable.",
      catchFundraisingDetailIndex
    );

    expect(financeSectionsAwaitIndex).toBeGreaterThan(-1);
    expect(financeSectionsCatchIndex).toBeGreaterThan(financeSectionsAwaitIndex);
    expect(catchFundraisingDetailIndex).toBeGreaterThan(financeSectionsCatchIndex);
    expect(sectionsUnavailableIndex).toBeGreaterThan(catchFundraisingDetailIndex);

    const data = buildPersonPageBundle({
      personFinanceSections: Promise.reject(new Error("sections unavailable"))
    });

    const rendered = render(DetailPage, { props: { data } });

    expect(rendered.body).toContain("Jane Doe");
    expect(rendered.body).toContain("<h4>Fundraising detail</h4>");
    expect(rendered.body).toContain("100%");
  });

  it("keeps identity and adjacent finance sections visible when contribution insights reject", () => {
    const source = readFileSync(new URL("./DetailPage.svelte", import.meta.url), "utf8");
    const insightsAwaitIndex = source.indexOf(
      "{#await combineDeferredTriple(personContributionInsights, personTopDonors, personTopEmployers)}"
    );
    const insightsFallbackIndex = source.indexOf("Contribution insights are temporarily unavailable.");
    const linkedCommitteesIndex = source.indexOf("<h4>Linked committees</h4>", insightsFallbackIndex);

    expect(insightsAwaitIndex).toBeGreaterThan(-1);
    expect(insightsFallbackIndex).toBeGreaterThan(insightsAwaitIndex);
    expect(linkedCommitteesIndex).toBeGreaterThan(insightsFallbackIndex);

    const data = buildPersonPageBundle({
      personContributionInsights: Promise.reject(new Error("insights unavailable")),
      personFinanceSections: asSettled([buildPersonFinanceSection()])
    });

    const rendered = render(DetailPage, { props: { data } });

    expect(rendered.body).toContain("Jane Doe");
    expect(rendered.body).toContain("Candidate One");
    expect(rendered.body).toContain("Friends of Candidate One");
    expect(rendered.body).toContain("Acme Donor LLC");
    expect(rendered.body).toContain('<h4 id="person-outside-spending">Outside spending</h4>');
  });

  it("encodes person finance candidate hrefs with the shared route builder", () => {
    const data = buildPersonPageBundle({
      personFinanceSections: asSettled([
        buildPersonFinanceSection({
          candidate: {
            id: CANDIDATE_ID,
            fec_candidate_id: "H0NC01001",
            name: "Candidate One",
            slug: "a/b",
            slug_is_unique: true,
            person_id: PERSON_ID,
            party: "DEM",
            office: "H",
            state: "NC",
            district: "01",
            incumbent_challenge: "I",
            principal_committee_id: COMMITTEE_ID,
            sources: []
          }
        })
      ])
    });

    const rendered = render(DetailPage, { props: { data } });

    expect(rendered.body).toContain('href="/candidate/a%2Fb"');
    expect(rendered.body).not.toContain('href="/candidate/a/b"');
  });

  it("renders explicit person empty-state copy and portrait fallback when person data is missing", () => {
    const data = buildPersonPageBundle({
      detail: {
        id: PERSON_ID,
        canonical_name: "Jane Doe",
        name_variants: [],
        first_name: "Jane",
        middle_name: null,
        last_name: "Doe",
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
        sources: []
      },
      personFinanceSections: asSettled([buildPersonFinanceSection({
        summary: asSettled({
          ...SELECTED_CYCLE_FIELDS,
          candidate_id: CANDIDATE_ID,
          candidate_name: "Candidate One",
          total_raised: "0.00",
          total_spent: "0.00",
          net: "0.00",
          transaction_count: 0,
          itemized_transaction_count: 0,
          cash_on_hand: null,
          net_self_funding: null,
          summary_source: "derived" as const,
          receipt_source_composition: [],
          selected_cycle_coverage_complete: false,
          can_render_share: false,
          receipt_source_caveats: [],
          committees: []
        }),
        donorVendorTransactions: asSettled([]),
        ieSummary: null,
        ieTransactions: asSettled([])
      })])
    });

    const rendered = render(DetailPage, { props: { data } });

    expect(rendered.body).toContain('data-testid="entity-portrait-initials"');
    expect(rendered.body).toContain("Initials avatar for Jane Doe");
    expect(rendered.body).toContain("No linked committee summaries are available yet.");
    expect(rendered.body).toContain("No donor/vendor transactions are available yet.");
    expect(rendered.body).toContain('<h4 id="person-outside-spending">Outside spending</h4>');
  });

  it("renders both empty-state banners when linked committees and donor/vendor transactions are absent", () => {
    const data = buildPersonPageBundle({
      personFinanceSections: asSettled([buildPersonFinanceSection({
        summary: asSettled({
          ...SELECTED_CYCLE_FIELDS,
          candidate_id: CANDIDATE_ID,
          candidate_name: "Candidate One",
          total_raised: "0.00",
          total_spent: "0.00",
          net: "0.00",
          transaction_count: 0,
          itemized_transaction_count: 0,
          cash_on_hand: null,
          net_self_funding: null,
          summary_source: "derived" as const,
          receipt_source_composition: [],
          selected_cycle_coverage_complete: false,
          can_render_share: false,
          receipt_source_caveats: [],
          committees: []
        }),
        donorVendorTransactions: asSettled([])
      })])
    });

    const rendered = render(DetailPage, { props: { data } });

    expect(rendered.body).toContain("No linked committee summaries are available yet.");
    expect(rendered.body).toContain("No donor/vendor transactions are available yet.");
  });

  it("renders only the zero-transactions Stage 6 banner when linked committees exist", () => {
    const data = buildPersonPageBundle({
      personFinanceSections: asSettled([buildPersonFinanceSection({
        donorVendorTransactions: asSettled([])
      })])
    });

    const rendered = render(DetailPage, { props: { data } });

    expect(rendered.body).toContain("No donor/vendor transactions are available yet.");
    expect(rendered.body).not.toContain("No linked committee summaries are available yet.");
  });

  it("does not render a Stage 6 empty-state banner when linked committees and transactions exist", () => {
    const data = buildPersonPageBundle({
      personFinanceSections: asSettled([buildPersonFinanceSection()])
    });

    const rendered = render(DetailPage, { props: { data } });

    expect(rendered.body).not.toContain("No linked committee summaries are available yet.");
    expect(rendered.body).not.toContain("No donor/vendor transactions are available yet.");
  });

  it("renders donor/vendor await as a sibling of summary await so the two failures stay isolated", () => {
    // A nested donor/vendor await would couple the two sections: a summary
    // rejection would hide the donor/vendor section entirely and skeletons
    // would render sequentially instead of in parallel.
    const source = readFileSync(new URL("./DetailPage.svelte", import.meta.url), "utf8");
    const personFinanceStart = source.indexOf('{:else if sectionKey === "person-campaign-finance"}');
    expect(personFinanceStart).toBeGreaterThan(-1);

    const personFinanceSlice = source.slice(personFinanceStart);
    const linkedCommitteesIndex = personFinanceSlice.indexOf("<h4>Linked committees</h4>");
    const summaryAwaitIndex = personFinanceSlice.indexOf("{#await section.summary}", linkedCommitteesIndex);
    const summaryCatchIndex = personFinanceSlice.indexOf(
      "Linked committees are temporarily unavailable.",
      summaryAwaitIndex
    );
    const summaryAwaitEndIndex = personFinanceSlice.indexOf("{/await}", summaryCatchIndex);
    const donorVendorAwaitIndex = personFinanceSlice.indexOf("{#await section.donorVendorTransactions}");

    expect(summaryAwaitIndex).toBeGreaterThan(-1);
    expect(summaryCatchIndex).toBeGreaterThan(summaryAwaitIndex);
    expect(summaryAwaitEndIndex).toBeGreaterThan(summaryCatchIndex);
    expect(donorVendorAwaitIndex).toBeGreaterThan(summaryAwaitEndIndex);
  });

  it("resolves outside-spending summary and transactions in the same awaited slice", () => {
    const source = readFileSync(new URL("./DetailPage.svelte", import.meta.url), "utf8");
    const personFinanceStart = source.indexOf('{:else if sectionKey === "person-campaign-finance"}');
    expect(personFinanceStart).toBeGreaterThan(-1);

    const personFinanceSlice = source.slice(personFinanceStart);
    const outsideSpendingIndex = personFinanceSlice.indexOf('<h4 id="person-outside-spending">Outside spending</h4>');
    const combinedAwaitIndex = personFinanceSlice.indexOf(
      "{#await combineDeferredPair(section.ieSummary, section.ieTransactions)}",
      outsideSpendingIndex
    );
    const combinedThenIndex = personFinanceSlice.indexOf("{:then [ieSummary, ieTransactions]}", combinedAwaitIndex);
    const outsideSpendingBuildIndex = personFinanceSlice.indexOf(
      "buildPersonOutsideSpendingSection(ieSummary, ieTransactions)",
      combinedThenIndex
    );

    expect(outsideSpendingIndex).toBeGreaterThan(-1);
    expect(combinedAwaitIndex).toBeGreaterThan(outsideSpendingIndex);
    expect(combinedThenIndex).toBeGreaterThan(combinedAwaitIndex);
    expect(outsideSpendingBuildIndex).toBeGreaterThan(combinedThenIndex);
    expect(personFinanceSlice).not.toContain("{#await section.ieSummary}");
  });
});
