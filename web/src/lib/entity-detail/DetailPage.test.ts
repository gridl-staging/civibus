import { readFileSync } from "node:fs";
import { render } from "svelte/server";
import { describe, expect, it, vi } from "vitest";
import type { PersonCandidateFinanceSection } from "$lib/server/api/campaign-finance-detail";
import type { EntityDetailPageBundle } from "$lib/server/api/entity-detail";
import DetailPage from "./DetailPage.svelte";
import { buildPersonDetailFixture } from "./detail_page_test_fixtures";

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
const POPULATED_CANDIDATE_MONEY_COVERAGE = {
  activity_state: "populated" as const,
  completeness: "complete" as const,
  basis: "qualifying_transactions" as const
};
const POPULATED_SCHEDULE_E_COVERAGE = {
  activity_state: "populated" as const,
  completeness: "complete" as const,
  basis: "fec_schedule_e_transactions" as const
};
const LOADED_ZERO_CANDIDATE_MONEY_COVERAGE = {
  activity_state: "loaded_zero" as const,
  completeness: "complete" as const,
  basis: "authoritative_load_evidence" as const
};
const LOADED_ZERO_SCHEDULE_E_COVERAGE = {
  activity_state: "loaded_zero" as const,
  completeness: "complete" as const,
  basis: "authoritative_load_evidence" as const
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
  {
    employer: "ACME CORP",
    total_amount: "600.00",
    transaction_count: 3,
    industry: "Technology",
    industry_rollup_eligible: true
  },
  {
    employer: "State University",
    total_amount: "150.00",
    transaction_count: 1,
    industry: "UNKNOWN_INDUSTRY",
    industry_rollup_eligible: true
  },
  {
    employer: "Legacy employer bucket",
    total_amount: "25.00",
    transaction_count: 1,
    industry: "UNKNOWN_INDUSTRY",
    industry_rollup_eligible: false
  }
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
      coverage: POPULATED_CANDIDATE_MONEY_COVERAGE,
      out_of_cycle_official_total: null,
      committees: []
    }
  };
}

/**
 * The `not_loaded` headline arm carries no summary at all — that is the point.
 * The backend's zero-valued money fields never reach the presentation layer.
 */
function buildNotLoadedMoneyHeadline() {
  return {
    kind: "not_loaded" as const,
    message:
      "A linked FEC candidate exists for this person, but Civibus has not loaded authoritative selected-cycle fundraising evidence for that candidate.",
    selectedCycle: 2026,
    // The summary carries available_cycles, which is what the cycle switcher is
    // built from. It is deliberately NOT used for any figure in this arm.
    summary: buildLoadedMoneyHeadline().summary
  };
}

/**
 * Genuine no-money coverage. Same zero money strings as the not-loaded payload, but
 * the discriminator proves the loader ran, so these zeroes are facts that must render.
 */
function buildLoadedZeroMoneyHeadline() {
  return {
    kind: "loaded" as const,
    summary: {
      ...buildLoadedMoneyHeadline().summary,
      total_raised: "0.00",
      total_spent: "0.00",
      net: "0.00",
      transaction_count: 0,
      itemized_transaction_count: 0,
      cash_on_hand: "0.00",
      net_self_funding: null,
      debts_owed_by_committee: "0.00",
      receipt_source_composition: [],
      can_render_share: false,
      coverage: LOADED_ZERO_CANDIDATE_MONEY_COVERAGE
    }
  };
}

/**
 * Slices the rendered Money at a glance region so currency assertions cannot be
 * satisfied (or defeated) by dollar values from unrelated panels on the page.
 */
function extractMoneyGlanceSection(body: string): string {
  const start = body.indexOf('<section class="detail__money-glance"');
  if (start === -1) {
    throw new Error("Expected a rendered Money at a glance section.");
  }
  const end = body.indexOf("</section>", start);
  if (end === -1) {
    throw new Error("Expected the Money at a glance section to be closed.");
  }

  return body.slice(start, end);
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
      identity_is_safe: true,
      has_official_total: true,
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
      coverage: POPULATED_CANDIDATE_MONEY_COVERAGE,
      out_of_cycle_official_total: null,
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
      ],
      coverage: POPULATED_SCHEDULE_E_COVERAGE
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
    detail: buildPersonDetailFixture(),
    personFinanceSections: asSettled([]),
    personContributionInsights: asSettled(CONTRIBUTION_INSIGHTS),
    personTopDonors: asSettled(PERSON_TOP_DONORS),
    personTopEmployers: asSettled(PERSON_TOP_EMPLOYERS),
    ...overrides
  };
}

