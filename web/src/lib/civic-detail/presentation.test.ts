import { describe, expect, it } from "vitest";
import { vi } from "vitest";
import { buildTrustSection } from "$lib/detail-trust/presentation";
import { OFFICE_LEVELS, type ContestDetailResponse } from "./contract";
import {
  buildCandidacyDetailMetadataFromDetail,
  buildCandidacyDetailPresentation,
  buildContestDetailMetadataFromDetail,
  buildContestDetailPresentation,
  buildOfficeDetailMetadataFromDetail,
  buildOfficeDetailPresentation,
  buildOfficeholdingDetailMetadataFromDetail,
  buildOfficeholdingDetailPresentation
} from "./presentation";

const OFFICE_ID = "33333333-3333-4333-8333-333333333333";
const OFFICEHOLDING_ID = "44444444-4444-4444-8444-444444444444";
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

describe("office detail presentation", () => {
  it("builds office title/facts, current officeholder link rows, incomplete-data warning, and shared trust section", () => {
    const sources = [
      {
        domain: "civics",
        jurisdiction: "us/nc",
        data_source_name: "NC Board of Elections",
        data_source_url: "https://example.org/nc",
        source_record_key: "office-1",
        record_url: "https://example.org/nc/offices/1",
        pull_date: "2026-03-30T00:00:00Z"
      }
    ];

    const viewModel = buildOfficeDetailPresentation({
      id: OFFICE_ID,
      name: "North Carolina Governor",
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
      current_holder_card: {
        officeholding_id: OFFICEHOLDING_ID,
        person_id: PERSON_ID,
        person_name: "Jane Officeholder",
        holder_status: "elected",
        electoral_division_id: ELECTORAL_DIVISION_ID,
        electoral_division_type: "county",
        electoral_division_state: "NC",
        valid_period_lower: "2025-01-01",
        valid_period_upper: null,
        date_precision: "day"
      },
      officeholding_timeline: [],
      recent_contests: [],
      selected_electoral_division_id: null,
      selected_electoral_division_type: null,
      selected_electoral_division_state: null,
      incomplete_data_states: ["no_officeholder"],
      sources
    });

    expect(viewModel.title).toBe("North Carolina Governor");
    expect(viewModel.factRows).toEqual([
      { label: "Name", value: "North Carolina Governor" },
      { label: "Title", value: "Governor" },
      { label: "Office level", value: "State" },
      { label: "State", value: "NC" },
      { label: "Elected", value: "Yes" },
      { label: "Number of seats", value: "1" }
    ]);
    expect(viewModel.officeholderRows).toEqual([
      {
        id: OFFICEHOLDING_ID,
        personName: "Jane Officeholder",
        holderStatus: "elected",
        personHref: `/person/${PERSON_ID}`,
        officeholdingHref: `/officeholding/${OFFICEHOLDING_ID}`,
        linkAriaLabel: "View officeholding detail for Jane Officeholder"
      }
    ]);
    expect(viewModel.incompleteDataWarning).toBe(
      "Current officeholder data is incomplete for this office."
    );
    expect(viewModel.trustSection).toEqual(buildTrustSection(sources));
    expect(viewModel.sectionOrder).toEqual([
      "summary",
      "trust",
      "metrics",
      "records",
      "caveats"
    ]);
    expect(viewModel.keyMetricRows).toEqual([
      { label: "Current officeholders", value: "1" }
    ]);
  });

  it("maps every allowed office_level literal to exact Office level copy with unknown fallback", () => {
    const expectedByLevel = {
      federal: "Federal",
      state: "State",
      county: "County",
      municipal: "Municipal",
      judicial: "Judicial",
      school_board: "School board",
      special_district: "Special district"
    } as const;

    for (const officeLevel of OFFICE_LEVELS) {
      const viewModel = buildOfficeDetailPresentation({
        id: OFFICE_ID,
        name: "Any Office",
        office_level: officeLevel,
        title: null,
        jurisdiction_id: null,
        state: null,
        is_elected: true,
        number_of_seats: 1,
        current_officeholders: [],
        current_holder_card: null,
        officeholding_timeline: [],
        recent_contests: [],
        selected_electoral_division_id: null,
        selected_electoral_division_type: null,
        selected_electoral_division_state: null,
        incomplete_data_states: [],
        sources: []
      });

      const officeLevelRow = viewModel.factRows.find((row) => row.label === "Office level");
      expect(officeLevelRow?.value).toBe(expectedByLevel[officeLevel]);
    }

    const fallbackViewModel = buildOfficeDetailPresentation({
      id: OFFICE_ID,
      name: "Unknown Office",
      office_level: "regional" as never,
      title: null,
      jurisdiction_id: null,
      state: null,
      is_elected: true,
      number_of_seats: 1,
      current_officeholders: [],
      current_holder_card: null,
      officeholding_timeline: [],
      recent_contests: [],
      selected_electoral_division_id: null,
      selected_electoral_division_type: null,
      selected_electoral_division_state: null,
      incomplete_data_states: [],
      sources: []
    });
    const fallbackRow = fallbackViewModel.factRows.find((row) => row.label === "Office level");
    expect(fallbackRow?.value).toBe("Regional");
  });

  it("emits next-step officeholder empty-state copy while preserving incomplete-data warning as caveat content", () => {
    const viewModel = buildOfficeDetailPresentation({
      id: OFFICE_ID,
      name: "North Carolina Governor",
      office_level: "state",
      title: "Governor",
      jurisdiction_id: null,
      state: "NC",
      is_elected: true,
      number_of_seats: 1,
      current_officeholders: [],
      current_holder_card: null,
      officeholding_timeline: [],
      recent_contests: [],
      selected_electoral_division_id: null,
      selected_electoral_division_type: null,
      selected_electoral_division_state: null,
      incomplete_data_states: ["no_officeholder"],
      sources: []
    });

    expect(viewModel.keyMetricRows).toEqual([
      { label: "Current officeholders", value: "0" }
    ]);
    expect(viewModel.officeholderEmptyMessage).toBe(
      "No current officeholders are linked yet. Check back after the next records refresh."
    );
    expect(viewModel.incompleteDataWarning).toBe(
      "Current officeholder data is incomplete for this office."
    );
  });

  it("builds office route metadata from loaded office detail", () => {
    expect(
      buildOfficeDetailMetadataFromDetail({
        id: OFFICE_ID,
        name: "North Carolina Governor",
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
        current_holder_card: {
          officeholding_id: OFFICEHOLDING_ID,
          person_id: PERSON_ID,
          person_name: "Jane Officeholder",
          holder_status: "elected",
          electoral_division_id: ELECTORAL_DIVISION_ID,
          electoral_division_type: "county",
          electoral_division_state: "NC",
          valid_period_lower: "2025-01-01",
          valid_period_upper: null,
          date_precision: "day"
        },
        officeholding_timeline: [],
        recent_contests: [],
        selected_electoral_division_id: null,
        selected_electoral_division_type: null,
        selected_electoral_division_state: null,
        incomplete_data_states: [],
        sources: []
      })
    ).toEqual({
      title: "North Carolina Governor | Office | Civibus",
      description: "Office profile with 1 current officeholder."
    });
  });

  it("builds current-holder card, timeline ordering, recent contests, and map highlight context", () => {
    const viewModel = buildOfficeDetailPresentation({
      id: OFFICE_ID,
      name: "North Carolina Governor",
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
      current_holder_card: {
        officeholding_id: OFFICEHOLDING_ID,
        person_id: PERSON_ID,
        person_name: "Jane Officeholder",
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
          officeholding_id: "old-officeholding",
          person_id: "old-person",
          person_name: "Former Officeholder",
          holder_status: "former",
          electoral_division_id: ELECTORAL_DIVISION_ID,
          electoral_division_type: "county",
          electoral_division_state: "NC",
          valid_period_lower: "2020-01-01",
          valid_period_upper: "2024-01-01",
          date_precision: "day",
          is_active: false,
          term_ended: true
        },
        {
          officeholding_id: OFFICEHOLDING_ID,
          person_id: PERSON_ID,
          person_name: "Jane Officeholder",
          holder_status: "elected",
          electoral_division_id: ELECTORAL_DIVISION_ID,
          electoral_division_type: "county",
          electoral_division_state: "NC",
          valid_period_lower: "2025-01-01",
          valid_period_upper: null,
          date_precision: "day",
          is_active: true,
          term_ended: false
        }
      ],
      recent_contests: [
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
        },
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
        }
      ],
      selected_electoral_division_id: ELECTORAL_DIVISION_ID,
      selected_electoral_division_type: "county",
      selected_electoral_division_state: "NC",
      incomplete_data_states: [],
      sources: []
    });

    expect(viewModel.currentHolderCard?.personName).toBe("Jane Officeholder");
    expect(viewModel.timelineRows.map((row) => row.personName)).toEqual([
      "Jane Officeholder",
      "Former Officeholder"
    ]);
    expect(viewModel.timelineRows[1].termEndEmphasis).toBe("Term ended 2024-01-01");
    // Backend order is preserved verbatim. The API selects five contests by
    // distance from today so the election a reader came for leads; re-sorting
    // here by date would put the furthest-future contest back on top.
    expect(viewModel.recentContestRows.map((row) => row.contestName)).toEqual([
      "Governor 2024 General",
      "Governor 2026 General"
    ]);
    expect(viewModel.recentContestRows[0].contestHref).toBe("/contest/contest-older");
    expect(viewModel.selectedElectoralDivisionId).toBe(ELECTORAL_DIVISION_ID);
  });

  it("does not emit term-ended emphasis for active bounded current-holder terms", () => {
    const viewModel = buildOfficeDetailPresentation({
      id: OFFICE_ID,
      name: "North Carolina Governor",
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
      current_holder_card: {
        officeholding_id: OFFICEHOLDING_ID,
        person_id: PERSON_ID,
        person_name: "Jane Officeholder",
        holder_status: "elected",
        electoral_division_id: ELECTORAL_DIVISION_ID,
        electoral_division_type: "county",
        electoral_division_state: "NC",
        valid_period_lower: "2025-01-01",
        valid_period_upper: "2100-01-01",
        date_precision: "day"
      },
      officeholding_timeline: [],
      recent_contests: [],
      selected_electoral_division_id: null,
      selected_electoral_division_type: null,
      selected_electoral_division_state: null,
      incomplete_data_states: [],
      sources: []
    });

    expect(viewModel.currentHolderCard?.termEndEmphasis).toBeNull();
    expect(viewModel.currentHolderCard?.validThrough).toBe("2100-01-01");
  });

  it("does not emit term-ended emphasis for future bounded timeline rows", () => {
    const viewModel = buildOfficeDetailPresentation({
      id: OFFICE_ID,
      name: "North Carolina Governor",
      office_level: "state",
      title: "Governor",
      jurisdiction_id: null,
      state: "NC",
      is_elected: true,
      number_of_seats: 1,
      current_officeholders: [],
      current_holder_card: null,
      officeholding_timeline: [
        {
          officeholding_id: "future-officeholding",
          person_id: PERSON_ID,
          person_name: "Future Officeholder",
          holder_status: "appointed",
          electoral_division_id: ELECTORAL_DIVISION_ID,
          electoral_division_type: "county",
          electoral_division_state: "NC",
          valid_period_lower: "2100-01-01",
          valid_period_upper: "2104-01-01",
          date_precision: "day",
          is_active: false,
          term_ended: false
        }
      ],
      recent_contests: [],
      selected_electoral_division_id: null,
      selected_electoral_division_type: null,
      selected_electoral_division_state: null,
      incomplete_data_states: [],
      sources: []
    });

    expect(viewModel.timelineRows).toHaveLength(1);
    expect(viewModel.timelineRows[0].termEndEmphasis).toBeNull();
  });

  it("defaults malformed missing officeholding_timeline payloads to an empty timeline", () => {
    const malformedDetail = {
      id: OFFICE_ID,
      name: "North Carolina Governor",
      office_level: "state",
      title: "Governor",
      jurisdiction_id: null,
      state: "NC",
      is_elected: true,
      number_of_seats: 1,
      current_officeholders: [],
      current_holder_card: null,
      recent_contests: [],
      selected_electoral_division_id: null,
      selected_electoral_division_type: null,
      selected_electoral_division_state: null,
      incomplete_data_states: [],
      sources: []
    } as unknown as Parameters<typeof buildOfficeDetailPresentation>[0];

    const viewModel = buildOfficeDetailPresentation(malformedDetail);

    expect(viewModel.timelineRows).toEqual([]);
    expect(viewModel.timelineEmptyMessage).toBe(
      "No officeholding history is linked yet. Check back after the next records refresh."
    );
  });

  it("defaults malformed missing recent_contests payloads to an empty recent-contests section", () => {
    const malformedDetail = {
      id: OFFICE_ID,
      name: "North Carolina Governor",
      office_level: "state",
      title: "Governor",
      jurisdiction_id: null,
      state: "NC",
      is_elected: true,
      number_of_seats: 1,
      current_officeholders: [],
      current_holder_card: null,
      officeholding_timeline: [],
      selected_electoral_division_id: null,
      selected_electoral_division_type: null,
      selected_electoral_division_state: null,
      incomplete_data_states: [],
      sources: []
    } as unknown as Parameters<typeof buildOfficeDetailPresentation>[0];

    const viewModel = buildOfficeDetailPresentation(malformedDetail);

    expect(viewModel.recentContestRows).toEqual([]);
    expect(viewModel.recentContestEmptyMessage).toBe(
      "No recent contests are linked yet. Check back after the next records refresh."
    );
  });

  it("treats malformed missing current_holder_card payloads as no current holder card", () => {
    const malformedDetail = {
      id: OFFICE_ID,
      name: "North Carolina Governor",
      office_level: "state",
      title: "Governor",
      jurisdiction_id: null,
      state: "NC",
      is_elected: true,
      number_of_seats: 1,
      current_officeholders: [],
      officeholding_timeline: [],
      recent_contests: [],
      selected_electoral_division_id: null,
      selected_electoral_division_type: null,
      selected_electoral_division_state: null,
      incomplete_data_states: [],
      sources: []
    } as unknown as Parameters<typeof buildOfficeDetailPresentation>[0];

    const viewModel = buildOfficeDetailPresentation(malformedDetail);

    expect(viewModel.currentHolderCard).toBeNull();
  });

  it("derives a fallback current-holder card from a single current_officeholders row", () => {
    const malformedDetail = {
      id: OFFICE_ID,
      name: "North Carolina Governor",
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
      officeholding_timeline: [],
      recent_contests: [],
      selected_electoral_division_id: null,
      selected_electoral_division_type: null,
      selected_electoral_division_state: null,
      incomplete_data_states: [],
      sources: []
    } as unknown as Parameters<typeof buildOfficeDetailPresentation>[0];

    const viewModel = buildOfficeDetailPresentation(malformedDetail);

    expect(viewModel.currentHolderCard).toMatchObject({
      officeholdingId: OFFICEHOLDING_ID,
      personName: "Jane Officeholder",
      personHref: `/person/${PERSON_ID}`,
      officeholdingHref: `/officeholding/${OFFICEHOLDING_ID}`,
      holderStatus: "elected",
      validFrom: "—",
      validThrough: "—",
      termEndEmphasis: null
    });
  });

  it("keeps term-ended emphasis tied to backend row state, not frontend wall-clock date", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("1900-01-01T00:00:00.000Z"));
    try {
      const viewModel = buildOfficeDetailPresentation({
        id: OFFICE_ID,
        name: "North Carolina Governor",
        office_level: "state",
        title: "Governor",
        jurisdiction_id: null,
        state: "NC",
        is_elected: true,
        number_of_seats: 1,
        current_officeholders: [],
        current_holder_card: null,
        officeholding_timeline: [
          {
            officeholding_id: "former-officeholding",
            person_id: PERSON_ID,
            person_name: "Former Officeholder",
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
        recent_contests: [],
        selected_electoral_division_id: null,
        selected_electoral_division_type: null,
        selected_electoral_division_state: null,
        incomplete_data_states: [],
        sources: []
      });

      expect(viewModel.timelineRows).toHaveLength(1);
      expect(viewModel.timelineRows[0].termEndEmphasis).toBe("Term ended 2024-01-01");
    } finally {
      vi.useRealTimers();
    }
  });

  it("preserves term-end emphasis for ended bounded timeline rows whose holder_status is not 'former'", () => {
    const viewModel = buildOfficeDetailPresentation({
      id: OFFICE_ID,
      name: "North Carolina Governor",
      office_level: "state",
      title: "Governor",
      jurisdiction_id: null,
      state: "NC",
      is_elected: true,
      number_of_seats: 1,
      current_officeholders: [],
      current_holder_card: null,
      officeholding_timeline: [
        {
          officeholding_id: "ended-elected-officeholding",
          person_id: PERSON_ID,
          person_name: "Ended Elected Officeholder",
          holder_status: "elected",
          electoral_division_id: ELECTORAL_DIVISION_ID,
          electoral_division_type: "county",
          electoral_division_state: "NC",
          valid_period_lower: "2018-01-01",
          valid_period_upper: "2022-01-01",
          date_precision: "day",
          is_active: false,
          term_ended: true
        },
        {
          officeholding_id: "ended-appointed-officeholding",
          person_id: "another-person",
          person_name: "Ended Appointed Officeholder",
          holder_status: "appointed",
          electoral_division_id: ELECTORAL_DIVISION_ID,
          electoral_division_type: "county",
          electoral_division_state: "NC",
          valid_period_lower: "2014-01-01",
          valid_period_upper: "2018-01-01",
          date_precision: "day",
          is_active: false,
          term_ended: true
        }
      ],
      recent_contests: [],
      selected_electoral_division_id: null,
      selected_electoral_division_type: null,
      selected_electoral_division_state: null,
      incomplete_data_states: [],
      sources: []
    });

    expect(viewModel.timelineRows.map((row) => row.termEndEmphasis)).toEqual([
      "Term ended 2022-01-01",
      "Term ended 2018-01-01"
    ]);
    expect(viewModel.timelineRows.map((row) => row.holderStatus)).toEqual([
      "elected",
      "appointed"
    ]);
  });
});

