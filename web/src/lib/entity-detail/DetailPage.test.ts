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

const CONTRIBUTION_INSIGHTS = {
  person_id: PERSON_ID,
  has_data: true,
  metadata: {
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
      label: "$1-$199",
      min_amount: "1.00",
      max_amount: "199.99",
      total_amount: "100.00",
      transaction_count: 1
    }
  ],
  dollars_by_size: [
    { label: "Unitemized (<$200)", total_amount: "125.00", source: "committee_summary" as const },
    { label: "$1-$199", total_amount: "100.00", source: "transactions" as const }
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
    }
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
      candidate_id: CANDIDATE_ID,
      candidate_name: "Candidate One",
      total_raised: "1000.00",
      total_spent: "600.00",
      net: "400.00",
      transaction_count: 3,
      itemized_transaction_count: 3,
      cash_on_hand: null,
      summary_source: "derived" as const,
      committees: [
        {
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
          summary_source: "derived" as const
        }
      ]
    }),
    ieTransactions: asSettled([
      {
        id: "ie-1",
        filing_id: null,
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
    expect(rendered.body).toContain("Total raised");
    expect(rendered.body).toContain("$1,000.00");
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
    expect(rendered.body).toContain("Career");
    expect(rendered.body).toContain(
      "Totals combine itemized transactions with available committee-summary data; unitemized coverage may be incomplete."
    );
    expect(rendered.body).toContain("Donations over time");
    expect(rendered.body).toContain("Donation count by size bucket");
    expect(rendered.body).toContain("Dollars by size bucket");
    expect(rendered.body).toContain("Fundraising geography");
    expect(rendered.body).toContain("District share");
    expect(rendered.body).toContain("100% in district");
    expect(rendered.body).toContain("$100.00 in district and $0.00 out of district.");
    expect(rendered.body).toContain("<h5>Top donors</h5>");
    expect(rendered.body).toContain("Largest Person Donor");
    expect(rendered.body).toContain("$500.00");
    expect(rendered.body).toContain("Second Person Donor");
    expect(rendered.body).toContain("<h5>Top employers</h5>");
    expect(rendered.body).toContain("Top employers aggregate raw employer names from itemized individual contributions only.");
    expect(rendered.body).toContain("They are not industry- or sector-coded; see Methodology for source-linking and evidence limitations.");
    expect(rendered.body).toContain('data-testid="person-top-employers-scroll"');
    expect(rendered.body).toContain("ACME CORP");
    expect(rendered.body).toContain("$600.00");
    expect(rendered.body).toContain("State University");
    expect(rendered.body).toContain("Unitemized (&lt;$200)");
    expect(rendered.body).toContain("Unitemized contributions are excluded from count and geography charts.");
    expect(rendered.body).toContain("<h4>Outside Spending</h4>");
    expect(rendered.body).toContain('aria-label="Outside spending chart for Candidate One"');
    expect(rendered.body).toContain("Finance chart: Candidate One");

    const summaryChartIndex = rendered.body.indexOf("Finance chart: Candidate One");
    const detailIndex = rendered.body.indexOf("<h4>Fundraising detail</h4>");
    const linkedCommitteesIndex = rendered.body.indexOf("<h4>Linked committees</h4>");
    expect(detailIndex).toBeGreaterThan(-1);
    expect(detailIndex).toBeGreaterThan(summaryChartIndex);
    expect(linkedCommitteesIndex).toBeGreaterThan(detailIndex);
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

  it("renders ranked Top donors in total-desc order without replacing the donor/vendor feed", () => {
    const rendered = render(DetailPage, {
      props: {
        data: buildPersonPageBundle({
          personFinanceSections: asSettled([buildPersonFinanceSection()])
        })
      }
    });

    const topDonorsIndex = rendered.body.indexOf("<h5>Top donors</h5>");
    const largestDonorIndex = rendered.body.indexOf("Largest Person Donor", topDonorsIndex);
    const secondDonorIndex = rendered.body.indexOf("Second Person Donor", topDonorsIndex);
    const donorVendorIndex = rendered.body.indexOf("<h4>Donors and vendors</h4>");
    const chronologicalDonorIndex = rendered.body.indexOf("Acme Donor LLC", donorVendorIndex);

    expect(topDonorsIndex).toBeGreaterThan(-1);
    expect(largestDonorIndex).toBeGreaterThan(topDonorsIndex);
    expect(secondDonorIndex).toBeGreaterThan(largestDonorIndex);
    expect(rendered.body).toContain("<th>Donor</th><th>Total</th><th>Transactions</th>");
    expect(rendered.body).not.toContain(
      "<th>Donor</th><th>Total</th><th>Transactions</th><th>Transactions</th>"
    );
    expect(donorVendorIndex).toBeGreaterThan(topDonorsIndex);
    expect(chronologicalDonorIndex).toBeGreaterThan(donorVendorIndex);
  });

  it("renders ranked Top employers near Top donors without replacing the donor/vendor feed", () => {
    const rendered = render(DetailPage, {
      props: {
        data: buildPersonPageBundle({
          personFinanceSections: asSettled([buildPersonFinanceSection()])
        })
      }
    });

    const topDonorsIndex = rendered.body.indexOf("<h5>Top donors</h5>");
    const topEmployersIndex = rendered.body.indexOf("<h5>Top employers</h5>", topDonorsIndex);
    const acmeIndex = rendered.body.indexOf("ACME CORP", topEmployersIndex);
    const universityIndex = rendered.body.indexOf("State University", topEmployersIndex);
    const donorVendorIndex = rendered.body.indexOf("<h4>Donors and vendors</h4>");
    const chronologicalDonorIndex = rendered.body.indexOf("Acme Donor LLC", donorVendorIndex);

    expect(topEmployersIndex).toBeGreaterThan(topDonorsIndex);
    expect(acmeIndex).toBeGreaterThan(topEmployersIndex);
    expect(universityIndex).toBeGreaterThan(acmeIndex);
    expect(rendered.body).toContain("<th>Employer</th><th>Total</th><th>Transactions</th>");
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

  it("renders IE Top spenders inside the existing Outside Spending block", () => {
    const rendered = render(DetailPage, {
      props: {
        data: buildPersonPageBundle({
          personFinanceSections: asSettled([buildPersonFinanceSection()])
        })
      }
    });

    const outsideSpendingIndex = rendered.body.indexOf("<h4>Outside Spending</h4>");
    const topSpendersIndex = rendered.body.indexOf("<h5>Top spenders</h5>", outsideSpendingIndex);
    const spenderIndex = rendered.body.indexOf("Outside Group A", topSpendersIndex);

    expect(outsideSpendingIndex).toBeGreaterThan(-1);
    expect(topSpendersIndex).toBeGreaterThan(outsideSpendingIndex);
    expect(spenderIndex).toBeGreaterThan(topSpendersIndex);
    expect(rendered.body).toContain("$1,250.00");
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
        expect(rendered.body).toContain("Dollars by size bucket");
        expect(rendered.body).not.toContain(
          "Committee summary totals are required before dollars by size can be shown."
        );
      }
      expect(rendered.body).toContain("Jane Doe");
      expect(rendered.body).toContain("Friends of Candidate One");
      expect(rendered.body).toContain("Acme Donor LLC");
      expect(rendered.body).toContain("<h4>Outside Spending</h4>");
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
              }
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
    expect(rendered.body).toContain('aria-label="Donations over time for Jane Doe"');
    expect(rendered.body).toContain('aria-label="Donation count by size bucket for Jane Doe"');
    expect(rendered.body).toContain('aria-label="Dollars by size bucket for Jane Doe"');
    expect(rendered.body).toContain('aria-label="Fundraising geography for Jane Doe"');
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

  it("keeps person-scoped contribution insights between candidate summary and linked committees when the summary rejects", () => {
    const source = readFileSync(new URL("./DetailPage.svelte", import.meta.url), "utf8");
    const financePanelIndex = source.indexOf('{:else if sectionKey === "person-campaign-finance"}');
    const summaryAwaitIndex = source.indexOf("{#await section.summary}");
    const summaryCatchIndex = source.indexOf("{:catch}", summaryAwaitIndex);
    const summaryAwaitCloseIndex = source.indexOf("{/await}", summaryCatchIndex);
    const fundraisingDetailIndex = source.indexOf(
      "{@render fundraisingDetail()}",
      summaryAwaitCloseIndex
    );
    const linkedCommitteesIndex = source.indexOf("<h4>Linked committees</h4>", fundraisingDetailIndex);

    expect(financePanelIndex).toBeGreaterThan(-1);
    expect(summaryAwaitIndex).toBeGreaterThan(-1);
    expect(summaryCatchIndex).toBeGreaterThan(summaryAwaitIndex);
    expect(summaryAwaitCloseIndex).toBeGreaterThan(summaryCatchIndex);
    expect(fundraisingDetailIndex).toBeGreaterThan(summaryAwaitCloseIndex);
    expect(linkedCommitteesIndex).toBeGreaterThan(fundraisingDetailIndex);

    const data = buildPersonPageBundle({
      personFinanceSections: asSettled([
        buildPersonFinanceSection({
          summary: Promise.reject(new Error("summary unavailable"))
        })
      ])
    });

    const rendered = render(DetailPage, { props: { data } });
    const summaryUnavailableIndex = rendered.body.indexOf(
      "Candidate fundraising summary is temporarily unavailable."
    );
    const fundraisingDetailIndexInBody = rendered.body.indexOf("<h4>Fundraising detail</h4>");
    const linkedCommitteesIndexInBody = rendered.body.indexOf("<h4>Linked committees</h4>");

    expect(rendered.body).toContain("<h4>Fundraising detail</h4>");
    expect(rendered.body).toContain("100%");
    expect(rendered.body).toContain("Candidate One");
    expect(rendered.body).toContain("Acme Donor LLC");
    expect(rendered.body).toContain("<h4>Outside Spending</h4>");
    expect(fundraisingDetailIndexInBody).toBeGreaterThan(summaryUnavailableIndex);
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
    expect(rendered.body).toContain("<h4>Outside Spending</h4>");
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
          candidate_id: CANDIDATE_ID,
          candidate_name: "Candidate One",
          total_raised: "0.00",
          total_spent: "0.00",
          net: "0.00",
          transaction_count: 0,
          itemized_transaction_count: 0,
          cash_on_hand: null,
          summary_source: "derived" as const,
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
    expect(rendered.body).toContain("<h4>Outside Spending</h4>");
  });

  it("renders both empty-state banners when linked committees and donor/vendor transactions are absent", () => {
    const data = buildPersonPageBundle({
      personFinanceSections: asSettled([buildPersonFinanceSection({
        summary: asSettled({
          candidate_id: CANDIDATE_ID,
          candidate_name: "Candidate One",
          total_raised: "0.00",
          total_spent: "0.00",
          net: "0.00",
          transaction_count: 0,
          itemized_transaction_count: 0,
          cash_on_hand: null,
          summary_source: "derived" as const,
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
    const summaryAwaitIndex = personFinanceSlice.indexOf("{#await section.summary}");
    const summaryCatchIndex = personFinanceSlice.indexOf("Candidate fundraising summary is temporarily unavailable.");
    const summaryAwaitEndIndex = personFinanceSlice.indexOf("{/await}", summaryCatchIndex);
    const donorVendorAwaitIndex = personFinanceSlice.indexOf("{#await section.donorVendorTransactions}");

    expect(summaryAwaitIndex).toBeGreaterThan(-1);
    expect(summaryCatchIndex).toBeGreaterThan(summaryAwaitIndex);
    expect(summaryAwaitEndIndex).toBeGreaterThan(summaryCatchIndex);
    expect(donorVendorAwaitIndex).toBeGreaterThan(summaryAwaitEndIndex);
  });
});
