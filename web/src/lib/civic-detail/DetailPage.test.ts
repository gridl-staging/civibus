import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "svelte/server";
import type {
  CandidacyDetailResponse,
  ContestDetailResponse,
  OfficeDetailResponse,
  OfficeholdingDetailResponse
} from "./contract";
import {
  buildCandidacyDetailPresentation,
  buildContestDetailPresentation,
  buildOfficeDetailPresentation,
  buildOfficeholdingDetailPresentation
} from "./presentation";
import DetailPage from "./DetailPage.svelte";

type NavTarget = { url: URL; params: null; route: { id: null }; scroll: null };
type MockNavigation = { from: NavTarget | null; to: NavTarget | null };
let currentNavigating: MockNavigation | null = null;

function navTarget(url: string): NavTarget {
  return { url: new URL(url), params: null, route: { id: null }, scroll: null };
}

vi.mock("$app/stores", () => ({
  navigating: {
    subscribe(run: (value: MockNavigation | null) => void): () => void {
      run(currentNavigating);
      return () => {};
    }
  }
}));

const OFFICE_ID = "33333333-3333-4333-8333-333333333333";
const CONTEST_ID = "77777777-7777-4777-8777-777777777777";
const CANDIDACY_ID = "88888888-8888-4888-8888-888888888888";
const PERSON_ID = "11111111-1111-4111-8111-111111111111";
const ELECTORAL_DIVISION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

const CONTEST_DETAIL: ContestDetailResponse = {
  id: CONTEST_ID,
  name: "Governor 2026 General Election",
  election_date: "2026-11-03",
  election_type: "general",
  office_id: OFFICE_ID,
  electoral_division_id: null,
  number_of_seats: 1,
  filing_deadline: "2026-09-01",
  is_partisan: true,
  candidate_list_incomplete: false,
  candidacies: [
    {
      candidacy_id: CANDIDACY_ID,
      person_id: PERSON_ID,
      person_name: "Jane Candidate",
      party: "DEM",
      status: "filed",
      incumbent_challenge: "I"
    }
  ],
  sources: []
};

const OFFICEHOLDING_ID = "99999999-9999-4999-8999-999999999999";
const OFFICE_DETAIL: OfficeDetailResponse = {
  id: OFFICE_ID,
  name: "Governor",
  office_level: "state",
  title: "Governor",
  jurisdiction_id: null,
  state: "NC",
  is_elected: true,
  number_of_seats: 1,
  current_officeholders: [
    {
      officeholding_id: OFFICEHOLDING_ID,
      person_id: PERSON_ID,
      person_name: "Jane Candidate",
      holder_status: "elected"
    },
    {
      officeholding_id: "aaaaaaa1-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
      person_id: "aaaaaaa2-aaaa-4aaa-8aaa-aaaaaaaaaaa2",
      person_name: "Alex Challenger",
      holder_status: "appointed"
    }
  ],
  current_holder_card: {
    officeholding_id: OFFICEHOLDING_ID,
    person_id: PERSON_ID,
    person_name: "Jane Candidate",
    holder_status: "elected",
    electoral_division_id: ELECTORAL_DIVISION_ID,
    electoral_division_type: "county",
    electoral_division_state: "NC",
    valid_period_lower: "2025-01-01",
    valid_period_upper: null,
    date_precision: "day"
  },
  officeholding_timeline: [
    {
      officeholding_id: OFFICEHOLDING_ID,
      person_id: PERSON_ID,
      person_name: "Jane Candidate",
      holder_status: "elected",
      electoral_division_id: ELECTORAL_DIVISION_ID,
      electoral_division_type: "county",
      electoral_division_state: "NC",
      valid_period_lower: "2025-01-01",
      valid_period_upper: null,
      date_precision: "day",
      is_active: true,
      term_ended: false
    },
    {
      officeholding_id: "former-officeholding",
      person_id: "former-person",
      person_name: "Former Incumbent",
      holder_status: "former",
      electoral_division_id: ELECTORAL_DIVISION_ID,
      electoral_division_type: "county",
      electoral_division_state: "NC",
      valid_period_lower: "2020-01-01",
      valid_period_upper: "2024-01-01",
      date_precision: "day",
      is_active: false,
      term_ended: true
    }
  ],
  recent_contests: [
    {
      contest_id: "contest-newer",
      contest_name: "Governor 2026 General",
      election_date: "2026-11-03",
      election_type: "general",
      filing_deadline: "2026-09-01",
      electoral_division_id: ELECTORAL_DIVISION_ID,
      electoral_division_type: "county",
      electoral_division_state: "NC",
      is_partisan: true,
      candidate_list_incomplete: false
    },
    {
      contest_id: "contest-older",
      contest_name: "Governor 2024 General",
      election_date: "2024-11-05",
      election_type: "general",
      filing_deadline: "2024-09-01",
      electoral_division_id: ELECTORAL_DIVISION_ID,
      electoral_division_type: "county",
      electoral_division_state: "NC",
      is_partisan: true,
      candidate_list_incomplete: true
    }
  ],
  selected_electoral_division_id: ELECTORAL_DIVISION_ID,
  selected_electoral_division_type: "county",
  selected_electoral_division_state: "NC",
  incomplete_data_states: [],
  sources: []
};