describe("contest detail presentation", () => {
  it("builds title/facts/candidacy rows, delegates trust section, and computes key metrics", () => {
    const sources = [
      {
        domain: "civics",
        jurisdiction: "us/nc",
        data_source_name: "NC Board of Elections",
        data_source_url: "https://example.org/nc",
        source_record_key: "contest-1",
        record_url: "https://example.org/nc/contests/1",
        pull_date: "2026-03-30T00:00:00Z"
      }
    ];

    const viewModel = buildContestDetailPresentation({
      id: CONTEST_ID,
      name: "Governor 2026 General Election",
      election_date: "2026-11-03",
      election_type: "general",
      office_id: OFFICE_ID,
      electoral_division_id: ELECTORAL_DIVISION_ID,
      number_of_seats: 1,
      filing_deadline: "2026-09-01",
      is_partisan: true,
      candidate_list_incomplete: false,
      candidacies: [
        {
          candidacy_id: CANDIDACY_ID,
          person_id: PERSON_ID,
          person_name: "Jane Officeholder",
          party: "DEM",
          status: "filed",
          incumbent_challenge: "I"
        }
      ],
      sources
    });

    expect(viewModel.title).toBe("Governor 2026 General Election");
    expect(viewModel.factRows).toEqual([
      { label: "Name", value: "Governor 2026 General Election" },
      { label: "Election date", value: "2026-11-03" },
      { label: "Election type", value: "general" },
      { label: "Filing deadline", value: "2026-09-01" },
      { label: "Partisan", value: "Yes" },
      { label: "Number of seats", value: "1" }
    ]);
    expect(viewModel.keyMetricRows).toEqual([{ label: "Candidacies", value: "1" }]);
    expect(viewModel.officeHref).toBe(`/office/${OFFICE_ID}`);
    expect(viewModel.candidacyRows).toEqual([
      {
        id: CANDIDACY_ID,
        personId: PERSON_ID,
        personName: "Jane Officeholder",
        personHref: `/person/${PERSON_ID}`,
        candidacyHref: `/candidacy/${CANDIDACY_ID}`,
        party: "DEM",
        status: "filed",
        incumbentChallenge: "I",
        isWinner: false,
        linkAriaLabel: "View candidacy detail for Jane Officeholder"
      }
    ]);
    expect(viewModel.candidacyEmptyMessage).toBeNull();
    expect(viewModel.candidateListWarning).toBeNull();
    expect(viewModel.trustSection).toEqual(buildTrustSection(sources));
    expect(viewModel.resultWinnerPersonName).toBeNull();
    expect(viewModel.resultWinnerPersonHref).toBeNull();
    expect(viewModel.resultWinnerCandidacyHref).toBeNull();
    expect(viewModel.resultEmptyMessage).toBe(
      "Results are not yet available for this contest."
    );
    expect(viewModel.financeRows).toEqual([]);
    expect(viewModel.financeEmptyMessage).toBe(
      "Candidate finance and outside-spending data are not linked for this contest yet."
    );
  });

  it("emits candidacy empty-state and candidate-list warning when coverage is incomplete", () => {
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
      candidate_list_incomplete: true,
      candidacies: [],
      sources: []
    });

    expect(viewModel.keyMetricRows).toEqual([{ label: "Candidacies", value: "0" }]);
    expect(viewModel.candidacyEmptyMessage).toBe(
      "No candidacies are linked yet. Check back after the next records refresh."
    );
    expect(viewModel.candidateListWarning).toBe(
      "Candidate list coverage is incomplete for this contest."
    );
  });

  // Local fixture: this file builds contest payloads inline elsewhere, so the
  // race-scoreboard tests carry their own minimal, explicit contest record.
  const CONTEST_DETAIL: ContestDetailResponse = {
    id: CONTEST_ID,
    name: "North Carolina 1st Congressional District — 2026 General Election",
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
        candidacy_id: CANDIDACY_ID,
        person_id: PERSON_ID,
        person_name: "Jane Candidate",
        party: "DEM",
        status: "filed",
        incumbent_challenge: "C"
      }
    ],
    sources: []
  };

  it("builds the race scoreboard from the batched money response in backend order", () => {
    const presentation = buildContestDetailPresentation(
      {
        ...CONTEST_DETAIL,
        result_winner_candidacy_id: CANDIDACY_ID,
        result_winner_person_id: PERSON_ID,
        result_winner_person_name: "Jane Candidate"
      },
      {
        // A deliberately wrong route cycle: the backend's cycle must win, since
        // it is the one every row in the response was actually computed for.
        selectedCycle: 9999,
        candidateMoney: {
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
              // Schedule E was loaded for this cycle and named somebody else:
              // this zero is measured, so it must keep rendering as $0.00.
              ie_coverage: {
                activity_state: "loaded_zero",
                completeness: "partial",
                basis: "fec_schedule_e_transactions"
              }
            }
          ]
        }
      }
    );

    expect(presentation.financeRows.map((row) => row.personName)).toEqual([
      "Jane Candidate",
      "Sam Runner"
    ]);
    expect(presentation.financeRows[0].candidateHref).toBe(
      "/candidate/jane-candidate?cycle=2026"
    );
    expect(presentation.financeRows[0].personHref).toBe(`/person/${PERSON_ID}?cycle=2026`);
    expect(presentation.financeRows[0].financeFacts).toEqual([
      { label: "Raised", value: "$5,000.00" },
      { label: "Spent", value: "$2,000.00" },
      { label: "Cash on hand", value: "$1,000.00" }
    ]);
    expect(presentation.financeRows[0].outsideSpendingFacts).toEqual([
      { label: "Outside spending supporting", value: "$100.00" },
      { label: "Outside spending opposing", value: "$50.00" }
    ]);
    expect(presentation.financeRows[0].moneyUnavailableMessage).toBeNull();
    // Unknown optional value reads as unknown, not as a zero.
    expect(presentation.financeRows[1].financeFacts[2]).toEqual({
      label: "Cash on hand",
      value: "Not available"
    });

    expect(presentation.raceMoneySummary).toEqual({
      candidateCount: 2,
      totalRaised: "$5,500.00",
      fundraisingKnown: true,
      totalOutsideSupport: "$100.00",
      totalOutsideOppose: "$50.00",
      outsideSpendingKnown: true,
      selectedCycle: 2026,
      incompleteNote: null,
      outsideSpendingNote: null
    });
    expect(presentation.financeEmptyMessage).toBeNull();
  });

  it("reports unknown candidate money as unknown and qualifies the race totals", () => {
    const presentation = buildContestDetailPresentation(CONTEST_DETAIL, {
      candidateMoney: {
        contest_id: CONTEST_DETAIL.id,
        selected_cycle: 2026,
        candidate_count: 1,
        total_raised: "0.00",
        total_ie_support: "0.00",
        total_ie_oppose: "0.00",
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
    });

    // No figures at all for an unlinked candidacy: the row carries copy instead.
    expect(presentation.financeRows[0].financeFacts).toEqual([]);
    // Including the outside-spending half. An unlinked candidacy has no FEC
    // candidate ID for a Schedule E filing to name, so "$0.00" would be invented.
    expect(presentation.financeRows[0].outsideSpendingFacts).toEqual([
      { label: "Outside spending supporting", value: "Not available" },
      { label: "Outside spending opposing", value: "Not available" }
    ]);
    expect(presentation.financeRows[0].moneyUnavailableMessage).toContain(
      "missing coverage, not zero fundraising"
    );
    expect(presentation.financeRows[0].candidateHref).toBeNull();
    expect(presentation.raceMoneySummary?.incompleteNote).toContain(
      "only the candidates Civibus has loaded"
    );
  });

  it("separates loaded-zero outside spending from outside spending that was never loaded", () => {
    // Three candidates, three coverage states, one race. The whole feature is
    // that these three render as three different claims.
    const baseRow = {
      party: "DEM",
      status: "filed",
      incumbent_challenge: "C",
      candidate_slug_is_unique: true,
      candidate_identity_is_safe: true,
      has_fec_money: true,
      total_raised: "5000.00",
      total_spent: "2000.00",
      net: "3000.00",
      cash_on_hand: "1000.00",
      summary_source: "fec_weball",
      fundraising_coverage: null
    };
    const presentation = buildContestDetailPresentation(CONTEST_DETAIL, {
      candidateMoney: {
        contest_id: CONTEST_DETAIL.id,
        selected_cycle: 2024,
        candidate_count: 3,
        total_raised: "15000.00",
        total_ie_support: "250.00",
        total_ie_oppose: "100.00",
        has_unknown_candidate_money: false,
        has_unknown_candidate_ie: true,
        rows: [
          {
            ...baseRow,
            candidacy_id: CANDIDACY_ID,
            person_id: PERSON_ID,
            person_name: "Populated Candidate",
            fec_candidate_id: "H0NC01001",
            candidate_id: "22222222-2222-4222-8222-222222222222",
            candidate_name: "CANDIDATE, POPULATED",
            candidate_slug: "populated-candidate",
            ie_support_total: "250.00",
            ie_oppose_total: "100.00",
            ie_support_count: 1,
            ie_oppose_count: 1,
            ie_coverage: null
          },
          {
            ...baseRow,
            candidacy_id: "99999999-9999-4999-8999-999999999991",
            person_id: "88888888-8888-4888-8888-888888888881",
            person_name: "Loaded Zero Candidate",
            fec_candidate_id: "H0NC01002",
            candidate_id: "33333333-3333-4333-8333-333333333331",
            candidate_name: "CANDIDATE, LOADED ZERO",
            candidate_slug: "loaded-zero-candidate",
            ie_support_total: "0.00",
            ie_oppose_total: "0.00",
            ie_support_count: 0,
            ie_oppose_count: 0,
            ie_coverage: {
              activity_state: "loaded_zero",
              completeness: "partial",
              basis: "fec_schedule_e_transactions"
            }
          },
          {
            ...baseRow,
            candidacy_id: "99999999-9999-4999-8999-999999999992",
            person_id: "88888888-8888-4888-8888-888888888882",
            person_name: "Not Loaded Candidate",
            fec_candidate_id: "H0NC01003",
            candidate_id: "33333333-3333-4333-8333-333333333332",
            candidate_name: "CANDIDATE, NOT LOADED",
            candidate_slug: "not-loaded-candidate",
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
    });

    const [populated, loadedZero, notLoaded] = presentation.financeRows;

    expect(populated.outsideSpendingFacts).toEqual([
      { label: "Outside spending supporting", value: "$250.00" },
      { label: "Outside spending opposing", value: "$100.00" }
    ]);
    // A measured zero stays a zero. Turning this into "Not available" would be
    // the same dishonesty pointing the other way.
    expect(loadedZero.outsideSpendingFacts).toEqual([
      { label: "Outside spending supporting", value: "$0.00" },
      { label: "Outside spending opposing", value: "$0.00" }
    ]);
    expect(notLoaded.outsideSpendingFacts).toEqual([
      { label: "Outside spending supporting", value: "Not available" },
      { label: "Outside spending opposing", value: "Not available" }
    ]);
    expect(
      notLoaded.outsideSpendingFacts.map((fact) => fact.value).join(" ")
    ).not.toContain("$");

    // Partially known race: the totals exist but cover only two of three
    // candidates, so they must carry the qualifying caveat.
    expect(presentation.raceMoneySummary?.outsideSpendingKnown).toBe(true);
    expect(presentation.raceMoneySummary?.totalOutsideSupport).toBe("$250.00");
    expect(presentation.raceMoneySummary?.outsideSpendingNote).toContain(
      "missing coverage, not an absence of outside spending"
    );
  });

  it("reads a race with no loaded outside spending as unknown, not as zero", () => {
    const presentation = buildContestDetailPresentation(CONTEST_DETAIL, {
      candidateMoney: {
        contest_id: CONTEST_DETAIL.id,
        selected_cycle: 2024,
        candidate_count: 1,
        total_raised: "5000.00",
        total_ie_support: null,
        total_ie_oppose: null,
        has_unknown_candidate_money: false,
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
    });

    // The headline is the most prominent figure on a race page. "$0.00" here is
    // the Sherrod Brown defect: the most expensive race in US history reading
    // as no outside spending at all.
    expect(presentation.raceMoneySummary?.totalOutsideSupport).toBe("Not available");
    expect(presentation.raceMoneySummary?.totalOutsideOppose).toBe("Not available");
    expect(presentation.raceMoneySummary?.totalRaised).toBe("$5,000.00");
    expect(presentation.raceMoneySummary?.outsideSpendingKnown).toBe(false);
    // Nothing is known, so there is no partial total to qualify: the summary
    // line states the gap outright instead of carrying a weaker caveat.
    expect(presentation.raceMoneySummary?.outsideSpendingNote).toBeNull();
  });

  it("reads a race with no loaded fundraising as unknown, not as zero", () => {
    const presentation = buildContestDetailPresentation(CONTEST_DETAIL, {
      candidateMoney: {
        contest_id: CONTEST_DETAIL.id,
        selected_cycle: 2024,
        candidate_count: 1,
        // No candidacy in the race resolved to a cf.candidate row, so there is
        // no known value to total. The API now says so instead of flooring the
        // sum of an empty set at "0.00".
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
            fec_candidate_id: null,
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
            ie_coverage: null
          }
        ]
      }
    });

    // The headline figure is the single most-read claim on a race page.
    // "$0.00 raised" about a race nobody measured is the fundraising twin of
    // the outside-spending defect above.
    expect(presentation.raceMoneySummary?.totalRaised).toBe("Not available");
    expect(presentation.raceMoneySummary?.fundraisingKnown).toBe(false);
    // Nothing is known, so there is no partial total to qualify: the headline
    // states the gap outright rather than adding a weaker caveat beneath a
    // figure it should not have printed.
    expect(presentation.raceMoneySummary?.incompleteNote).toBeNull();
  });

  it("keeps a measured zero race total as $0.00 rather than reading it as unknown", () => {
    const presentation = buildContestDetailPresentation(CONTEST_DETAIL, {
      candidateMoney: {
        contest_id: CONTEST_DETAIL.id,
        selected_cycle: 2024,
        candidate_count: 1,
        // Loaded, and genuinely nothing raised. This zero is a measurement.
        total_raised: "0.00",
        total_ie_support: "0.00",
        total_ie_oppose: "0.00",
        has_unknown_candidate_money: false,
        has_unknown_candidate_ie: false,
        rows: [
          {
            candidacy_id: CANDIDACY_ID,
            person_id: PERSON_ID,
            person_name: "Jane Candidate",
            party: "DEM",
            status: "filed",
            incumbent_challenge: "C",
            fec_candidate_id: "H0NC01001",
            candidate_id: "22222222-2222-4222-8222-222222222222",
            candidate_name: "CANDIDATE, JANE",
            candidate_slug: "jane-candidate",
            candidate_slug_is_unique: true,
            candidate_identity_is_safe: true,
            has_fec_money: true,
            total_raised: "0.00",
            total_spent: "0.00",
            net: "0.00",
            cash_on_hand: "0.00",
            summary_source: "fec_weball",
            fundraising_coverage: {
              activity_state: "loaded_zero",
              completeness: "partial",
              basis: "qualifying_transactions"
            },
            ie_support_total: "0.00",
            ie_oppose_total: "0.00",
            ie_support_count: 0,
            ie_oppose_count: 0,
            ie_coverage: {
              activity_state: "loaded_zero",
              completeness: "partial",
              basis: "fec_schedule_e_transactions"
            }
          }
        ]
      }
    });

    // Suppressing a measured zero would be the same dishonesty inverted: it
    // would hide a fact the product actually established and sourced.
    expect(presentation.raceMoneySummary?.totalRaised).toBe("$0.00");
    expect(presentation.raceMoneySummary?.fundraisingKnown).toBe(true);
    expect(presentation.raceMoneySummary?.totalOutsideSupport).toBe("$0.00");
    expect(presentation.raceMoneySummary?.outsideSpendingKnown).toBe(true);
  });

  it("falls back to the contest finance empty state when no money response loaded", () => {
    const presentation = buildContestDetailPresentation(CONTEST_DETAIL, {
      candidateMoney: null,
      selectedCycle: 2024
    });

    expect(presentation.financeRows).toEqual([]);
    expect(presentation.raceMoneySummary).toBeNull();
    expect(presentation.financeEmptyMessage).toBe(
      "Candidate finance and outside-spending data are not linked for this contest yet."
    );
    // With no backend cycle, the route-supplied one still routes person links.
    expect(presentation.candidacyRows[0].personHref).toBe(`/person/${PERSON_ID}?cycle=2024`);
  });

  it("builds contest route metadata from loaded contest detail", () => {
    expect(
      buildContestDetailMetadataFromDetail({
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
            person_name: "Jane Officeholder",
            party: "DEM",
            status: "filed",
            incumbent_challenge: "I"
          }
        ],
        sources: []
      })
    ).toEqual({
      title: "Governor 2026 General Election | Contest | Civibus",
      description: "Contest profile with 1 candidacy."
    });
  });
});

