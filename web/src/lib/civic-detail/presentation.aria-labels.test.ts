import { describe, expect, it } from "vitest";
import {
  buildContestDetailPresentation,
  buildOfficeDetailPresentation
} from "./presentation";

const OFFICE_ID = "33333333-3333-4333-8333-333333333333";
const OFFICEHOLDING_ID = "44444444-4444-4444-8444-444444444444";
const CONTEST_ID = "77777777-7777-4777-8777-777777777777";
const PERSON_ID = "11111111-1111-4111-8111-111111111111";

describe("duplicate-name row aria-label disambiguation", () => {
  it("appends holder status to officeholder aria labels when person names collide", () => {
    const viewModel = buildOfficeDetailPresentation({
      id: OFFICE_ID,
      name: "NC Governor",
      office_level: "state",
      title: "Governor",
      jurisdiction_id: null,
      state: "NC",
      is_elected: true,
      number_of_seats: 2,
      current_officeholders: [
        {
          officeholding_id: "oh-aaa",
          person_id: "p-aaa",
          person_name: "Jane Smith",
          holder_status: "elected"
        },
        {
          officeholding_id: "oh-bbb",
          person_id: "p-bbb",
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
    });

    expect(viewModel.officeholderRows[0].linkAriaLabel).toBe(
      "View officeholding detail for Jane Smith, elected"
    );
    expect(viewModel.officeholderRows[1].linkAriaLabel).toBe(
      "View officeholding detail for Jane Smith, appointed"
    );
  });

  it("appends index when officeholder name and status both collide", () => {
    const viewModel = buildOfficeDetailPresentation({
      id: OFFICE_ID,
      name: "NC Governor",
      office_level: "state",
      title: "Governor",
      jurisdiction_id: null,
      state: "NC",
      is_elected: true,
      number_of_seats: 2,
      current_officeholders: [
        {
          officeholding_id: "oh-aaa",
          person_id: "p-aaa",
          person_name: "Jane Smith",
          holder_status: "elected"
        },
        {
          officeholding_id: "oh-bbb",
          person_id: "p-bbb",
          person_name: "Jane Smith",
          holder_status: "elected"
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
    });

    expect(viewModel.officeholderRows[0].linkAriaLabel).toBe(
      "View officeholding detail for Jane Smith, elected (#1)"
    );
    expect(viewModel.officeholderRows[1].linkAriaLabel).toBe(
      "View officeholding detail for Jane Smith, elected (#2)"
    );
  });

  it("uses plain name for officeholders with unique names", () => {
    const viewModel = buildOfficeDetailPresentation({
      id: OFFICE_ID,
      name: "NC Governor",
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
          person_name: "Jane Officeholder",
          holder_status: "elected"
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
    });

    expect(viewModel.officeholderRows[0].linkAriaLabel).toBe(
      "View officeholding detail for Jane Officeholder"
    );
  });

  it("appends party to candidacy aria labels when person names collide", () => {
    const viewModel = buildContestDetailPresentation({
      id: CONTEST_ID,
      name: "Governor 2026 General Election",
      election_date: "2026-11-03",
      election_type: "general",
      office_id: OFFICE_ID,
      electoral_division_id: null,
      number_of_seats: 1,
      filing_deadline: null,
      is_partisan: true,
      candidate_list_incomplete: false,
      candidacies: [
        {
          candidacy_id: "c-aaa",
          person_id: "p-aaa",
          person_name: "Jane Smith",
          party: "DEM",
          status: "filed",
          incumbent_challenge: "I"
        },
        {
          candidacy_id: "c-bbb",
          person_id: "p-bbb",
          person_name: "Jane Smith",
          party: "REP",
          status: "filed",
          incumbent_challenge: "C"
        }
      ],
      sources: []
    });

    expect(viewModel.candidacyRows[0].linkAriaLabel).toBe(
      "View candidacy detail for Jane Smith, DEM"
    );
    expect(viewModel.candidacyRows[1].linkAriaLabel).toBe(
      "View candidacy detail for Jane Smith, REP"
    );
  });

  it("appends index when candidacy name and party both collide", () => {
    const viewModel = buildContestDetailPresentation({
      id: CONTEST_ID,
      name: "Governor 2026 General Election",
      election_date: "2026-11-03",
      election_type: "general",
      office_id: OFFICE_ID,
      electoral_division_id: null,
      number_of_seats: 1,
      filing_deadline: null,
      is_partisan: true,
      candidate_list_incomplete: false,
      candidacies: [
        {
          candidacy_id: "c-aaa",
          person_id: "p-aaa",
          person_name: "Jane Smith",
          party: "DEM",
          status: "filed",
          incumbent_challenge: "I"
        },
        {
          candidacy_id: "c-bbb",
          person_id: "p-bbb",
          person_name: "Jane Smith",
          party: "DEM",
          status: "qualified",
          incumbent_challenge: "C"
        }
      ],
      sources: []
    });

    expect(viewModel.candidacyRows[0].linkAriaLabel).toBe(
      "View candidacy detail for Jane Smith, DEM (#1)"
    );
    expect(viewModel.candidacyRows[1].linkAriaLabel).toBe(
      "View candidacy detail for Jane Smith, DEM (#2)"
    );
  });

  it("handles null party in candidacy disambiguation with fallback text", () => {
    const viewModel = buildContestDetailPresentation({
      id: CONTEST_ID,
      name: "Governor 2026 General Election",
      election_date: null,
      election_type: "general",
      office_id: OFFICE_ID,
      electoral_division_id: null,
      number_of_seats: 1,
      filing_deadline: null,
      is_partisan: false,
      candidate_list_incomplete: false,
      candidacies: [
        {
          candidacy_id: "c-aaa",
          person_id: "p-aaa",
          person_name: "Jane Smith",
          party: null,
          status: "filed",
          incumbent_challenge: null
        },
        {
          candidacy_id: "c-bbb",
          person_id: "p-bbb",
          person_name: "Jane Smith",
          party: null,
          status: "qualified",
          incumbent_challenge: null
        }
      ],
      sources: []
    });

    expect(viewModel.candidacyRows[0].linkAriaLabel).toBe(
      "View candidacy detail for Jane Smith, no party (#1)"
    );
    expect(viewModel.candidacyRows[1].linkAriaLabel).toBe(
      "View candidacy detail for Jane Smith, no party (#2)"
    );
  });

  it("appends winner context to the matching candidacy aria label", () => {
    const viewModel = buildContestDetailPresentation({
      id: CONTEST_ID,
      name: "Governor 2026 General Election",
      election_date: "2026-11-03",
      election_type: "general",
      office_id: OFFICE_ID,
      electoral_division_id: null,
      number_of_seats: 1,
      filing_deadline: null,
      is_partisan: true,
      candidate_list_incomplete: false,
      result_winner_candidacy_id: "c-aaa",
      result_winner_person_id: "p-aaa",
      result_winner_person_name: "Jane Smith",
      candidacies: [
        {
          candidacy_id: "c-aaa",
          person_id: "p-aaa",
          person_name: "Jane Smith",
          party: "DEM",
          status: "won",
          incumbent_challenge: "I"
        },
        {
          candidacy_id: "c-bbb",
          person_id: "p-bbb",
          person_name: "Jane Smith",
          party: "REP",
          status: "qualified",
          incumbent_challenge: "C"
        }
      ],
      sources: []
    });

    expect(viewModel.candidacyRows[0].linkAriaLabel).toBe(
      "View candidacy detail for Jane Smith, DEM, winner"
    );
    expect(viewModel.candidacyRows[1].linkAriaLabel).toBe(
      "View candidacy detail for Jane Smith, REP"
    );
  });
});