function buildPersonPageBundleWithoutCurrentOffice(): EntityDetailPageBundle {
  const data = buildPersonPageBundle();
  if (data.entityType !== "person" || !("current_office" in data.detail)) {
    throw new Error("Expected a person detail bundle with current-office context.");
  }

  const { current_office: _currentOffice, ...detail } = data.detail;

  return buildPersonPageBundle({ detail });
}

describe("entity detail page rendering", () => {
  it("renders public person detail with identifier metrics and no ER/graph/civic internals", () => {
    const rendered = render(DetailPage, {
      props: { data: buildPersonPageBundle() }
    });

    expect(rendered.body).toContain("Portrait of Jane Doe");
    expect(rendered.body).toContain("<h3>Core attributes</h3>");
    expect(rendered.body).toContain("<dt>Current office</dt>");
    // The office name is the person page's return path into the race-discovery
    // chain (person -> office -> "Elections for this office" -> contest), so it
    // must be a link to the office record, not bare text. civibus-7qj.
    expect(rendered.body).toContain(
      '<a href="/office/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb">City Council Member</a>'
    );
    expect(rendered.body).toContain("<dt>Office level</dt>");
    expect(rendered.body).toContain("<dd>municipal</dd>");
    expect(rendered.body).toContain("<dt>Identifiers</dt>");
    expect(rendered.body).toContain("<dd>1</dd>");
    expect(rendered.body).toContain('data-testid="entity-metric-identifiers"');
    expect(rendered.body).not.toContain("ER matches");
    expect(rendered.body).not.toContain("Graph relationships");
    expect(rendered.body).not.toContain("Civic Record");
    expect(rendered.body).not.toContain("Officeholding timeline");
    expect(rendered.body).not.toContain("Entity internals");
  });

  // civibus-7qj: the direct person -> race link. The backend orders candidacies
  // nearest election first; the page renders payload order without re-sorting.
  it("renders a Races panel linking each candidacy's contest in payload order", () => {
    const rendered = render(DetailPage, {
      props: {
        data: buildPersonPageBundle({
          detail: buildPersonDetailFixture({
            candidacies: [
              {
                candidacy_id: "77777777-7777-4777-8777-777777777777",
                contest_id: "88888888-8888-4888-8888-888888888888",
                contest_name: "Test State U.S. Senate — 2026 General Election",
                election_date: "2026-11-03",
                election_type: "general",
                office_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                office_name: "Test Senator",
                office_level: "federal",
                party: "DEM",
                status: "qualified",
                incumbent_challenge: "I",
                fec_candidate_id: "S8ZZ00001"
              },
              {
                candidacy_id: "99999999-9999-4999-8999-999999999999",
                contest_id: "aaaaaaaa-1111-4111-8111-aaaaaaaa1111",
                contest_name: "Test State U.S. Senate — 2026 Primary",
                election_date: null,
                election_type: "primary",
                office_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                office_name: "Test Senator",
                office_level: "federal",
                party: null,
                status: null,
                incumbent_challenge: null,
                fec_candidate_id: null
              }
            ]
          })
        })
      }
    });

    expect(rendered.body).toContain('data-testid="person-races"');
    expect(rendered.body).toContain("<h3>Races</h3>");
    // Each contest name links its race through the shared /contest/[id] path owner.
    expect(rendered.body).toContain(
      '<a href="/contest/88888888-8888-4888-8888-888888888888">Test State U.S. Senate — 2026 General Election</a>'
    );
    expect(rendered.body).toContain(
      '<a href="/contest/aaaaaaaa-1111-4111-8111-aaaaaaaa1111">Test State U.S. Senate — 2026 Primary</a>'
    );
    // Response-backed secondary facts for the first row.
    expect(rendered.body).toContain("2026-11-03");
    expect(rendered.body).toContain("DEM");
    expect(rendered.body).toContain("qualified");
    // Payload order is preserved: the general race renders before the primary.
    const generalIndex = rendered.body.indexOf("2026 General Election");
    const primaryIndex = rendered.body.indexOf("2026 Primary");
    expect(generalIndex).toBeGreaterThan(-1);
    expect(primaryIndex).toBeGreaterThan(generalIndex);
    // Two rows, no placeholder facts for the null-valued second row.
    expect(rendered.body.match(/data-testid="person-race-row"/g)).toHaveLength(2);
  });

  it("omits the Races panel when the candidacies list is empty", () => {
    const rendered = render(DetailPage, {
      props: { data: buildPersonPageBundle() }
    });

    expect(rendered.body).not.toContain('data-testid="person-races"');
    expect(rendered.body).not.toContain("<h3>Races</h3>");
    expect(rendered.body).not.toContain('data-testid="person-race-row"');
  });

  it("omits the Races panel when an older payload lacks the candidacies key entirely", () => {
    const data = buildPersonPageBundle();
    if (data.entityType !== "person" || !("candidacies" in data.detail)) {
      throw new Error("Expected a person detail bundle with a candidacies list.");
    }
    const { candidacies: _candidacies, ...detail } = data.detail;

    const rendered = render(DetailPage, {
      props: { data: buildPersonPageBundle({ detail }) }
    });

    expect(rendered.body).not.toContain('data-testid="person-races"');
    expect(rendered.body).not.toContain('data-testid="person-race-row"');
  });

  it("renders canonical person facts without current-office rows when current office is omitted", () => {
    const rendered = render(DetailPage, {
      props: {
        data: buildPersonPageBundleWithoutCurrentOffice()
      }
    });

    expect(rendered.body).toContain("Jane Doe");
    expect(rendered.body).toContain("<h3>Core attributes</h3>");
    expect(rendered.body).toContain("<dt>Year of birth</dt>");
    expect(rendered.body).toContain("<dd>1985</dd>");
    expect(rendered.body).toContain("<dt>Identifiers</dt>");
    expect(rendered.body).toContain("<dd>1</dd>");
    expect(rendered.body).not.toContain("<dt>Current office</dt>");
    expect(rendered.body).not.toContain("<dt>Office level</dt>");
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

  // civibus-bmg: the finance-section card heading rendered `candidate.name`
  // bare. Mixed-case fixtures ("Candidate One") pass vacuously through the
  // formatter, so these specimens are deliberately ALL-CAPS/raw — the exact
  // class the 2026-08-20 deploy gate caught on the committee page.
  it("formats an identity-safe candidate's ALL-CAPS filed name in the finance card heading", () => {
    const rendered = render(DetailPage, {
      props: {
        data: buildPersonPageBundle({
          personFinanceSections: asSettled([
            buildPersonFinanceSection({
              candidate: {
                ...buildPersonFinanceSection().candidate,
                name: "WHITFIELD, T. MARGARET",
                identity_is_safe: true
              }
            })
          ])
        })
      }
    });

    expect(rendered.body).toContain("Whitfield, T. Margaret");
    expect(rendered.body).not.toContain("WHITFIELD, T. MARGARET");
  });

  it("keeps an identity-unsafe candidate's filed name raw in the finance card heading", () => {
    const rendered = render(DetailPage, {
      props: {
        data: buildPersonPageBundle({
          personFinanceSections: asSettled([
            buildPersonFinanceSection({
              candidate: {
                ...buildPersonFinanceSection().candidate,
                name: "212 N HALF W. JOHN, RODNEY HOWARD MR.",
                identity_is_safe: false
              }
            })
          ])
        })
      }
    });

    // Raw filed string survives untouched: prettifying a junk identity would
    // present source evidence as a vetted human name.
    expect(rendered.body).toContain("212 N HALF W. JOHN, RODNEY HOWARD MR.");
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
    expect(rendered.body).toContain("<h4>Top reported contributor names</h4>");
    expect(rendered.body).toContain("detail__rank-bar");
    expect(rendered.body).toContain("Largest Person Donor");
    expect(rendered.body).toContain("$500.00");
    expect(rendered.body).toContain("Second Person Donor");
    expect(rendered.body).toContain("<h4>Top reported employer names</h4>");
    expect(rendered.body).toContain("Top employers aggregate raw employer names from itemized individual contributions only.");
    expect(rendered.body).toContain(
      "The raw ranking remains employer-name data; see Methodology for source-linking and evidence limitations."
    );
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
    expect(
      rendered.body.match(
        /<section class="detail__money-glance" aria-label="Money at a glance">/g
      )
    ).toHaveLength(1);
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

  it("renders not-loaded Money at a glance copy with no dollar figures at all", () => {
    // person_detail.md: when fundraising coverage is `not_loaded`, Money at a glance
    // must say a linked FEC candidate exists but Civibus has not loaded authoritative
    // selected-cycle evidence, and must suppress the zero headline values entirely.
    const rendered = render(DetailPage, {
      props: {
        data: buildPersonPageBundle({
          personMoneyHeadline: buildNotLoadedMoneyHeadline(),
          personFinanceSections: new Promise(() => {}),
          personContributionInsights: new Promise(() => {}),
          personTopDonors: new Promise(() => {}),
          personTopEmployers: new Promise(() => {})
        })
      }
    });

    const moneyGlance = extractMoneyGlanceSection(rendered.body);

    // A dedicated test id, not the shared unavailable arm: "we have not loaded this"
    // and "this is temporarily broken" are different claims and must stay separable
    // for component and browser probes.
    expect(moneyGlance).toContain('data-testid="person-money-not-loaded"');
    expect(moneyGlance).toContain("Money at a glance");
    expect(moneyGlance).toContain("2026 cycle");
    expect(moneyGlance).toContain(
      "A linked FEC candidate exists for this person, but Civibus has not loaded authoritative selected-cycle fundraising evidence for that candidate."
    );

    // The reader must not be stranded. A cycle with no loaded evidence is exactly
    // the page you most need to leave, so the cycle switcher stays — dropping it
    // turned the not-loaded state into a dead end with no way back to a cycle
    // that does have data.
    expect(moneyGlance).toContain('aria-label="Election cycle"');
    expect(moneyGlance).toContain('aria-current="page"');
    expect(moneyGlance).toContain("?cycle=2024");

    // No dollar sign at all inside the region: no $0.00, no suppressed-metric labels.
    expect(moneyGlance).not.toContain("$");
    expect(moneyGlance).not.toContain("Total receipts");
    expect(moneyGlance).not.toContain("Total disbursements");
    expect(moneyGlance).not.toContain("Cash on hand");
    expect(moneyGlance).not.toContain("Debts owed by the committee");

    // Forbidden framings from the spec: missing evidence is not zero activity,
    // not an absence of filings, and not a campaign-wide or career total.
    expect(moneyGlance).not.toContain("no activity");
    expect(moneyGlance).not.toContain("No activity");
    expect(moneyGlance).not.toContain("no filings");
    expect(moneyGlance).not.toContain("career total");
    expect(moneyGlance).not.toContain("campaign total");
  });

  it("still renders explicit $0.00 when the discriminator proves loaded-zero coverage", () => {
    // Over-suppression guard. `loaded_zero` is authoritative evidence of genuine
    // no-money coverage, so the real zeroes must keep rendering as figures.
    const rendered = render(DetailPage, {
      props: {
        data: buildPersonPageBundle({
          personMoneyHeadline: buildLoadedZeroMoneyHeadline(),
          personFinanceSections: new Promise(() => {}),
          personContributionInsights: new Promise(() => {}),
          personTopDonors: new Promise(() => {}),
          personTopEmployers: new Promise(() => {})
        })
      }
    });

    const moneyGlance = extractMoneyGlanceSection(rendered.body);

    expect(moneyGlance).toContain("Money at a glance");
    expect(moneyGlance).toContain("2026 cycle");
    expect(moneyGlance).toContain("<dt>Total receipts</dt>");
    expect(moneyGlance).toContain("<dt>Total disbursements</dt>");
    expect(moneyGlance).toContain("<dt>Cash on hand</dt>");
    expect(moneyGlance).toContain("<dt>Debts owed by the committee</dt>");
    expect(moneyGlance.match(/<dd>\$0\.00<\/dd>/g)).toHaveLength(4);
    expect(moneyGlance).not.toContain(
      "A linked FEC candidate exists for this person, but Civibus has not loaded authoritative selected-cycle fundraising evidence for that candidate."
    );
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
                coverage: POPULATED_CANDIDATE_MONEY_COVERAGE,
                out_of_cycle_official_total: null,
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

  it("keeps the outside-spending anchor unique across multiple candidacies", () => {
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

    expect(rendered.body.match(/\sid="person-outside-spending"/g)).toHaveLength(1);
    expect(rendered.body.match(/>Outside spending<\/h4>/g)).toHaveLength(2);
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

    const topDonorsIndex = rendered.body.indexOf("<h4>Top reported contributor names</h4>");
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

    const topDonorsIndex = rendered.body.indexOf("<h4>Top reported contributor names</h4>");
    const topEmployersIndex = rendered.body.indexOf("<h4>Top reported employer names</h4>", topDonorsIndex);
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

  it("renders the server-owned industry rollup after the unchanged employer-name table", () => {
    const rendered = render(DetailPage, {
      props: {
        data: buildPersonPageBundle({
          personFinanceSections: asSettled([buildPersonFinanceSection()])
        })
      }
    });

    const topEmployersIndex = rendered.body.indexOf("<h4>Top reported employer names</h4>");
    const legacyEmployerIndex = rendered.body.indexOf("Legacy employer bucket", topEmployersIndex);
    const industryHeadingIndex = rendered.body.indexOf(
      "<h4>Industries among top reported employer names</h4>",
      topEmployersIndex
    );
    const industryRows = rendered.body.match(/data-testid="industry-rollup-row"/g) ?? [];

    expect(topEmployersIndex).toBeGreaterThan(-1);
    expect(legacyEmployerIndex).toBeGreaterThan(topEmployersIndex);
    expect(industryHeadingIndex).toBeGreaterThan(legacyEmployerIndex);
    expect(industryRows).toHaveLength(2);
    expect(rendered.body).toContain(
      '<tr data-testid="industry-rollup-row"><td>Technology</td><td>$600.00</td><td>3 transactions</td></tr>'
    );
    expect(rendered.body).toContain(
      '<tr data-testid="industry-rollup-row"><td>Unknown / unclassified</td><td>$150.00</td><td>1 transaction</td></tr>'
    );
    expect(rendered.body).toContain(
      "Classified: $600.00 and 3 transactions out of $750.00 and 4 transactions among eligible top-employer rows."
    );
    expect(rendered.body).toContain(
      "Industries are assigned from reported employer names by the server. This rollup covers only eligible returned top-employer rows for the selected cycle."
    );
    expect(rendered.body).toContain("<th>Employer</th><th>Total</th><th>Transactions</th>");
  });

  it("renders an honest industry empty state when no employer row is eligible", () => {
    const rendered = render(DetailPage, {
      props: {
        data: buildPersonPageBundle({
          personFinanceSections: asSettled([buildPersonFinanceSection()]),
          personTopEmployers: asSettled([
            {
              employer: "Legacy employer bucket",
              total_amount: "25.00",
              transaction_count: 1,
              industry: "UNKNOWN_INDUSTRY",
              industry_rollup_eligible: false
            }
          ])
        })
      }
    });

    expect(rendered.body).toContain("<h4>Industries among top reported employer names</h4>");
    expect(rendered.body).toContain(
      "No industry data is available among eligible top-employer rows for this cycle."
    );
    expect(rendered.body).not.toContain('data-testid="industry-rollup-row"');
    expect(rendered.body).not.toContain("Classified:");
    expect(rendered.body).toContain("Legacy employer bucket");
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
                ],
                coverage: POPULATED_SCHEDULE_E_COVERAGE
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
                ],
                coverage: POPULATED_SCHEDULE_E_COVERAGE
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
          top_spenders: [],
          coverage: LOADED_ZERO_SCHEDULE_E_COVERAGE
        },
        expectedCopy: "No independent expenditure support or oppose activity is reported for this cycle."
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
            identity_is_safe: true,
            has_official_total: true,
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
        current_office: null,
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
          coverage: LOADED_ZERO_CANDIDATE_MONEY_COVERAGE,
          out_of_cycle_official_total: null,
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
          coverage: LOADED_ZERO_CANDIDATE_MONEY_COVERAGE,
          out_of_cycle_official_total: null,
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
    const outsideSpendingIndex = personFinanceSlice.indexOf(
      '<h4 id={candidateIndex === 0 ? "person-outside-spending" : undefined}>Outside spending</h4>'
    );
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

describe("entity detail scrollable regions", () => {
  // axe rule scrollable-region-focusable, impact serious, reported live against
  // /person/[id] before this guard existed. .detail__table-scroll sets overflow-x: auto over a table wider
  // than its container; with no focusable descendant such a region cannot be
  // scrolled from the keyboard at all. The smoke a11y floor refuses serious
  // violations, but it only runs nightly - this holds the same invariant at
  // vitest speed, and it fails the moment a new scroll container is added
  // without the attribute rather than when the fix is deleted from an old one.
  it("gives every horizontal scroll container a keyboard tab stop", () => {
    const source = readFileSync(new URL("./DetailPage.svelte", import.meta.url), "utf8");
    const containers = [...source.matchAll(/<div class="detail__table-scroll"[^>]*>/g)].map(
      (match) => match[0]
    );

    expect(containers.length).toBeGreaterThan(0);
    for (const container of containers) {
      expect(container).toContain('tabindex="0"');
    }
  });
});