describe("candidacy detail presentation", () => {
  it("builds title/facts for person linkage, filing metadata, and trust delegation", () => {
    const sources = [
      {
        domain: "civics",
        jurisdiction: "us/nc",
        data_source_name: "NC Board of Elections",
        data_source_url: "https://example.org/nc",
        source_record_key: "candidacy-1",
        record_url: "https://example.org/nc/candidacies/1",
        pull_date: "2026-03-30T00:00:00Z"
      }
    ];

    const viewModel = buildCandidacyDetailPresentation({
      id: CANDIDACY_ID,
      person_id: PERSON_ID,
      person_name: "Jane Officeholder",
      contest_id: CONTEST_ID,
      party: "DEM",
      filing_date: "2026-02-01",
      status: "filed",
      incumbent_challenge: "I",
      candidate_number: "17",
      sources
    });

    expect(viewModel.title).toBe("Jane Officeholder candidacy");
    expect(viewModel.factRows).toEqual([
      { label: "Person", value: "Jane Officeholder" },
      { label: "Party", value: "DEM" },
      { label: "Filing date", value: "2026-02-01" },
      { label: "Status", value: "filed" },
      { label: "Incumbent/challenger", value: "I" },
      { label: "Candidate number", value: "17" }
    ]);
    expect(viewModel.personHref).toBe(`/person/${PERSON_ID}`);
    expect(viewModel.contestHref).toBe(`/contest/${CONTEST_ID}`);
    expect(viewModel.keyMetricRows).toEqual([{ label: "Has filing date", value: "Yes" }]);
    expect(viewModel.statusEmptyMessage).toBeNull();
    expect(viewModel.trustSection).toEqual(buildTrustSection(sources));
  });

  it("emits status empty-state when candidacy status is not available", () => {
    const viewModel = buildCandidacyDetailPresentation({
      id: CANDIDACY_ID,
      person_id: PERSON_ID,
      person_name: "Jane Officeholder",
      contest_id: CONTEST_ID,
      party: null,
      filing_date: null,
      status: null,
      incumbent_challenge: null,
      candidate_number: null,
      sources: []
    });

    expect(viewModel.factRows).toEqual([
      { label: "Person", value: "Jane Officeholder" },
      { label: "Party", value: "—" },
      { label: "Filing date", value: "—" },
      { label: "Status", value: "—" },
      { label: "Incumbent/challenger", value: "—" },
      { label: "Candidate number", value: "—" }
    ]);
    expect(viewModel.keyMetricRows).toEqual([{ label: "Has filing date", value: "No" }]);
    expect(viewModel.statusEmptyMessage).toBe(
      "Status is not available for this candidacy yet."
    );
  });

  it("builds candidacy route metadata from loaded candidacy detail", () => {
    expect(
      buildCandidacyDetailMetadataFromDetail({
        id: CANDIDACY_ID,
        person_id: PERSON_ID,
        person_name: "Jane Officeholder",
        contest_id: CONTEST_ID,
        party: "DEM",
        filing_date: "2026-02-01",
        status: "filed",
        incumbent_challenge: "I",
        candidate_number: "17",
        sources: []
      })
    ).toEqual({
      title: "Jane Officeholder | Candidacy | Civibus",
      description: "Candidacy profile for Jane Officeholder."
    });
  });
});

