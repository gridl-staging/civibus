import { render } from "svelte/server";
import { describe, expect, it, vi } from "vitest";
import CongressPage from "./+page.svelte";

let currentPageUrl = new URL("https://preview.internal:5173/congress");

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
  },
  navigating: {
    subscribe(run: (value: null) => void): () => void {
      run(null);
      return () => {};
    }
  }
}));

vi.mock("$app/navigation", () => ({
  goto: vi.fn()
}));

const MEMBERS = [
  {
    person_id: "11111111-1111-4111-8111-111111111111",
    person_name: "Jane Representative",
    officeholding_id: "44444444-4444-4444-8444-444444444444",
    office_id: "33333333-3333-4333-8333-333333333333",
    office_name: "U.S. Representative for North Carolina's 1st congressional district",
    chamber: "House",
    state: "NC",
    district: "01",
    district_or_class: "01",
    party: "Democratic",
    portrait_source_image_url: "https://example.test/jane.jpg",
    person_detail_path: "/person/11111111-1111-4111-8111-111111111111"
  },
  {
    person_id: "22222222-2222-4222-8222-222222222222",
    person_name: "Alex Senator",
    officeholding_id: "55555555-5555-4555-8555-555555555555",
    office_id: "66666666-6666-4666-8666-666666666666",
    office_name: "U.S. Senator from Georgia",
    chamber: "Senate",
    state: "GA",
    district: null,
    district_or_class: "Class II",
    party: "Republican",
    portrait_source_image_url: null,
    person_detail_path: "/person/22222222-2222-4222-8222-222222222222"
  },
  {
    person_id: "77777777-7777-4777-8777-777777777777",
    person_name: "Maria Delegate",
    officeholding_id: "88888888-8888-4888-8888-888888888888",
    office_id: "99999999-9999-4999-8999-999999999999",
    office_name: "Delegate to the U.S. House from Puerto Rico",
    chamber: "House",
    state: "PR",
    district: null,
    district_or_class: "Delegate",
    party: "Democratic",
    portrait_source_image_url: null,
    person_detail_path: "/person/77777777-7777-4777-8777-777777777777"
  },
  {
    person_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    person_name: "Sam Unloaded",
    officeholding_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    office_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    office_name: "U.S. Senator from Wyoming",
    chamber: "Senate",
    state: "WY",
    district: null,
    district_or_class: "Class I",
    party: "Republican",
    portrait_source_image_url: null,
    person_detail_path: "/person/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
  }
];

const MONEY_SUMMARIES = [
  {
    person_id: "11111111-1111-4111-8111-111111111111",
    person_name: "Jane Representative",
    has_fec_money: true,
    candidate_id: "H6NC01001",
    total_raised: "300.00",
    total_spent: "200.00",
    net: "100.00",
    cash_on_hand: "60.00",
    summary_source: "fec_candidate_totals",
    ie_support_total: "90.00",
    ie_oppose_total: "30.00",
    ie_support_count: 2,
    ie_oppose_count: 1,
    sources: [
      {
        domain: "fec",
        jurisdiction: "US",
        data_source_name: "FEC candidate summary",
        data_source_url: "https://api.open.fec.gov/developers/",
        source_record_key: "H6NC01001",
        record_url: "https://www.fec.gov/data/candidate/H6NC01001/",
        pull_date: "2026-07-16"
      }
    ]
  },
  {
    person_id: "22222222-2222-4222-8222-222222222222",
    person_name: "Alex Senator",
    has_fec_money: true,
    candidate_id: "S6GA00001",
    total_raised: "100.00",
    total_spent: "75.00",
    net: "25.00",
    cash_on_hand: "0.00",
    summary_source: "fec_candidate_totals",
    ie_support_total: "20.00",
    ie_oppose_total: "80.00",
    ie_support_count: 1,
    ie_oppose_count: 3,
    sources: []
  },
  {
    // No linked FEC candidate at all. The API sends nulls, not minted zeros.
    person_id: "77777777-7777-4777-8777-777777777777",
    person_name: "Maria Delegate",
    has_fec_money: false,
    candidate_id: null,
    total_raised: null,
    total_spent: null,
    net: null,
    cash_on_hand: null,
    summary_source: null,
    ie_support_total: null,
    ie_oppose_total: null,
    ie_support_count: null,
    ie_oppose_count: null,
    sources: []
  },
  {
    // Linked to a real FEC candidate -- has_fec_money is TRUE -- but no
    // Schedule A was loaded for the cycle. This is the 74-of-539 shape: the
    // money panel renders, and every cell in it has to say so in words.
    person_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    person_name: "Sam Unloaded",
    has_fec_money: true,
    candidate_id: "S6WY00001",
    total_raised: null,
    total_spent: null,
    net: null,
    cash_on_hand: null,
    summary_source: null,
    fundraising_coverage: {
      activity_state: "not_loaded" as const,
      completeness: "unknown" as const,
      basis: "no_authoritative_load_evidence" as const
    },
    ie_support_total: null,
    ie_oppose_total: null,
    ie_support_count: null,
    ie_oppose_count: null,
    sources: []
  }
];

function renderedMemberRow(body: string, rowIndex: number): string {
  const startMarker = `data-testid="congress-member-row-${rowIndex}"`;
  const start = body.indexOf(startMarker);
  const next = body.indexOf(`data-testid="congress-member-row-${rowIndex + 1}"`, start);
  return body.slice(start, next === -1 ? undefined : next);
}

