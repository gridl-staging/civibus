import { describe, expect, it } from "vitest";
import { vi } from "vitest";
import { buildTrustSection } from "$lib/detail-trust/presentation";
import { OFFICE_LEVELS } from "./contract";
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
    expect(viewModel.recentContestRows.map((row) => row.contestName)).toEqual([
      "Governor 2026 General",
      "Governor 2024 General"
    ]);
    expect(viewModel.recentContestRows[0].contestHref).toBe("/contest/contest-newer");
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

  it("builds winner results and compact selected-cycle candidate finance facts from shared finance formatters", () => {
    const viewModel = buildContestDetailPresentation(
      {
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
        result_winner_candidacy_id: CANDIDACY_ID,
        result_winner_person_id: PERSON_ID,
        result_winner_person_name: "Jane Officeholder",
        candidacies: [
          {
            candidacy_id: CANDIDACY_ID,
            person_id: PERSON_ID,
            person_name: "Jane Officeholder",
            party: "DEM",
            status: "won",
            incumbent_challenge: "I"
          }
        ],
        sources: []
      },
      {
        selectedCycle: 9999,
        candidateFinanceByPersonId: {
          [PERSON_ID]: {
            personId: PERSON_ID,
            candidateHref: "/candidate/jane-officeholder",
            summary: {
              selected_cycle: 2026,
              coverage_start_date: "2025-01-01",
              coverage_end_date: "2026-12-31",
              available_cycles: [2022, 2024, 2026],
              candidate_id: "candidate-1",
              candidate_name: "Jane Officeholder",
              total_raised: "5000.00",
              total_spent: "2000.00",
              net: "3000.00",
              transaction_count: 42,
              itemized_transaction_count: 42,
              cash_on_hand: "1000.00",
              net_self_funding: null,
              summary_source: "derived" as const,
              receipt_source_composition: [],
              selected_cycle_coverage_complete: false,
              can_render_share: false,
              receipt_source_caveats: [],
              coverage: POPULATED_CANDIDATE_MONEY_COVERAGE,
              committees: []
            },
            ieSummary: {
              selected_cycle: 2024,
              coverage_start_date: "2023-01-01",
              coverage_end_date: "2024-12-31",
              available_cycles: [2022, 2024],
              candidate_id: "candidate-1",
              support_total: "100.00",
              oppose_total: "50.00",
              support_count: 1,
              oppose_count: 1,
              top_spenders: [],
              excluded_outlier_count: 0,
              coverage: POPULATED_SCHEDULE_E_COVERAGE
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
    );

    expect(viewModel.resultWinnerPersonName).toBe("Jane Officeholder");
    expect(viewModel.resultWinnerPersonHref).toBe(`/person/${PERSON_ID}?cycle=2026`);
    expect(viewModel.resultWinnerCandidacyHref).toBe(`/candidacy/${CANDIDACY_ID}`);
    expect(viewModel.resultEmptyMessage).toBeNull();
    expect(viewModel.financeEmptyMessage).toBeNull();
    expect(viewModel.candidacyRows[0].isWinner).toBe(true);
    expect(viewModel.candidacyRows[0].personHref).toBe(`/person/${PERSON_ID}?cycle=2026`);
    expect(viewModel.financeRows).toHaveLength(1);
    expect(viewModel.financeRows[0]).toMatchObject({
      personId: PERSON_ID,
      personName: "Jane Officeholder",
      personHref: `/person/${PERSON_ID}?cycle=2026`,
      candidateHref: "/candidate/jane-officeholder?cycle=2026",
      financeFacts: [
        { label: "Selected cycle", value: "2026" },
        { label: "Coverage through", value: "2026-12-31" },
        { label: "Receipts", value: "$5,000.00" },
        { label: "Disbursements", value: "$2,000.00" },
        { label: "Cash on hand", value: "$1,000.00" }
      ],
      outsideSpending: {
        supportTotal: "—",
        opposeTotal: "—",
        supportCountLabel: "—",
        opposeCountLabel: "—",
        emptyMessage:
          "Outside-spending data is not yet available for this candidate. Coverage may be incomplete."
      }
    });
    expect("financeChartSeries" in viewModel.financeRows[0]).toBe(false);
    expect("outsideSpendingChartSeries" in viewModel.financeRows[0]).toBe(false);
    expect(viewModel.financeRows[0].outsideSpendingFigure).toBeNull();
  });

  it("uses IE selected-cycle metadata for contest outside-spending figures when fundraising is missing", () => {
    const viewModel = buildContestDetailPresentation(
      {
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
        result_winner_candidacy_id: CANDIDACY_ID,
        result_winner_person_id: PERSON_ID,
        result_winner_person_name: "Jane Officeholder",
        candidacies: [
          {
            candidacy_id: CANDIDACY_ID,
            person_id: PERSON_ID,
            person_name: "Jane Officeholder",
            party: "DEM",
            status: "won",
            incumbent_challenge: "I"
          }
        ],
        sources: []
      },
      {
        selectedCycle: 9999,
        candidateFinanceByPersonId: {
          [PERSON_ID]: {
            personId: PERSON_ID,
            candidateHref: "/candidate/jane-officeholder",
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
              excluded_outlier_count: 0,
              coverage: LOADED_ZERO_SCHEDULE_E_COVERAGE
            },
            ieTransactions: []
          }
        }
      }
    );

    expect(viewModel.resultWinnerPersonHref).toBe(`/person/${PERSON_ID}?cycle=2024`);
    expect(viewModel.financeRows[0].candidateHref).toBe(
      "/candidate/jane-officeholder?cycle=2024"
    );
    expect(viewModel.financeRows[0].outsideSpendingFigure).toMatchObject({
      cycle: 2024,
      coverageThrough: "2024-10-15",
      rows: [
        { id: "support", amount: 0, transactionCount: 0 },
        { id: "oppose", amount: 0, transactionCount: 0 }
      ]
    });
  });

  it("preserves route-selected cycle links when contest finance sections are empty", () => {
    const viewModel = buildContestDetailPresentation(
      {
        id: CONTEST_ID,
        name: "Governor 2024 General Election",
        election_date: "2024-11-05",
        election_type: "general",
        office_id: OFFICE_ID,
        electoral_division_id: ELECTORAL_DIVISION_ID,
        number_of_seats: 1,
        filing_deadline: "2024-09-01",
        is_partisan: true,
        candidate_list_incomplete: false,
        result_winner_candidacy_id: CANDIDACY_ID,
        result_winner_person_id: PERSON_ID,
        result_winner_person_name: "Jane Officeholder",
        candidacies: [
          {
            candidacy_id: CANDIDACY_ID,
            person_id: PERSON_ID,
            person_name: "Jane Officeholder",
            party: "DEM",
            status: "won",
            incumbent_challenge: "I"
          }
        ],
        sources: []
      },
      {
        selectedCycle: 2024,
        candidateFinanceByPersonId: {
          [PERSON_ID]: {
            personId: PERSON_ID,
            candidateHref: "/candidate/jane-officeholder",
            summary: null,
            ieSummary: null,
            ieTransactions: []
          }
        }
      }
    );

    expect(viewModel.resultWinnerPersonHref).toBe(`/person/${PERSON_ID}?cycle=2024`);
    expect(viewModel.candidacyRows[0].personHref).toBe(`/person/${PERSON_ID}?cycle=2024`);
    expect(viewModel.financeRows).toHaveLength(1);
    expect(viewModel.financeRows[0].personHref).toBe(`/person/${PERSON_ID}?cycle=2024`);
    expect(viewModel.financeRows[0].candidateHref).toBe(
      "/candidate/jane-officeholder?cycle=2024"
    );
    expect(viewModel.financeRows[0].financeFacts).toEqual([]);
    expect(viewModel.financeRows[0].outsideSpendingFigure).toBeNull();
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