const CONTEST_DETAIL_WITH_MULTIPLE_CANDIDACIES: ContestDetailResponse = {
  ...CONTEST_DETAIL,
  candidacies: [
    ...CONTEST_DETAIL.candidacies,
    {
      candidacy_id: "bbbbbbb1-bbbb-4bbb-8bbb-bbbbbbbbbbb1",
      person_id: "bbbbbbb2-bbbb-4bbb-8bbb-bbbbbbbbbbb2",
      person_name: "Alex Challenger",
      party: "REP",
      status: "qualified",
      incumbent_challenge: "C"
    }
  ]
};

const OFFICE_DETAIL_WITH_HOMONYMS: OfficeDetailResponse = {
  id: OFFICE_ID,
  name: "Governor",
  office_level: "state",
  title: "Governor",
  jurisdiction_id: null,
  state: "NC",
  is_elected: true,
  number_of_seats: 2,
  current_officeholders: [
    {
      officeholding_id: OFFICEHOLDING_ID,
      person_id: PERSON_ID,
      person_name: "Jane Smith",
      holder_status: "elected"
    },
    {
      officeholding_id: "aaaaaaa1-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
      person_id: "aaaaaaa2-aaaa-4aaa-8aaa-aaaaaaaaaaa2",
      person_name: "Jane Smith",
      holder_status: "appointed"
    }
  ],
  current_holder_card: null,
  officeholding_timeline: [],
  recent_contests: [],
  selected_electoral_division_id: null,
  selected_electoral_division_type: null,
  selected_electoral_division_state: null,
  incomplete_data_states: [],
  sources: []
};

const CONTEST_DETAIL_WITH_HOMONYMS: ContestDetailResponse = {
  ...CONTEST_DETAIL,
  candidacies: [
    {
      candidacy_id: CANDIDACY_ID,
      person_id: PERSON_ID,
      person_name: "Jane Smith",
      party: "DEM",
      status: "filed",
      incumbent_challenge: "I"
    },
    {
      candidacy_id: "bbbbbbb1-bbbb-4bbb-8bbb-bbbbbbbbbbb1",
      person_id: "bbbbbbb2-bbbb-4bbb-8bbb-bbbbbbbbbbb2",
      person_name: "Jane Smith",
      party: "REP",
      status: "qualified",
      incumbent_challenge: "C"
    }
  ]
};

const OFFICE_DETAIL_WITH_INCOMPLETE_DATA: OfficeDetailResponse = {
  ...OFFICE_DETAIL,
  current_officeholders: [],
  current_holder_card: null,
  officeholding_timeline: [],
  recent_contests: [],
  selected_electoral_division_id: null,
  selected_electoral_division_type: null,
  selected_electoral_division_state: null,
  incomplete_data_states: ["no_officeholder"]
};

