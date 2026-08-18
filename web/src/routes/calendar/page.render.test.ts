/**
 * Render tests for /calendar, the top of the race discovery chain.
 *
 * /calendar is in STATIC_PATHS and in the shell navigation, so it is how a
 * reader reaches an election at all. It rendered 681 contests as bare
 * `<li>{contest.name}</li>` — no link to the contest, and not even a link to
 * the election date's own page — which made the whole race surface unreachable
 * from navigation. These tests pin that every date and every contest is a link.
 */
import { render } from "svelte/server";
import { describe, expect, it, vi } from "vitest";
import type { ElectionContestSummary, UpcomingElectionTimelineEntry } from "$lib/civic-detail/contract";
import CalendarPage from "./+page.svelte";

vi.mock("$app/stores", async () => {
  const { readable } = await import("svelte/store");
  return { page: readable({ url: new URL("https://civibus.org/calendar") }) };
});

vi.mock("$env/dynamic/public", () => ({ env: { PUBLIC_ORIGIN: "https://civibus.org" } }));

const HOUSE_CONTEST_ID = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa";
const SENATE_CONTEST_ID = "aaaaaaaa-2222-4222-8222-aaaaaaaaaaaa";
const LATER_CONTEST_ID = "aaaaaaaa-3333-4333-8333-aaaaaaaaaaaa";

function contest(overrides: Partial<ElectionContestSummary>): ElectionContestSummary {
  return {
    contest_id: HOUSE_CONTEST_ID,
    office_id: "11111111-1111-4111-8111-111111111111",
    name: "North Carolina 4th Congressional District — 2026 General Election",
    election_type: "general",
    office_name: "us_house",
    office_level: "federal",
    state: "NC",
    jurisdiction_id: null,
    electoral_division_id: "dddddddd-1111-4111-8111-dddddddddddd",
    electoral_division_type: "congressional_district",
    electoral_division_state: "NC",
    district_number: "04",
    candidate_count: 3,
    ...overrides
  };
}

const TIMELINE: UpcomingElectionTimelineEntry[] = [
  {
    date: "2026-11-03",
    contests: [
      contest({}),
      contest({
        contest_id: SENATE_CONTEST_ID,
        name: "Georgia U.S. Senate — 2026 General Election",
        office_name: "us_senate",
        state: "GA",
        electoral_division_id: null,
        electoral_division_type: null,
        electoral_division_state: null,
        district_number: null,
        candidate_count: 21
      })
    ]
  },
  {
    date: "2027-03-09",
    contests: [
      contest({
        contest_id: LATER_CONTEST_ID,
        name: "Florida 1st Congressional District — 2027 Special Election",
        election_type: "special",
        state: "FL",
        electoral_division_state: "FL",
        district_number: "01",
        candidate_count: 2
      })
    ]
  }
];

function renderCalendar(timelineEntries: UpcomingElectionTimelineEntry[]) {
  return render(CalendarPage, { props: { data: { timelineEntries } } });
}

describe("/calendar render", () => {
  it("links every election date to its own page", () => {
    const rendered = renderCalendar(TIMELINE);

    expect(rendered.body).toContain('href="/election/2026-11-03"');
    expect(rendered.body).toContain('href="/election/2027-03-09"');
  });

  it("links every contest to its race page", () => {
    const rendered = renderCalendar(TIMELINE);

    expect(rendered.body).toContain(`href="/contest/${HOUSE_CONTEST_ID}"`);
    expect(rendered.body).toContain(`href="/contest/${SENATE_CONTEST_ID}"`);
    expect(rendered.body).toContain(`href="/contest/${LATER_CONTEST_ID}"`);
  });

  it("shows the contest name and candidate count on each row", () => {
    const rendered = renderCalendar(TIMELINE);

    expect(rendered.body).toContain("Georgia U.S. Senate — 2026 General Election");
    // The count is what tells a reader which races are worth opening.
    expect(rendered.body).toContain("21 candidates");
    expect(rendered.body).toContain("3 candidates");
  });

  it("groups contests under their election date in timeline order", () => {
    const rendered = renderCalendar(TIMELINE);

    expect(rendered.body.indexOf("2026-11-03")).toBeLessThan(rendered.body.indexOf("2027-03-09"));
    expect(rendered.body.indexOf(HOUSE_CONTEST_ID)).toBeLessThan(
      rendered.body.indexOf(LATER_CONTEST_ID)
    );
  });

  it("renders the empty state when no elections are upcoming", () => {
    const rendered = renderCalendar([]);

    expect(rendered.body).toContain("No upcoming elections found.");
    expect(rendered.body).not.toContain('href="/contest/');
  });

  it("keeps a date heading for an election with no loaded contests", () => {
    // A date with no roster yet is real information, not an empty row to hide:
    // it tells a reader an election exists before filings open.
    const rendered = renderCalendar([{ date: "2028-11-07", contests: [] }]);

    expect(rendered.body).toContain('href="/election/2028-11-07"');
    expect(rendered.body).toContain("No contests are loaded for this date yet.");
  });
});
