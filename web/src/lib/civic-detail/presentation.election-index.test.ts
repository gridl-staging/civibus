/**
 * Contract tests for the `/election/[date]` race-index view model.
 *
 * The election-date aggregate is a flat list of up to ~515 contests for one day.
 * `buildElectionIndexPresentation` is the only place that turns that flat list
 * into something navigable: state groups, a stable within-group order, a link
 * per row, and a context line built from the electoral-division columns the
 * aggregate query now joins in. Every assertion below is a hand-calculated
 * expected value, not a shape check, so the tests fail on a real ordering,
 * grouping, labelling, or href defect.
 *
 * Screen spec: `docs/reference/screen_specs/election_date.md`.
 */
import { describe, expect, it } from "vitest";
import { buildElectionIndexPresentation } from "./presentation";
import type { ElectionContestSummary, ElectionDateAggregateResponse } from "./contract";

const ELECTION_DATE = "2026-11-03";

/**
 * Build one aggregate row. Defaults describe a plain statewide state contest;
 * each test overrides only the columns it is actually asserting on, so a future
 * field addition does not silently change what a test is pinning.
 */
function contestRow(overrides: Partial<ElectionContestSummary> = {}): ElectionContestSummary {
  return {
    contest_id: "00000000-0000-4000-8000-000000000001",
    office_id: "00000000-0000-4000-8000-0000000000f1",
    name: "Some Contest — 2026 General Election",
    election_type: "general",
    office_name: "us_senate",
    office_level: "federal",
    state: "NC",
    jurisdiction_id: null,
    electoral_division_id: null,
    electoral_division_type: null,
    electoral_division_state: null,
    district_number: null,
    candidate_count: 0,
    ...overrides
  };
}

function aggregate(contests: ElectionContestSummary[]): ElectionDateAggregateResponse {
  return {
    date: ELECTION_DATE,
    total_contests: contests.length,
    total_candidacies: contests.reduce((sum, contest) => sum + contest.candidate_count, 0),
    contests
  };
}

