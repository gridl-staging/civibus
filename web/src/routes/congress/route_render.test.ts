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
    person_id: "77777777-7777-4777-8777-777777777777",
    person_name: "Maria Delegate",
    has_fec_money: false,
    candidate_id: null,
    total_raised: "0.00",
    total_spent: "0.00",
    net: "0.00",
    cash_on_hand: null,
    summary_source: null,
    ie_support_total: "0.00",
    ie_oppose_total: "0.00",
    ie_support_count: 0,
    ie_oppose_count: 0,
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
});