const CONTEST_DETAIL_WITH_INCOMPLETE_CANDIDACY_DATA: ContestDetailResponse = {
  ...CONTEST_DETAIL,
  candidate_list_incomplete: true,
  candidacies: []
};

const CANDIDACY_DETAIL_WITH_MISSING_STATUS: CandidacyDetailResponse = {
  id: CANDIDACY_ID,
  person_id: PERSON_ID,
  person_name: "Jane Candidate",
  contest_id: CONTEST_ID,
  party: "DEM",
  filing_date: "2026-02-01",
  status: null,
  incumbent_challenge: "I",
  candidate_number: "17",
  sources: []
};

const OFFICEHOLDING_DETAIL_WITH_MISSING_PERIOD: OfficeholdingDetailResponse = {
  id: OFFICEHOLDING_ID,
  person_id: PERSON_ID,
  person_name: "Jane Candidate",
  office_id: OFFICE_ID,
  electoral_division_id: null,
  holder_status: "elected",
  valid_period_lower: null,
  valid_period_upper: null,
  date_precision: "day",
  sources: []
};

describe("civic detail page rendering", () => {
  beforeEach(() => {
    currentNavigating = null;
  });

  it("relies on shell-level busy state without a detail-level aria-busy attribute", () => {
    const rendered = render(DetailPage, {
      props: {
        entityType: "contest",
        data: CONTEST_DETAIL
      }
    });

    expect(rendered.body).toContain('<section class="card detail" aria-label="contest detail">');
    expect(rendered.body).not.toContain('aria-label="contest detail" aria-busy=');
  });

  it("renders only civic skeleton content while navigating between detail routes", () => {
    currentNavigating = {
      from: navTarget(`https://civibus.test/contest/${CONTEST_ID}`),
      to: navTarget(`https://civibus.test/office/${OFFICE_ID}`)
    };
    const rendered = render(DetailPage, {
      props: {
        entityType: "contest",
        data: CONTEST_DETAIL
      }
    });

    expect(rendered.body).toContain("contest detail loading");
    expect(rendered.body).not.toContain("Contest facts");
    expect(rendered.body).not.toContain("View office record");
  });

  it("does not show civic skeleton when navigating to a non-civic route", () => {
    currentNavigating = {
      from: navTarget(`https://civibus.test/office/${OFFICE_ID}`),
      to: navTarget(`https://civibus.test/person/${PERSON_ID}`)
    };
    const rendered = render(DetailPage, {
      props: {
        entityType: "office",
        data: OFFICE_DETAIL
      }
    });

    expect(rendered.body).not.toContain("office detail loading");
    expect(rendered.body).toContain("Office facts");
    expect(rendered.body).toContain("Jane Candidate");
  });

  it("uses record-specific accessible names for repeated row-level detail links", () => {
    const officeRendered = render(DetailPage, {
      props: {
        entityType: "office",
        data: OFFICE_DETAIL
      }
    });

    expect(officeRendered.body).toContain('aria-label="View officeholding detail for Jane Candidate"');
    expect(officeRendered.body).toContain('aria-label="View officeholding detail for Alex Challenger"');

    const contestRendered = render(DetailPage, {
      props: {
        entityType: "contest",
        data: CONTEST_DETAIL_WITH_MULTIPLE_CANDIDACIES
      }
    });

    expect(contestRendered.body).toContain('aria-label="View candidacy detail for Jane Candidate"');
    expect(contestRendered.body).toContain('aria-label="View candidacy detail for Alex Challenger"');
  });

  it("disambiguates row-level links when multiple rows share the same person name", () => {
    const officeRendered = render(DetailPage, {
      props: {
        entityType: "office",
        data: OFFICE_DETAIL_WITH_HOMONYMS
      }
    });

    expect(officeRendered.body).toContain(
      'aria-label="View officeholding detail for Jane Smith, elected"'
    );
    expect(officeRendered.body).toContain(
      'aria-label="View officeholding detail for Jane Smith, appointed"'
    );

    const contestRendered = render(DetailPage, {
      props: {
        entityType: "contest",
        data: CONTEST_DETAIL_WITH_HOMONYMS
      }
    });

    expect(contestRendered.body).toContain(
      'aria-label="View candidacy detail for Jane Smith, DEM"'
    );
    expect(contestRendered.body).toContain(
      'aria-label="View candidacy detail for Jane Smith, REP"'
    );
  });

  it("renders office records as semantic tables without debug labels or pipe delimiters", () => {
    const rendered = render(DetailPage, {
      props: {
        entityType: "office",
        data: OFFICE_DETAIL
      }
    });

    expect(rendered.body).toContain('class="detail__table-scroll"');
    expect(rendered.body).toContain("<table>");
    expect(rendered.body).toContain("<thead>");
    expect(rendered.body).toMatch(/<th(?:\s+scope="col")?>Person<\/th>/);
    expect(rendered.body).toMatch(/<th(?:\s+scope="col")?>Officeholding record<\/th>/);
    expect(rendered.body).toMatch(/<th(?:\s+scope="col")?>Holder status<\/th>/);
    expect(rendered.body).not.toContain('<ul class="detail__list">');
    expect(rendered.body).not.toContain("status:");
    expect(rendered.body).not.toContain('<span aria-hidden="true">|</span>');
  });

  it("renders office current-holder, timeline, and recent contest sections", () => {
    const rendered = render(DetailPage, {
      props: {
        entityType: "office",
        data: OFFICE_DETAIL
      }
    });

    expect(rendered.body).toContain("<h3>Current holder</h3>");
    expect(rendered.body).toContain("Jane Candidate");
    expect(rendered.body).toContain("<h3>Officeholding timeline</h3>");
    expect(rendered.body).toContain("Former Incumbent");
    expect(rendered.body).toContain("Term ended 2024-01-01");
    expect(rendered.body).toContain("<h3>Recent contests</h3>");
    expect(rendered.body).toContain("Governor 2026 General");
    expect(rendered.body).toContain('href="/contest/contest-newer"');
  });

  it("treats missing officeholding_timeline payloads as an empty timeline section", () => {
    const malformedOfficePayload = {
      ...OFFICE_DETAIL,
      officeholding_timeline: undefined
    } as unknown as OfficeDetailResponse;

    const rendered = render(DetailPage, {
      props: {
        entityType: "office",
        data: malformedOfficePayload
      }
    });

    expect(rendered.body).toContain("<h3>Officeholding timeline</h3>");
    expect(rendered.body).toContain(
      "No officeholding history is linked yet. Check back after the next records refresh."
    );
  });

  it("treats missing recent_contests payloads as an empty recent contests section", () => {
    const malformedOfficePayload = {
      ...OFFICE_DETAIL,
      recent_contests: undefined
    } as unknown as OfficeDetailResponse;

    const rendered = render(DetailPage, {
      props: {
        entityType: "office",
        data: malformedOfficePayload
      }
    });

    expect(rendered.body).toContain("<h3>Recent contests</h3>");
    expect(rendered.body).toContain(
      "No recent contests are linked yet. Check back after the next records refresh."
    );
  });

  it("treats non-object current_holder_card payloads as missing and renders empty current-holder copy", () => {
    const malformedOfficePayload = {
      ...OFFICE_DETAIL,
      current_holder_card: "invalid"
    } as unknown as OfficeDetailResponse;

    const rendered = render(DetailPage, {
      props: {
        entityType: "office",
        data: malformedOfficePayload
      }
    });

    expect(rendered.body).toContain("<h3>Current holder</h3>");
    expect(rendered.body).toContain(
      "No active officeholder is linked yet. Check back after the next records refresh."
    );
  });

  it("shows current-holder section when current_holder_card is missing but officeholders exist", () => {
    const malformedOfficePayload = {
      ...OFFICE_DETAIL_WITH_HOMONYMS,
      current_holder_card: undefined
    } as unknown as OfficeDetailResponse;

    const rendered = render(DetailPage, {
      props: {
        entityType: "office",
        data: malformedOfficePayload
      }
    });

    expect(rendered.body).toContain("<h3>Current holder</h3>");
    expect(rendered.body).toContain(
      "No active officeholder is linked yet. Check back after the next records refresh."
    );
  });

  it("does not show no-active-holder copy when multiple current officeholders exist", () => {
    const rendered = render(DetailPage, {
      props: {
        entityType: "office",
        data: OFFICE_DETAIL_WITH_HOMONYMS
      }
    });

    expect(rendered.body).not.toContain("<h3>Current holder</h3>");
    expect(rendered.body).not.toContain(
      "No active officeholder is linked yet. Check back after the next records refresh."
    );
    expect(rendered.body).toContain("<h3>Current officeholders</h3>");
    expect(rendered.body).toContain("Jane Smith");
  });

  it("renders office empty-state record copy and incomplete-data caveat when linked rows are missing", () => {
    const rendered = render(DetailPage, {
      props: {
        entityType: "office",
        data: OFFICE_DETAIL_WITH_INCOMPLETE_DATA
      }
    });

    expect(rendered.body).toContain(
      "No current officeholders are linked yet. Check back after the next records refresh."
    );
    expect(rendered.body).toContain(
      "No officeholding history is linked yet. Check back after the next records refresh."
    );
    expect(rendered.body).toContain(
      "No recent contests are linked yet. Check back after the next records refresh."
    );
    expect(rendered.body).toContain("Current officeholder data is incomplete for this office.");
    expect(rendered.body).toContain("Data coverage warning");
  });

  it("renders contest records as semantic tables without debug labels or pipe delimiters", () => {
    const rendered = render(DetailPage, {
      props: {
        entityType: "contest",
        data: CONTEST_DETAIL
      }
    });

    expect(rendered.body).toContain('class="detail__table-scroll"');
    expect(rendered.body).toContain("<table>");
    expect(rendered.body).toContain("<thead>");
    expect(rendered.body).toMatch(/<th(?:\s+scope="col")?>Person<\/th>/);
    expect(rendered.body).toMatch(/<th(?:\s+scope="col")?>Candidacy record<\/th>/);
    expect(rendered.body).toMatch(/<th(?:\s+scope="col")?>Party<\/th>/);
    expect(rendered.body).toMatch(/<th(?:\s+scope="col")?>Status<\/th>/);
    expect(rendered.body).toMatch(/<th(?:\s+scope="col")?>Incumbent\/challenger<\/th>/);
    expect(rendered.body).not.toContain('<ul class="detail__list">');
    expect(rendered.body).not.toContain("party:");
    expect(rendered.body).not.toContain("status:");
    expect(rendered.body).not.toContain("incumbent/challenger:");
    expect(rendered.body).not.toContain('<span aria-hidden="true">|</span>');
  });

  it("renders contest results and candidate finance/outside-spending sections", () => {
    const rendered = render(DetailPage, {
      props: {
        entityType: "contest",
        data: {
          ...CONTEST_DETAIL,
          result_winner_candidacy_id: CANDIDACY_ID,
          result_winner_person_id: PERSON_ID,
          result_winner_person_name: "Jane Candidate"
        },
        contestSelectedCycle: 9999,
        contestCandidateFinanceByPersonId: {
          [PERSON_ID]: {
            personId: PERSON_ID,
            candidateHref: "/candidate/jane-candidate",
            summary: {
              selected_cycle: 2026,
              coverage_start_date: "2025-01-01",
              coverage_end_date: "2026-12-31",
              available_cycles: [2022, 2024, 2026],
              candidate_id: "candidate-1",
              candidate_name: "Jane Candidate",
              total_raised: "5000.00",
              total_spent: "2000.00",
              net: "3000.00",
              transaction_count: 42,
              itemized_transaction_count: 42,
              cash_on_hand: "1000.00",
              summary_source: "derived" as const,
              receipt_source_composition: [],
              selected_cycle_coverage_complete: false,
              can_render_share: false,
              receipt_source_caveats: [],
              committees: []
            },
            ieSummary: {
              selected_cycle: 2026,
              coverage_start_date: "2025-01-01",
              coverage_end_date: "2026-12-31",
              available_cycles: [2022, 2024, 2026],
              candidate_id: "candidate-1",
              support_total: "100.00",
              oppose_total: "50.00",
              support_count: 1,
              oppose_count: 1,
              top_spenders: [
                {
                  committee_id: "committee-1",
                  committee_name: "Independent Expenditure Committee",
                  support_oppose: "S",
                  total_amount: "100.00",
                  transaction_count: 1
                }
              ],
              excluded_outlier_count: 0
            },
            ieTransactions: [
              {
                id: "ie-1",
                filing_id: null,
                committee_id: "committee-1",
                committee_name: "Independent Expenditure Committee",
                amount: 100,
                transaction_date: "2026-03-19",
                purpose: "Independent expenditure",
                dissemination_date: "2026-03-20",
                aggregate_amount: 100,
                support_oppose: "S"
              }
            ]
          }
        }
      }
    });

    expect(rendered.body).toContain("<h3>Results</h3>");
    expect(rendered.body).toContain('data-testid="contest-results-panel"');
    expect(rendered.body).toContain("Jane Candidate");
    expect(
      rendered.body.match(/href="\/person\/11111111-1111-4111-8111-111111111111\?cycle=2026"/g)
    ).toHaveLength(2);
    expect(rendered.body).not.toContain("?cycle=9999");
    expect(rendered.body).toContain("<h3>Candidate finance and outside spending</h3>");
    expect(rendered.body).toContain('href="/candidate/jane-candidate?cycle=2026"');
    expect(rendered.body).toContain("Selected cycle");
    expect(rendered.body).toContain("Coverage through");
    expect(rendered.body).toContain("Receipts");
    expect(rendered.body).toContain("$5,000.00");
    expect(rendered.body).toContain("Disbursements");
    expect(rendered.body).toContain("$2,000.00");
    expect(rendered.body).toContain("Cash on hand");
    expect(rendered.body).toContain("$1,000.00");
    expect(rendered.body).not.toContain("Debt");
    expect(rendered.body).not.toContain("Fundraising summary");
    expect(rendered.body).toContain("Outside Spending");
    expect(rendered.body).not.toContain("Finance chart for Jane Candidate");
    expect(rendered.body).not.toContain("Outside spending chart for Jane Candidate");
    expect(rendered.body).toContain("Outside spending is independent and not controlled by the candidate committee.");
    expect(rendered.body).toContain("2026 cycle, coverage through December 31, 2026. Unit: dollars");
    expect(rendered.body).toContain(
      "Outside spending reports $100.00 in support spending and $50.00 in oppose spending for the 2026 cycle."
    );
    expect(rendered.body).toContain("View chart data");
    expect(rendered.body).toContain("Support spending");
    expect(rendered.body).toMatch(/Dollars:[\s\S]*\$100\.00[\s\S]*Transactions:[\s\S]*1/);
    expect(rendered.body).toContain('data-zero-centered="true"');
    expect(rendered.body).toContain('href="/committee/committee-1"');
    expect(rendered.body).toContain("Independent Expenditure Committee");
    expect(rendered.body).toContain("Dissemination Date");
    expect(rendered.body).toContain("2026-03-20");
  });

  it("renders route-selected cycle person links when contest finance sections are empty", () => {
    const rendered = render(DetailPage, {
      props: {
        entityType: "contest",
        data: {
          ...CONTEST_DETAIL,
          result_winner_candidacy_id: CANDIDACY_ID,
          result_winner_person_id: PERSON_ID,
          result_winner_person_name: "Jane Candidate"
        },
        contestSelectedCycle: 2024,
        contestCandidateFinanceByPersonId: {
          [PERSON_ID]: {
            personId: PERSON_ID,
            candidateHref: null,
            summary: null,
            ieSummary: null,
            ieTransactions: []
          }
        }
      }
    });

    expect(
      rendered.body.match(/href="\/person\/11111111-1111-4111-8111-111111111111\?cycle=2024"/g)
    ).toHaveLength(3);
    expect(rendered.body).toContain("Candidate fundraising data is not yet available.");
    expect(rendered.body).toContain(
      "Outside-spending data is not yet available for this candidate. Coverage may be incomplete."
    );
  });

  it("lets the shared outside-spending figure suppress zero-activity plots", () => {
    const rendered = render(DetailPage, {
      props: {
        entityType: "contest",
        data: {
          ...CONTEST_DETAIL,
          result_winner_candidacy_id: CANDIDACY_ID,
          result_winner_person_id: PERSON_ID,
          result_winner_person_name: "Jane Candidate"
        },
        contestSelectedCycle: 2024,
        contestCandidateFinanceByPersonId: {
          [PERSON_ID]: {
            personId: PERSON_ID,
            candidateHref: "/candidate/jane-candidate",
            summary: null,
            ieSummary: {
              selected_cycle: 2024,
              coverage_start_date: "2023-01-01",
              coverage_end_date: "2024-10-15",
              available_cycles: [2024],
              candidate_id: "candidate-1",
              support_total: "0.00",
              oppose_total: "0.00",
              support_count: 0,
              oppose_count: 0,
              top_spenders: [],
              excluded_outlier_count: 0
            },
            ieTransactions: []
          }
        }
      }
    });

    expect(rendered.body).toContain(
      "No independent expenditure support or oppose activity is reported for this cycle."
    );
    expect(rendered.body).toContain(
      "Outside spending is independent and not controlled by the candidate committee."
    );
    expect(rendered.body).not.toContain(
      'data-testid="contest-outside-spending-11111111-1111-4111-8111-111111111111-plot"'
    );
  });

  it("renders contest empty-state and degraded-coverage caveat when candidacies are unavailable", () => {
    const rendered = render(DetailPage, {
      props: {
        entityType: "contest",
        data: CONTEST_DETAIL_WITH_INCOMPLETE_CANDIDACY_DATA
      }
    });

    expect(rendered.body).toContain(
      "No candidacies are linked yet. Check back after the next records refresh."
    );
    expect(rendered.body).toContain("Candidate list coverage is incomplete for this contest.");
    expect(rendered.body).toContain("Data coverage warning");
  });

  it("passes contest division highlight metadata to the shared RegionMap seam", () => {
    const rendered = render(DetailPage, {
      props: {
        entityType: "contest",
        data: {
          ...CONTEST_DETAIL,
          electoral_division_id: "division-2"
        },
        contestMap: {
          pageLevel: "state",
          stateCode: "NC",
          layerVisibility: {
            nc_statewide_boundary: true,
            nc_county_boundaries: true,
            nc_congressional_districts: false
          },
          geometryByLevel: {
            state: {
              type: "FeatureCollection",
              features: []
            },
            county: {
              type: "FeatureCollection",
              features: [
                {
                  type: "Feature",
                  geometry: { type: "Polygon", coordinates: [] },
                  properties: {
                    id: "division-1",
                    name: "County One",
                    division_type: "county",
                    state: "NC",
                    district_number: null,
                    boundary_year: 2024
                  }
                },
                {
                  type: "Feature",
                  geometry: { type: "Polygon", coordinates: [] },
                  properties: {
                    id: "division-2",
                    name: "County Two",
                    division_type: "county",
                    state: "NC",
                    district_number: null,
                    boundary_year: 2024
                  }
                }
              ]
            },
            congressional_district: {
              type: "FeatureCollection",
              features: []
            }
          }
        }
      }
    });

    expect(rendered.body).toContain("Map preview");
    expect(rendered.body).toContain('data-feature-id="division-1"');
    expect(rendered.body).toContain('data-feature-id="division-2"');
    expect(rendered.body).toMatch(/class="[^"]*region-map__feature--highlighted[^"]*"/);
  });

  it("passes office division highlight metadata to the shared RegionMap seam", () => {
    const rendered = render(DetailPage, {
      props: {
        entityType: "office",
        data: OFFICE_DETAIL,
        contestMap: {
          pageLevel: "state",
          stateCode: "NC",
          layerVisibility: {
            nc_statewide_boundary: true,
            nc_county_boundaries: true,
            nc_congressional_districts: false
          },
          geometryByLevel: {
            state: {
              type: "FeatureCollection",
              features: []
            },
            county: {
              type: "FeatureCollection",
              features: [
                {
                  type: "Feature",
                  geometry: { type: "Polygon", coordinates: [] },
                  properties: {
                    id: "division-1",
                    name: "County One",
                    division_type: "county",
                    state: "NC",
                    district_number: null,
                    boundary_year: 2024
                  }
                },
                {
                  type: "Feature",
                  geometry: { type: "Polygon", coordinates: [] },
                  properties: {
                    id: ELECTORAL_DIVISION_ID,
                    name: "County Two",
                    division_type: "county",
                    state: "NC",
                    district_number: null,
                    boundary_year: 2024
                  }
                }
              ]
            },
            congressional_district: {
              type: "FeatureCollection",
              features: []
            }
          }
        }
      }
    });

    expect(rendered.body).toContain("District map context");
    expect(rendered.body).toContain(`data-feature-id="${ELECTORAL_DIVISION_ID}"`);
    expect(rendered.body).toMatch(/class="[^"]*region-map__feature--highlighted[^"]*"/);
  });

  it("renders caveat warnings as a shared note banner and keeps warning text sourced from presenters", () => {
    const officeWarning = buildOfficeDetailPresentation(OFFICE_DETAIL_WITH_INCOMPLETE_DATA).incompleteDataWarning;
    const contestWarning = buildContestDetailPresentation(
      CONTEST_DETAIL_WITH_INCOMPLETE_CANDIDACY_DATA
    ).candidateListWarning;
    const candidacyWarning = buildCandidacyDetailPresentation(
      CANDIDACY_DETAIL_WITH_MISSING_STATUS
    ).statusEmptyMessage;
    const officeholdingWarning = buildOfficeholdingDetailPresentation(
      OFFICEHOLDING_DETAIL_WITH_MISSING_PERIOD
    ).validPeriodEmptyMessage;

    const warningCases = [
      { entityType: "office", data: OFFICE_DETAIL_WITH_INCOMPLETE_DATA, warning: officeWarning },
      {
        entityType: "contest",
        data: CONTEST_DETAIL_WITH_INCOMPLETE_CANDIDACY_DATA,
        warning: contestWarning
      },
      {
        entityType: "candidacy",
        data: CANDIDACY_DETAIL_WITH_MISSING_STATUS,
        warning: candidacyWarning
      },
      {
        entityType: "officeholding",
        data: OFFICEHOLDING_DETAIL_WITH_MISSING_PERIOD,
        warning: officeholdingWarning
      }
    ] as const;

    for (const warningCase of warningCases) {
      expect(warningCase.warning).toBeTruthy();
      const rendered = render(DetailPage, {
        props: {
          entityType: warningCase.entityType,
          data: warningCase.data
        }
      });

      expect(rendered.body).toMatch(/role="note"/);
      expect(rendered.body).toMatch(/class="[^"]*caveat-banner[^"]*"/);
      expect(rendered.body).toContain(warningCase.warning as string);
      expect((rendered.body.match(/role="note"/g) ?? []).length).toBe(1);
    }
  });
});