describe("election index presentation", () => {
  it("links every contest row through the canonical contest route path", () => {
    const viewModel = buildElectionIndexPresentation(
      aggregate([
        contestRow({
          contest_id: "11111111-1111-4111-8111-111111111111",
          name: "North Carolina U.S. Senate — 2026 General Election"
        }),
        contestRow({
          contest_id: "22222222-2222-4222-8222-222222222222",
          name: "North Carolina 1st Congressional District — 2026 General Election",
          office_name: "us_house",
          electoral_division_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
          electoral_division_type: "congressional_district",
          electoral_division_state: "NC",
          district_number: "01"
        })
      ])
    );

    expect(viewModel.groups).toHaveLength(1);
    expect(viewModel.groups[0].rows.map((row) => row.contestHref)).toEqual([
      "/contest/11111111-1111-4111-8111-111111111111",
      "/contest/22222222-2222-4222-8222-222222222222"
    ]);
    expect(viewModel.groups[0].rows.map((row) => row.linkAriaLabel)).toEqual([
      "View North Carolina U.S. Senate — 2026 General Election",
      "View North Carolina 1st Congressional District — 2026 General Election"
    ]);
  });

  it("groups rows by state, orders groups by display name, and puts stateless rows last", () => {
    const viewModel = buildElectionIndexPresentation(
      aggregate([
        contestRow({
          contest_id: "00000000-0000-4000-8000-00000000000a",
          name: "Texas U.S. Senate — 2026 General Election",
          state: "TX"
        }),
        contestRow({
          contest_id: "00000000-0000-4000-8000-00000000000b",
          name: "U.S. President — 2026 General Election",
          office_name: "us_president",
          state: null
        }),
        contestRow({
          contest_id: "00000000-0000-4000-8000-00000000000c",
          name: "California U.S. Senate — 2026 General Election",
          state: "CA"
        })
      ])
    );

    // "California" < "Texas" alphabetically by display name, and the stateless
    // row sorts last regardless of name.
    expect(viewModel.groups.map((group) => group.heading)).toEqual([
      "California",
      "Texas",
      "Nationwide and unassigned"
    ]);
    expect(viewModel.groups.map((group) => group.stateCode)).toEqual(["CA", "TX", null]);
    expect(viewModel.groups.map((group) => group.rows.length)).toEqual([1, 1, 1]);
    expect(viewModel.groups[0].rows[0].contestName).toBe(
      "California U.S. Senate — 2026 General Election"
    );
    expect(viewModel.groups[2].rows[0].contestName).toBe("U.S. President — 2026 General Election");
  });

  it("orders Senate before House inside a state and sorts House districts numerically", () => {
    // Deliberately supplied out of order, and with district numbers whose
    // lexicographic order ("02" > "12" is false, but "2" > "12" is true) differs
    // from their numeric order once zero padding is absent.
    const viewModel = buildElectionIndexPresentation(
      aggregate([
        contestRow({
          contest_id: "00000000-0000-4000-8000-000000000012",
          name: "California 12th Congressional District — 2026 General Election",
          office_name: "us_house",
          electoral_division_type: "congressional_district",
          district_number: "12",
          state: "CA"
        }),
        contestRow({
          contest_id: "00000000-0000-4000-8000-000000000002",
          name: "California 2nd Congressional District — 2026 General Election",
          office_name: "us_house",
          electoral_division_type: "congressional_district",
          district_number: "2",
          state: "CA"
        }),
        contestRow({
          contest_id: "00000000-0000-4000-8000-00000000000d1",
          name: "California Delegate — 2026 General Election",
          office_name: "us_house_delegate",
          state: "CA"
        }),
        contestRow({
          contest_id: "00000000-0000-4000-8000-00000000000e5",
          name: "California U.S. Senate — 2026 General Election",
          office_name: "us_senate",
          state: "CA"
        })
      ])
    );

    expect(viewModel.groups[0].rows.map((row) => row.contestName)).toEqual([
      "California U.S. Senate — 2026 General Election",
      "California 2nd Congressional District — 2026 General Election",
      "California 12th Congressional District — 2026 General Election",
      "California Delegate — 2026 General Election"
    ]);
  });

  it("builds a context line from office, seat, election type, and candidate count", () => {
    const viewModel = buildElectionIndexPresentation(
      aggregate([
        contestRow({
          contest_id: "00000000-0000-4000-8000-000000000101",
          name: "California 12th Congressional District — 2026 General Election",
          office_name: "us_house",
          electoral_division_type: "congressional_district",
          district_number: "12",
          state: "CA",
          candidate_count: 2
        })
      ])
    );

    const row = viewModel.groups[0].rows[0];
    expect(row.officeLabel).toBe("U.S. House");
    expect(row.seatLabel).toBe("District 12");
    expect(row.electionTypeLabel).toBe("General");
    expect(row.candidateCountLabel).toBe("2 candidates");
    expect(row.contextLine).toBe("U.S. House · District 12 · General · 2 candidates");
  });

  it("omits the seat segment when the contest has no electoral division", () => {
    const viewModel = buildElectionIndexPresentation(
      aggregate([
        contestRow({
          contest_id: "00000000-0000-4000-8000-000000000102",
          name: "North Carolina U.S. Senate — 2026 General Election",
          office_name: "us_senate",
          electoral_division_type: null,
          district_number: null,
          candidate_count: 1
        })
      ])
    );

    const row = viewModel.groups[0].rows[0];
    expect(row.seatLabel).toBeNull();
    expect(row.contextLine).toBe("U.S. Senate · General · 1 candidate");
  });

  it("labels at-large and statewide divisions without inventing a district number", () => {
    const viewModel = buildElectionIndexPresentation(
      aggregate([
        contestRow({
          contest_id: "00000000-0000-4000-8000-000000000103",
          name: "Wyoming At-Large Congressional District — 2026 General Election",
          office_name: "us_house",
          electoral_division_type: "congressional_district",
          district_number: "00",
          state: "WY"
        }),
        contestRow({
          contest_id: "00000000-0000-4000-8000-000000000104",
          name: "Wyoming U.S. Senate — 2026 General Election",
          office_name: "us_senate",
          electoral_division_type: "statewide",
          district_number: null,
          state: "WY"
        })
      ])
    );

    const [senateRow, houseRow] = viewModel.groups[0].rows;
    expect(senateRow.seatLabel).toBe("Statewide");
    expect(houseRow.seatLabel).toBe("At-large district");
  });

  it("falls back to the electoral division state when the office carries no state", () => {
    const viewModel = buildElectionIndexPresentation(
      aggregate([
        contestRow({
          contest_id: "00000000-0000-4000-8000-000000000105",
          name: "Guam Delegate — 2026 General Election",
          office_name: "us_house_delegate",
          state: null,
          electoral_division_type: "at_large",
          electoral_division_state: "GU"
        })
      ])
    );

    // GU has no display spelling in US_STATE_OPTIONS, so the heading falls back
    // to the raw code rather than silently dropping the territory.
    expect(viewModel.groups.map((group) => group.heading)).toEqual(["GU"]);
    expect(viewModel.groups[0].stateCode).toBe("GU");
    expect(viewModel.groups[0].rows[0].seatLabel).toBe("At-large");
  });

  it("falls back to the raw office name for offices outside the federal directory set", () => {
    const viewModel = buildElectionIndexPresentation(
      aggregate([
        contestRow({
          contest_id: "00000000-0000-4000-8000-000000000106",
          name: "Statewide General 2026",
          office_name: "nc_governor",
          office_level: "state",
          election_type: "primary",
          candidate_count: 3
        })
      ])
    );

    const row = viewModel.groups[0].rows[0];
    expect(row.officeLabel).toBe("nc_governor");
    expect(row.contextLine).toBe("nc_governor · Primary · 3 candidates");
  });

  it("reports whole-day scale and an empty flag verbatim from the aggregate", () => {
    const populated = buildElectionIndexPresentation({
      date: ELECTION_DATE,
      total_contests: 515,
      total_candidacies: 1832,
      contests: [contestRow()]
    });
    expect(populated.date).toBe(ELECTION_DATE);
    expect(populated.totalContestsLabel).toBe("Total contests: 515");
    expect(populated.totalCandidaciesLabel).toBe("Total candidacies: 1832");
    expect(populated.isEmpty).toBe(false);

    const empty = buildElectionIndexPresentation(aggregate([]));
    expect(empty.isEmpty).toBe(true);
    expect(empty.groups).toEqual([]);
    expect(empty.totalContestsLabel).toBe("Total contests: 0");
    expect(empty.totalCandidaciesLabel).toBe("Total candidacies: 0");
  });

  it("counts contests per group so a large day is scannable", () => {
    const viewModel = buildElectionIndexPresentation(
      aggregate([
        contestRow({ contest_id: "00000000-0000-4000-8000-000000000201", state: "CA" }),
        contestRow({
          contest_id: "00000000-0000-4000-8000-000000000202",
          state: "CA",
          office_name: "us_house",
          electoral_division_type: "congressional_district",
          district_number: "01"
        }),
        contestRow({ contest_id: "00000000-0000-4000-8000-000000000203", state: "TX" })
      ])
    );

    expect(viewModel.groups.map((group) => group.contestCountLabel)).toEqual([
      "2 contests",
      "1 contest"
    ]);
  });
});