describe("/congress route render", () => {
  it("renders populated member rows with linked names, context metadata, and portrait alt text", () => {
    currentPageUrl = new URL("https://preview.internal:5173/congress");
    const rendered = render(CongressPage, { props: { data: { members: MEMBERS, moneySummaries: [] } } });

    expect(rendered.head).toContain('<link rel="canonical" href="https://civibus.test/congress"');
    expect(rendered.body).toMatch(/<h2[^>]*>Congress<\/h2>/);
    expect(rendered.body).toContain('name="search"');
    expect(rendered.body).toContain('name="chamber"');
    expect(rendered.body).toContain('name="state"');
    expect(rendered.body).toContain('name="party"');
    expect(rendered.body).toContain('data-testid="congress-search"');
    expect(rendered.body).toContain('data-testid="congress-result-count"');
    expect(rendered.body).toContain('data-testid="congress-member-row-0"');
    expect(rendered.body).toContain('href="/person/11111111-1111-4111-8111-111111111111"');
    expect(rendered.body).toContain("Jane Representative");
    expect(rendered.body).toContain("House · NC · District 01 · Democratic");
    expect(rendered.body).toContain('alt="Portrait of Jane Representative"');
  });

  it("renders initials fallback content when portrait data is missing", () => {
    currentPageUrl = new URL("https://preview.internal:5173/congress");
    const rendered = render(CongressPage, { props: { data: { members: MEMBERS, moneySummaries: [] } } });

    expect(rendered.body).toContain('data-testid="entity-portrait-initials"');
    expect(rendered.body).toContain(">AS<");
    expect(rendered.body).toContain("Senate · GA · Class II · Republican");
  });

  it("renders an initial empty-data message distinct from filtered-empty results", () => {
    currentPageUrl = new URL("https://preview.internal:5173/congress");
    const rendered = render(CongressPage, { props: { data: { members: [], moneySummaries: [] } } });

    expect(rendered.body).toContain("No Congress members are available right now.");
    expect(rendered.body).not.toContain("No members match the active filters.");
  });

  it("renders the screen-spec filtered-empty message when filters exclude all rows", () => {
    currentPageUrl = new URL("https://preview.internal:5173/congress?search=nomatch");
    const rendered = render(CongressPage, { props: { data: { members: MEMBERS, moneySummaries: [] } } });

    expect(rendered.body).toContain('value="nomatch"');
    expect(rendered.body).toContain("No members match the active filters.");
    expect(rendered.body).toContain('href="/congress"');
    expect(rendered.body).not.toContain("Jane Representative");
    expect(rendered.body).not.toContain("Alex Senator");
  });

  it("renders exact money columns, shared-scale bars, reported zero, and explicit no-money copy", () => {
    currentPageUrl = new URL("https://preview.internal:5173/congress");
    const rendered = render(CongressPage, {
      props: { data: { members: MEMBERS, moneySummaries: MONEY_SUMMARIES } }
    });
    const janeRow = renderedMemberRow(rendered.body, 0);
    const alexRow = renderedMemberRow(rendered.body, 1);
    const mariaRow = renderedMemberRow(rendered.body, 2);

    expect(janeRow).toContain("Jane Representative");
    expect(janeRow).toContain("$300.00");
    expect(janeRow).toContain("$90.00");
    expect(janeRow).toContain("$30.00");
    expect(janeRow).toContain("$60.00");
    expect(janeRow).toContain('data-testid="comparison-bar-11111111-1111-4111-8111-111111111111"');
    expect(janeRow).toContain("--comparison-track-width: 100%");

    expect(alexRow).toContain("Alex Senator");
    expect(alexRow).toContain("$100.00");
    expect(alexRow).toContain("$20.00");
    expect(alexRow).toContain("$80.00");
    expect(alexRow).toContain("$0.00");
    expect(alexRow.match(/Source link unavailable/g)).toHaveLength(4);
    expect(alexRow).toContain('data-testid="comparison-bar-22222222-2222-4222-8222-222222222222"');
    expect(alexRow).toContain("--comparison-track-width: 33.33333333333333%");

    expect(mariaRow).toContain("Maria Delegate");
    expect(mariaRow).toContain("No reported/loaded money.");
    expect(mariaRow).not.toContain("$0");
  });

  it("renders words, not a dollar figure, for a linked member whose cycle was never loaded", () => {
    currentPageUrl = new URL("https://preview.internal:5173/congress");
    const rendered = render(CongressPage, {
      props: { data: { members: MEMBERS, moneySummaries: MONEY_SUMMARIES } }
    });
    // Located by name, not by sort position: the assertions below are about
    // what this member's row says, and a failure should read "printed $0.00",
    // not "the row moved".
    const samRow = [0, 1, 2, 3]
      .map((index) => renderedMemberRow(rendered.body, index))
      .find((row) => row.includes("Sam Unloaded"));

    expect(samRow).toBeDefined();
    // has_fec_money is true, so the money panel renders -- and every one of its
    // four cells has to say the figure is missing rather than print $0.00.
    expect(samRow).toContain('aria-label="Money summary for Sam Unloaded"');
    expect(samRow!.match(/Not reported\/loaded/g)).toHaveLength(4);
    // The single most important assertion on this page: no dollar figure at
    // all. A "$0.00" here is a measurement nobody took.
    expect(samRow).not.toContain("$");
    // No bar either. A zero-width bar is the graphical form of the same claim,
    // so the comparison row states the gap in words instead.
    expect(samRow).not.toContain('data-testid="comparison-bar-aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"');
    expect(samRow).toContain("No reported/loaded money.");
  });
});
