import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "svelte/server";
import { expectScrollContainersHaveTabStop } from "$lib/detail_scroll_tab_stop_guard";
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
const LOADED_ZERO_SCHEDULE_E_COVERAGE = {
  activity_state: "loaded_zero" as const,
  completeness: "complete" as const,
  basis: "authoritative_load_evidence" as const
};

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
    expect(rendered.body).toContain("<h3>Elections for this office</h3>");
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

    expect(rendered.body).toContain("<h3>Elections for this office</h3>");
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

  it("renders the race money scoreboard as a semantic table ordered by the backend", () => {
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
        contestCandidateMoney: {
          contest_id: CONTEST_DETAIL.id,
          selected_cycle: 2026,
          candidate_count: 2,
          total_raised: "5500.00",
          total_ie_support: "100.00",
          total_ie_oppose: "50.00",
          has_unknown_candidate_money: false,
          has_unknown_candidate_ie: false,
          rows: [
            {
              candidacy_id: CANDIDACY_ID,
              person_id: PERSON_ID,
              person_name: "Jane Candidate",
              party: "DEM",
              status: "won",
              incumbent_challenge: "I",
              fec_candidate_id: "H0NC01001",
              candidate_id: "22222222-2222-4222-8222-222222222222",
              candidate_name: "CANDIDATE, JANE",
              candidate_slug: "jane-candidate",
              candidate_slug_is_unique: true,
              candidate_identity_is_safe: true,
              has_fec_money: true,
              total_raised: "5000.00",
              total_spent: "2000.00",
              net: "3000.00",
              cash_on_hand: "1000.00",
              summary_source: "fec_weball",
              fundraising_coverage: null,
              ie_support_total: "100.00",
              ie_oppose_total: "50.00",
              ie_support_count: 1,
              ie_oppose_count: 1,
              ie_coverage: null
            },
            {
              candidacy_id: "99999999-9999-4999-8999-999999999999",
              person_id: "88888888-8888-4888-8888-888888888888",
              person_name: "Sam Runner",
              party: "REP",
              status: "filed",
              incumbent_challenge: "C",
              fec_candidate_id: "H0NC01002",
              candidate_id: "33333333-3333-4333-8333-333333333334",
              candidate_name: "RUNNER, SAM",
              candidate_slug: "sam-runner",
              candidate_slug_is_unique: true,
              candidate_identity_is_safe: true,
              has_fec_money: true,
              total_raised: "500.00",
              total_spent: "100.00",
              net: "400.00",
              cash_on_hand: null,
              summary_source: "fec_weball",
              fundraising_coverage: null,
              ie_support_total: "0.00",
              ie_oppose_total: "0.00",
              ie_support_count: 0,
              ie_oppose_count: 0,
              // Measured zero: Schedule E was loaded and named someone else.
              ie_coverage: {
                activity_state: "loaded_zero",
                completeness: "partial",
                basis: "fec_schedule_e_transactions"
              }
            }
          ]
        }
      }
    });

    // The backend owns the cycle for the whole race; a stale route-supplied
    // cycle must never win, or two candidates could be compared across windows.
    expect(rendered.body).not.toContain("?cycle=9999");
    expect(rendered.body).toContain('data-testid="race-money-scoreboard"');
    expect(rendered.body).toContain("<h3>Money in this race</h3>");

    // Answer-first headline, with hand-calculated race totals.
    expect(rendered.body).toContain('data-testid="race-money-summary"');
    expect(rendered.body).toContain("$5,500.00");
    expect(rendered.body).toContain("$100.00");
    expect(rendered.body).toContain("$50.00");
    // Totals are complete here, so no qualifying caveat should appear.
    expect(rendered.body).not.toContain('data-testid="race-money-incomplete-note"');

    // One row per candidate, in the backend's raised-descending order.
    expect(rendered.body.match(/data-testid="race-money-row"/g)).toHaveLength(2);
    expect(rendered.body.indexOf("Jane Candidate")).toBeLessThan(
      rendered.body.indexOf("Sam Runner")
    );

    expect(rendered.body).toContain('href="/candidate/jane-candidate?cycle=2026"');
    expect(rendered.body).toContain("$5,000.00");
    expect(rendered.body).toContain("$2,000.00");
    expect(rendered.body).toContain("$1,000.00");
    expect(rendered.body).toContain("Outside spending supporting");
    expect(rendered.body).toContain("Outside spending opposing");
    // Sam's cash on hand is unknown; it must read as unknown, not as zero.
    expect(rendered.body).toContain("Not available");
  });

  it("renders unknown candidate money as unknown copy and never as $0.00", () => {
    // The honesty rule this page exists to respect. A candidacy with no linked
    // FEC candidate record has UNKNOWN money. Publishing "$0.00 raised" would
    // assert something false about a real campaign, which is exactly the defect
    // the screen specs forbid.
    const rendered = render(DetailPage, {
      props: {
        entityType: "contest",
        data: CONTEST_DETAIL,
        contestCandidateMoney: {
          contest_id: CONTEST_DETAIL.id,
          selected_cycle: 2026,
          candidate_count: 1,
          // The API now sends null here: the single candidacy has no linked FEC
          // candidate, so no known value exists to total.
          total_raised: null,
          total_ie_support: null,
          total_ie_oppose: null,
          has_unknown_candidate_money: true,
          has_unknown_candidate_ie: true,
          rows: [
            {
              candidacy_id: CANDIDACY_ID,
              person_id: PERSON_ID,
              person_name: "Jane Candidate",
              party: "DEM",
              status: "filed",
              incumbent_challenge: "C",
              fec_candidate_id: "H0NC01001",
              candidate_id: null,
              candidate_name: null,
              candidate_slug: null,
              candidate_slug_is_unique: false,
              candidate_identity_is_safe: false,
              has_fec_money: false,
              total_raised: null,
              total_spent: null,
              net: null,
              cash_on_hand: null,
              summary_source: null,
              fundraising_coverage: null,
              ie_support_total: null,
              ie_oppose_total: null,
              ie_support_count: null,
              ie_oppose_count: null,
              ie_coverage: {
                activity_state: "not_loaded",
                completeness: "unknown",
                basis: "no_authoritative_load_evidence"
              }
            }
          ]
        }
      }
    });

    expect(rendered.body).toContain('data-testid="race-money-unavailable"');
    expect(rendered.body).toContain("This is missing coverage, not zero fundraising.");
    // No qualifying note here any more, and its absence is the point: the note
    // reads "these race totals cover only the candidates Civibus has loaded",
    // which implies totals exist. With nothing loaded for anyone there are no
    // totals to qualify, so the headline states the gap outright instead. The
    // outside-spending half already behaves exactly this way.
    expect(rendered.body).not.toContain('data-testid="race-money-incomplete-note"');
    // The outside-spending headline must not invent a figure either: with no
    // linked FEC candidate there is nothing a Schedule E filing could name.
    expect(rendered.body).toContain("outside spending is not available");
    // The fundraising headline must state the gap in words, exactly as the
    // outside-spending half already does.
    expect(rendered.body).toContain("the amount raised is not available");
    // Whole-body now, not scoped to the scoreboard rows. The race-level
    // `total_raised` rollup became nullable (civibus-nzz), so nothing on this
    // page may publish a dollar figure about a race nobody measured. Scoping
    // this to `<dd>` was the concession that let "$0.00 raised" survive in the
    // headline; there is nothing left to concede.
    expect(rendered.body).not.toContain("$0.00");
    // No candidate link at all: there is no FEC candidate row to link to.
    expect(rendered.body).not.toContain('href="/candidate/');
    // The person link still resolves, carrying the race's cycle.
    expect(rendered.body).toContain(`href="/person/${PERSON_ID}?cycle=2026"`);
  });

  it("shows the contest finance empty state when no money response loaded", () => {
    const rendered = render(DetailPage, {
      props: {
        entityType: "contest",
        data: CONTEST_DETAIL,
        contestCandidateMoney: null
      }
    });

    expect(rendered.body).toContain(
      "Candidate finance and outside-spending data are not linked for this contest yet."
    );
    expect(rendered.body).not.toContain('data-testid="race-money-row"');
    expect(rendered.body).not.toContain('data-testid="race-money-summary"');
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

describe("race money bars rendering", () => {
  // One money row per coverage archetype the bars must distinguish:
  // a leader, a trailer, a measured zero, and a never-loaded candidate.
  function buildBarsMoneyRow(
    overrides: Partial<
      import("./contract").ContestCandidateMoneyRow
    > & { person_name: string; person_id: string; total_raised: string | null }
  ): import("./contract").ContestCandidateMoneyRow {
    const measured = overrides.total_raised !== null;
    return {
      candidacy_id: `${overrides.person_id.slice(0, 8)}-0000-4000-8000-000000000000`,
      party: "DEM",
      status: "filed",
      incumbent_challenge: "C",
      fec_candidate_id: measured ? "H0NC01001" : null,
      candidate_id: null,
      candidate_name: null,
      candidate_slug: null,
      candidate_slug_is_unique: false,
      candidate_identity_is_safe: false,
      has_fec_money: measured,
      total_spent: null,
      net: null,
      cash_on_hand: null,
      summary_source: measured ? "fec_weball" : null,
      fundraising_coverage: null,
      ie_support_total: null,
      ie_oppose_total: null,
      ie_support_count: null,
      ie_oppose_count: null,
      ie_coverage: null,
      ...overrides
    };
  }

  const BAR_MONEY_RESPONSE = {
    contest_id: CONTEST_ID,
    selected_cycle: 2026,
    candidate_count: 4,
    total_raised: "5500.00",
    total_ie_support: null,
    total_ie_oppose: null,
    has_unknown_candidate_money: true,
    has_unknown_candidate_ie: true,
    rows: [
      // Wire order is deliberately not rank order: Zoe and Uma first.
      buildBarsMoneyRow({
        person_id: "aaaa1111-1111-4111-8111-111111111111",
        person_name: "Zoe Zilch",
        total_raised: "0.00",
        fundraising_coverage: {
          activity_state: "loaded_zero",
          completeness: "complete",
          basis: "authoritative_load_evidence"
        }
      }),
      buildBarsMoneyRow({
        person_id: "bbbb2222-2222-4222-8222-222222222222",
        person_name: "Uma Unloaded",
        total_raised: null
      }),
      buildBarsMoneyRow({
        person_id: "cccc3333-3333-4333-8333-333333333333",
        person_name: "Jane Candidate",
        total_raised: "5000.00",
        candidate_id: "22222222-2222-4222-8222-222222222222",
        candidate_slug: "jane-candidate",
        candidate_slug_is_unique: true,
        candidate_identity_is_safe: true
      }),
      buildBarsMoneyRow({
        person_id: "dddd4444-4444-4444-8444-444444444444",
        person_name: "Sam Runner",
        total_raised: "500.00"
      })
    ]
  };

  it("renders ranked bars above the table with proportional widths and exact figures", () => {
    const rendered = render(DetailPage, {
      props: {
        entityType: "contest",
        data: CONTEST_DETAIL,
        contestCandidateMoney: BAR_MONEY_RESPONSE
      }
    });

    const barsIndex = rendered.body.indexOf('data-testid="race-money-bars"');
    const tableIndex = rendered.body.indexOf('data-testid="race-money-table-scroll"');
    expect(barsIndex).toBeGreaterThan(-1);
    expect(tableIndex).toBeGreaterThan(-1);
    // The bars are the one-second answer; they come before the data table.
    expect(barsIndex).toBeLessThan(tableIndex);

    const barsBody = rendered.body.slice(barsIndex, tableIndex);
    // Ranked order in the DOM, not wire order: Jane, Sam, Zoe, then the group.
    const janeIndex = barsBody.indexOf("Jane Candidate");
    const samIndex = barsBody.indexOf("Sam Runner");
    const zoeIndex = barsBody.indexOf("Zoe Zilch");
    const umaIndex = barsBody.indexOf("Uma Unloaded");
    expect(janeIndex).toBeGreaterThan(-1);
    expect(janeIndex).toBeLessThan(samIndex);
    expect(samIndex).toBeLessThan(zoeIndex);
    expect(zoeIndex).toBeLessThan(umaIndex);

    // Hand-calculated widths: 5000/5000 and 500/5000.
    expect(barsBody).toContain("--race-bar-width: 100%");
    expect(barsBody).toContain("--race-bar-width: 10%");
    // Direct labels carry the exact figures.
    expect(barsBody).toContain("$5,000.00");
    expect(barsBody).toContain("$500.00");
    // Candidate link keeps the table's slug and cycle rules.
    expect(barsBody).toContain('href="/candidate/jane-candidate?cycle=2026"');
    // Heading sits below the panel h3, holding the heading-order floor.
    expect(barsBody).toContain("<h4");
    expect(barsBody).not.toContain("<h3");
  });

  it("keeps a measured zero visually distinct from money that was never loaded", () => {
    const rendered = render(DetailPage, {
      props: {
        entityType: "contest",
        data: CONTEST_DETAIL,
        contestCandidateMoney: BAR_MONEY_RESPONSE
      }
    });

    const barsIndex = rendered.body.indexOf('data-testid="race-money-bars"');
    const tableIndex = rendered.body.indexOf('data-testid="race-money-table-scroll"');
    const barsBody = rendered.body.slice(barsIndex, tableIndex);

    // Measured zero: a ranked row with a zero-width bar AND the $0.00 figure.
    const zoeRow = barsBody.slice(
      barsBody.indexOf("Zoe Zilch"),
      barsBody.indexOf('data-testid="race-money-bars-not-loaded"')
    );
    expect(zoeRow).toContain("--race-bar-width: 0%");
    expect(zoeRow).toContain("$0.00");

    // Never loaded: words in a distinct group, no bar track, no dollar figure.
    const notLoadedIndex = barsBody.indexOf('data-testid="race-money-bars-not-loaded"');
    expect(notLoadedIndex).toBeGreaterThan(-1);
    const notLoadedBody = barsBody.slice(notLoadedIndex);
    expect(notLoadedBody).toContain("Uma Unloaded");
    expect(notLoadedBody).not.toContain("race-money-bars__track");
    expect(notLoadedBody).not.toContain("$");
    // The group label states the claim in words, before the group.
    expect(barsBody).toContain("not loaded");

    // The decorative track is hidden from assistive tech; the row text
    // (name + figure) is the accessible content.
    expect(barsBody).toContain('aria-hidden="true"');
  });

  it("renders no bars when no candidate has measured fundraising", () => {
    const rendered = render(DetailPage, {
      props: {
        entityType: "contest",
        data: CONTEST_DETAIL,
        contestCandidateMoney: {
          ...BAR_MONEY_RESPONSE,
          total_raised: null,
          candidate_count: 1,
          rows: [
            buildBarsMoneyRow({
              person_id: "bbbb2222-2222-4222-8222-222222222222",
              person_name: "Uma Unloaded",
              total_raised: null
            })
          ]
        }
      }
    });

    expect(rendered.body).not.toContain('data-testid="race-money-bars"');
    // The scoreboard table remains: it carries the unknown-coverage copy.
    expect(rendered.body).toContain('data-testid="race-money-table-scroll"');
  });
});

describe("scrollable regions", () => {
  it("gives every horizontal scroll container a keyboard tab stop", () =>
    expectScrollContainersHaveTabStop(new URL("./DetailPage.svelte", import.meta.url)));
});
