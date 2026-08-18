import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "svelte/server";
import type { CandidateListItem } from "$lib/campaign-finance-detail/contract";

// The candidates route reads PUBLIC_ORIGIN for canonical/OG head tags.
vi.mock("$env/dynamic/public", () => ({
  env: {
    PUBLIC_ORIGIN: "https://civibus.test"
  }
}));

// URL query params are the source of truth for filters and sort, so the page
// store URL is the input under test for control state and link building.
const mockPageStore = vi.hoisted(() => ({
  url: new URL("https://civibus.test/candidates")
}));

vi.mock("$app/stores", () => ({
  page: {
    subscribe(run: (value: { url: URL }) => void): () => void {
      run({ url: mockPageStore.url });
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

import CandidatesPage from "./+page.svelte";

function setPageUrl(pathAndSearch: string): void {
  mockPageStore.url = new URL(pathAndSearch, "https://civibus.test");
}

/**
 * Splits the rendered body into one HTML chunk per candidate result row.
 * Anchored on the smoke-gate testid rather than the class attribute, because
 * Svelte appends a build-specific scoped-style hash to the class list.
 */
function extractResultRows(html: string): string[] {
  const chunks = html.split('data-testid="candidate-result-row"');
  return chunks.slice(1).map((chunk) => {
    const closingIndex = chunk.indexOf("</li>");
    return closingIndex === -1 ? chunk : chunk.slice(0, closingIndex);
  });
}

const FUNDED_CANDIDATE: CandidateListItem = {
  id: "11111111-1111-4111-8111-111111111111",
  fec_candidate_id: "H0NC01001",
  name: "Funded Candidate",
  party: "DEM",
  office: "H",
  state: "NC",
  district: "01",
  slug: "funded-candidate",
  slug_is_unique: true,
  identity_is_safe: true,
  has_official_total: true,
  total_receipts: "1234.56"
};

const UNFUNDED_CANDIDATE: CandidateListItem = {
  id: "22222222-2222-4222-8222-222222222222",
  fec_candidate_id: "H0NC01002",
  name: "Unfunded Candidate",
  party: "REP",
  office: "H",
  state: "NC",
  district: "02",
  slug: "unfunded-candidate",
  slug_is_unique: true,
  identity_is_safe: true,
  has_official_total: false,
  total_receipts: null
};

const LOADED_ZERO_CANDIDATE: CandidateListItem = {
  id: "33333333-3333-4333-8333-333333333333",
  fec_candidate_id: "H0NC01003",
  name: "Loaded Zero Candidate",
  party: "REP",
  office: "H",
  state: "NC",
  district: "03",
  slug: "loaded-zero-candidate",
  slug_is_unique: true,
  has_official_total: true,
  identity_is_safe: true,
  total_receipts: "0.00"
};

function buildPageData(items: CandidateListItem[], overrides: Record<string, unknown> = {}) {
  return {
    items,
    has_next: true,
    offset: 25,
    limit: 25,
    ...overrides
  };
}

describe("/candidates +page.svelte money column", () => {
  beforeEach(() => {
    setPageUrl("/candidates");
  });

  it("renders the formatted official total for a funded candidate", () => {
    const rendered = render(CandidatesPage, {
      props: { data: buildPageData([FUNDED_CANDIDATE]) }
    });
    const [row] = extractResultRows(rendered.body);

    expect(row).toContain("Total raised");
    expect(row).toContain("$1,234.56");
  });

  it("renders unknown copy and no dollar figure for a candidate with no loaded total", () => {
    const rendered = render(CandidatesPage, {
      props: { data: buildPageData([UNFUNDED_CANDIDATE]) }
    });
    const [row] = extractResultRows(rendered.body);

    expect(row).toContain("Total raised");
    expect(row).toContain("Not available");
    // Honesty rule: a missing official total is never reported as zero money.
    expect(row).not.toContain("$0.00");
    expect(row).not.toContain("$0");
    expect(row).not.toContain("$");
  });

  it("still renders an explicit $0.00 when the official total is a loaded zero", () => {
    const rendered = render(CandidatesPage, {
      props: { data: buildPageData([LOADED_ZERO_CANDIDATE]) }
    });
    const [row] = extractResultRows(rendered.body);

    expect(row).toContain("$0.00");
    expect(row).not.toContain("Not available");
  });

  it("keeps funded and unfunded rows distinguishable in one rendered list", () => {
    const rendered = render(CandidatesPage, {
      props: { data: buildPageData([FUNDED_CANDIDATE, UNFUNDED_CANDIDATE]) }
    });
    const rows = extractResultRows(rendered.body);

    expect(rows).toHaveLength(2);
    expect(rows[0]).toContain("$1,234.56");
    expect(rows[1]).toContain("Not available");
    expect(rows[1]).not.toContain("$");
  });
});

describe("/candidates +page.svelte sort control", () => {
  beforeEach(() => {
    setPageUrl("/candidates");
  });

  it("renders a sort select defaulting to the name sort", () => {
    const rendered = render(CandidatesPage, {
      props: { data: buildPageData([FUNDED_CANDIDATE]) }
    });

    expect(rendered.body).toContain('id="candidate-sort"');
    expect(rendered.body).toContain('name="sort"');
    expect(rendered.body).toContain('value="total_raised_desc"');
    expect(rendered.body).toMatch(/<option value="name"[^>]*selected/);
  });

  it("marks the active sort from the URL as selected", () => {
    setPageUrl("/candidates?sort=total_raised_desc");
    const rendered = render(CandidatesPage, {
      props: { data: buildPageData([FUNDED_CANDIDATE]) }
    });

    expect(rendered.body).toMatch(/<option value="total_raised_desc"[^>]*selected/);
  });

  it("carries the active sort through previous and next pagination hrefs", () => {
    setPageUrl("/candidates?state=NC&sort=total_raised_desc&offset=25&limit=25");
    const rendered = render(CandidatesPage, {
      props: { data: buildPageData([FUNDED_CANDIDATE]) }
    });

    expect(rendered.body).toContain(
      'href="/candidates?state=NC&amp;sort=total_raised_desc&amp;offset=0&amp;limit=25"'
    );
    expect(rendered.body).toContain(
      'href="/candidates?state=NC&amp;sort=total_raised_desc&amp;offset=50&amp;limit=25"'
    );
  });
});

describe("/candidates +page.svelte browse scope caption", () => {
  beforeEach(() => {
    setPageUrl("/candidates");
  });

  it("keeps the deploy-gate Candidates marker and explains browse suppression", () => {
    const rendered = render(CandidatesPage, {
      props: { data: buildPageData([FUNDED_CANDIDATE]) }
    });

    expect(rendered.body).toContain("<h2>Candidates</h2>");
    expect(rendered.body).toContain('data-testid="candidate-result-row"');
    expect(rendered.body).toContain("reachable at their own candidate pages");
  });
});
