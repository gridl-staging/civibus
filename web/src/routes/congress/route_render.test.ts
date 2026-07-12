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
  }
];

describe("/congress route render", () => {
  it("renders populated member rows with linked names, context metadata, and portrait alt text", () => {
    currentPageUrl = new URL("https://preview.internal:5173/congress");
    const rendered = render(CongressPage, { props: { data: { members: MEMBERS } } });

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
    const rendered = render(CongressPage, { props: { data: { members: MEMBERS } } });

    expect(rendered.body).toContain('data-testid="entity-portrait-initials"');
    expect(rendered.body).toContain(">AS<");
    expect(rendered.body).toContain("Senate · GA · Class II · Republican");
  });

  it("renders an initial empty-data message distinct from filtered-empty results", () => {
    currentPageUrl = new URL("https://preview.internal:5173/congress");
    const rendered = render(CongressPage, { props: { data: { members: [] } } });

    expect(rendered.body).toContain("No Congress members are available right now.");
    expect(rendered.body).not.toContain("No members match the active filters.");
  });

  it("renders the screen-spec filtered-empty message when filters exclude all rows", () => {
    currentPageUrl = new URL("https://preview.internal:5173/congress?search=nomatch");
    const rendered = render(CongressPage, { props: { data: { members: MEMBERS } } });

    expect(rendered.body).toContain('value="nomatch"');
    expect(rendered.body).toContain("No members match the active filters.");
    expect(rendered.body).toContain('href="/congress"');
    expect(rendered.body).not.toContain("Jane Representative");
    expect(rendered.body).not.toContain("Alex Senator");
  });
});