describe("officeholding detail presentation", () => {
  it("builds title/facts for person linkage, status, valid period, and trust delegation", () => {
    const sources = [
      {
        domain: "civics",
        jurisdiction: "us/nc",
        data_source_name: "NC Board of Elections",
        data_source_url: "https://example.org/nc",
        source_record_key: "officeholding-1",
        record_url: "https://example.org/nc/officeholdings/1",
        pull_date: "2026-03-30T00:00:00Z"
      }
    ];

    const viewModel = buildOfficeholdingDetailPresentation({
      id: OFFICEHOLDING_ID,
      person_id: PERSON_ID,
      person_name: "Jane Officeholder",
      office_id: OFFICE_ID,
      electoral_division_id: ELECTORAL_DIVISION_ID,
      holder_status: "elected",
      valid_period_lower: "2025-01-01",
      valid_period_upper: null,
      date_precision: "day",
      sources
    });

    expect(viewModel.title).toBe("Jane Officeholder officeholding");
    expect(viewModel.factRows).toEqual([
      { label: "Person", value: "Jane Officeholder" },
      { label: "Holder status", value: "elected" },
      { label: "Valid from", value: "2025-01-01" },
      { label: "Valid through", value: "—" },
      { label: "Date precision", value: "day" }
    ]);
    expect(viewModel.personHref).toBe(`/person/${PERSON_ID}`);
    expect(viewModel.officeHref).toBe(`/office/${OFFICE_ID}`);
    expect(viewModel.keyMetricRows).toEqual([{ label: "Active officeholding", value: "Yes" }]);
    expect(viewModel.validPeriodEmptyMessage).toBeNull();
    expect(viewModel.trustSection).toEqual(buildTrustSection(sources));
  });

  it("emits valid-period empty-state when both period bounds are unavailable", () => {
    const viewModel = buildOfficeholdingDetailPresentation({
      id: OFFICEHOLDING_ID,
      person_id: PERSON_ID,
      person_name: "Jane Officeholder",
      office_id: OFFICE_ID,
      electoral_division_id: null,
      holder_status: "former",
      valid_period_lower: null,
      valid_period_upper: null,
      date_precision: "day",
      sources: []
    });

    expect(viewModel.factRows).toEqual([
      { label: "Person", value: "Jane Officeholder" },
      { label: "Holder status", value: "former" },
      { label: "Valid from", value: "—" },
      { label: "Valid through", value: "—" },
      { label: "Date precision", value: "day" }
    ]);
    expect(viewModel.keyMetricRows).toEqual([{ label: "Active officeholding", value: "No" }]);
    expect(viewModel.validPeriodEmptyMessage).toBe(
      "No valid-period bounds are available for this officeholding."
    );
  });

  it("does not mark former officeholdings as active when their period is still open-ended", () => {
    const viewModel = buildOfficeholdingDetailPresentation({
      id: OFFICEHOLDING_ID,
      person_id: PERSON_ID,
      person_name: "Jane Officeholder",
      office_id: OFFICE_ID,
      electoral_division_id: null,
      holder_status: "former",
      valid_period_lower: "2025-01-01",
      valid_period_upper: null,
      date_precision: "day",
      sources: []
    });

    expect(viewModel.keyMetricRows).toEqual([{ label: "Active officeholding", value: "No" }]);
    expect(viewModel.validPeriodEmptyMessage).toBeNull();
  });

  it("builds officeholding route metadata from loaded officeholding detail", () => {
    expect(
      buildOfficeholdingDetailMetadataFromDetail({
        id: OFFICEHOLDING_ID,
        person_id: PERSON_ID,
        person_name: "Jane Officeholder",
        office_id: OFFICE_ID,
        electoral_division_id: null,
        holder_status: "elected",
        valid_period_lower: "2025-01-01",
        valid_period_upper: null,
        date_precision: "day",
        sources: []
      })
    ).toEqual({
      title: "Jane Officeholder | Officeholding | Civibus",
      description: "Officeholding profile for Jane Officeholder."
    });
  });
});
