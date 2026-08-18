/**
 * Rendered-markup contract for `/election/[date]`.
 *
 * This route is the only race index on the site, so the load-bearing assertion
 * is navigability: every contest the aggregate returns must render as an anchor
 * to its `/contest/[id]` page. Before 2026-08-17 the page rendered contest names
 * as plain `<li>` text with no anchors at all, which is exactly the defect the
 * first test below fails on.
 *
 * Screen spec: `docs/reference/screen_specs/election_date.md`.
 */
import { describe, expect, it, vi } from "vitest";
import { render } from "svelte/server";
import type { ElectionContestSummary, ElectionDateAggregateResponse } from "$lib/civic-detail/contract";

const currentPageUrl = new URL("https://civibus.test/election/2026-11-03");

vi.mock("$env/dynamic/public", () => ({
  env: {
    PUBLIC_ORIGIN: "https://civibus.test"
  }
}));

vi.mock("$app/stores", () => ({
  page: {
    subscribe(run: (value: { url: URL }) => void): () => void {
      run({ url: currentPageUrl });
      return () => {};
    }
  }
}));

import ElectionPage from "./+page.svelte";

const ELECTION_DATE = "2026-11-03";
const SENATE_CONTEST_ID = "11111111-1111-4111-8111-111111111111";
const HOUSE_2_CONTEST_ID = "22222222-2222-4222-8222-222222222222";
const HOUSE_12_CONTEST_ID = "33333333-3333-4333-8333-333333333333";
const TEXAS_CONTEST_ID = "44444444-4444-4444-8444-444444444444";

function contestRow(overrides: Partial<ElectionContestSummary> = {}): ElectionContestSummary {
  return {
    contest_id: SENATE_CONTEST_ID,
    office_id: "00000000-0000-4000-8000-0000000000f1",
    name: "California U.S. Senate — 2026 General Election",
    election_type: "general",
    office_name: "us_senate",
    office_level: "federal",
    state: "CA",
    jurisdiction_id: null,
    electoral_division_id: null,
    electoral_division_type: "statewide",
    electoral_division_state: "CA",
    district_number: null,
    candidate_count: 2,
    ...overrides
  };
}

const MULTI_STATE_AGGREGATE: ElectionDateAggregateResponse = {
  date: ELECTION_DATE,
  total_contests: 4,
  total_candidacies: 9,
  contests: [
    contestRow(),
    contestRow({
      contest_id: HOUSE_12_CONTEST_ID,
      name: "California 12th Congressional District — 2026 General Election",
      office_name: "us_house",
      electoral_division_type: "congressional_district",
      district_number: "12",
      candidate_count: 3
    }),
    contestRow({
      contest_id: HOUSE_2_CONTEST_ID,
      name: "California 2nd Congressional District — 2026 General Election",
      office_name: "us_house",
      electoral_division_type: "congressional_district",
      district_number: "02",
      candidate_count: 1
    }),
    contestRow({
      contest_id: TEXAS_CONTEST_ID,
      name: "Texas U.S. Senate — 2026 General Election",
      state: "TX",
      electoral_division_state: "TX",
      candidate_count: 3
    })
  ]
};

function renderElectionPage(data: ElectionDateAggregateResponse): string {
  return render(ElectionPage, { props: { data } }).body;
}

describe("/election/[date] route rendering", () => {
  it("renders one contest-route anchor per contest in the aggregate", () => {
    const body = renderElectionPage(MULTI_STATE_AGGREGATE);

    for (const contest of MULTI_STATE_AGGREGATE.contests) {
      const anchors = body.match(new RegExp(`href="/contest/${contest.contest_id}"`, "g")) ?? [];
      expect(anchors, `expected exactly one anchor for ${contest.name}`).toHaveLength(1);
    }
  });

  it("renders each contest name as the text of its own contest link", () => {
    const body = renderElectionPage(MULTI_STATE_AGGREGATE);

    // Anchor open tag through closing tag, with the contest name in between.
    // A name rendered as bare <li> text (the pre-fix markup) fails this.
    expect(body).toMatch(
      new RegExp(
        `<a[^>]*href="/contest/${TEXAS_CONTEST_ID}"[^>]*>\\s*Texas U.S. Senate — 2026 General Election\\s*</a>`
      )
    );
  });

  it("groups rows under state headings with Senate before House and numeric district order", () => {
    const body = renderElectionPage(MULTI_STATE_AGGREGATE);

    expect(body).toContain("<h3>California</h3>");
    expect(body).toContain("<h3>Texas</h3>");

    const positions = [
      body.indexOf("<h3>California</h3>"),
      body.indexOf(`/contest/${SENATE_CONTEST_ID}`),
      body.indexOf(`/contest/${HOUSE_2_CONTEST_ID}`),
      body.indexOf(`/contest/${HOUSE_12_CONTEST_ID}`),
      body.indexOf("<h3>Texas</h3>"),
      body.indexOf(`/contest/${TEXAS_CONTEST_ID}`)
    ];
    expect(positions.every((position) => position >= 0)).toBe(true);
    expect(positions).toEqual([...positions].sort((left, right) => left - right));
  });

  it("renders district context and candidate counts for each row", () => {
    const body = renderElectionPage(MULTI_STATE_AGGREGATE);

    expect(body).toContain("U.S. House · District 12 · General · 3 candidates");
    expect(body).toContain("U.S. House · District 2 · General · 1 candidate");
    expect(body).toContain("U.S. Senate · Statewide · General · 2 candidates");
  });

  it("renders whole-day scale counts and the group sizes", () => {
    const body = renderElectionPage(MULTI_STATE_AGGREGATE);

    expect(body).toContain("Total contests: 4");
    expect(body).toContain("Total candidacies: 9");
    expect(body).toContain("3 contests");
    expect(body).toContain("1 contest");
  });

  it("keeps the canonical election route link and the h2 date heading", () => {
    const body = renderElectionPage(MULTI_STATE_AGGREGATE);

    expect(body).toContain("<h2>Election 2026-11-03</h2>");
    expect(body).toMatch(/<a[^>]*href="\/election\/2026-11-03"[^>]*>\s*Canonical election route\s*<\/a>/);
  });

  it("renders the empty state without any contest anchors", () => {
    const body = renderElectionPage({
      date: ELECTION_DATE,
      total_contests: 0,
      total_candidacies: 0,
      contests: []
    });

    expect(body).toContain("No contests found for this date.");
    expect(body).not.toContain('href="/contest/');
    expect(body).toContain("Total contests: 0");
  });
});
