import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "svelte/server";
import SearchPage from "./+page.svelte";

let currentPageUrl = new URL("https://civibus.test/");

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

function expectNoRouteSocialTags(head: string): void {
  expect(head).not.toContain('<link rel="canonical"');
  expect(head).not.toContain('property="og:');
  expect(head).not.toContain('name="twitter:');
  expect(head).not.toContain("application/ld+json");
}

function getSearchResultsRegionMarkup(body: string): string {
  const regionMatch = body.match(/<([a-z0-9-]+)[^>]*data-testid="search-results-region"[^>]*>/i);
  expect(regionMatch).not.toBeNull();

  const openingTagMarkup = regionMatch?.[0] ?? "";
  const regionTagName = regionMatch?.[1] ?? "";
  const regionStartIndex = body.indexOf(openingTagMarkup);
  expect(regionStartIndex).toBeGreaterThanOrEqual(0);

  const closingTagMarkup = `</${regionTagName}>`;
  const regionEndIndex = body.lastIndexOf(closingTagMarkup);
  expect(regionEndIndex).toBeGreaterThanOrEqual(0);

  return body.slice(regionStartIndex, regionEndIndex + closingTagMarkup.length);
}

describe("search route head rendering", () => {
  beforeEach(() => {
    currentPageUrl = new URL("https://preview.internal:5173/search");
  });

  it("keeps /search as title-plus-description only with no canonical, OG, Twitter, or JSON-LD tags", () => {
    currentPageUrl = new URL("https://preview.internal:5173/search?q=jane");
    const rendered = render(SearchPage, {
      props: {
        data: {
          query: "jane",
          entityType: "",
          results: []
        }
      }
    });

    expect(rendered.head).toContain('<title>jane (0 results) | Search | Civibus</title>');
    expect(rendered.head).toContain(
      '<meta name="description" content="0 results for &quot;jane&quot; across Civibus records."'
    );
    expectNoRouteSocialTags(rendered.head);
    expect(rendered.body).toContain('aria-label="Browse by record type"');
    expect(rendered.body).toContain('href="/search?entity_type=person"');
    expect(rendered.body).toContain('href="/search?entity_type=org"');
    expect(rendered.body).toContain('href="/search?entity_type=committee"');
    expect(rendered.body).toContain('href="/search?entity_type=candidate"');
    expect(rendered.body).toContain('href="/search?entity_type=office"');
    expect(rendered.body).toContain('href="/search?entity_type=contest"');
    expect(rendered.body).toContain(
      'placeholder="Search people, organizations, committees, candidates, offices, or contests"'
    );
    expect(rendered.body).toContain('value="candidate"');
    expect(rendered.body).not.toContain("Candidate is intentionally excluded from this filter");
  });

  it("renders /search inline validation state from submitted action form data", () => {
    const rendered = render(SearchPage, {
      props: {
        data: {
          query: "",
          entityType: "",
          results: []
        },
        form: {
          query: "c",
          entityType: "candidate",
          validationMessage: "query.q: String should have at least 2 characters"
        }
      }
    });

    expect(rendered.head).toContain('<title>c (0 results) | Search | Civibus</title>');
    expect(rendered.body).toContain('value="c"');
    expect(rendered.body).toContain('value="candidate"');
    expect(rendered.body).toContain("query.q: String should have at least 2 characters");
    expect(rendered.body).toContain("Search could not run. Fix validation issues and try again.");
  });

  it("marks the query input invalid only when inline validation is present", () => {
    const invalidRendered = render(SearchPage, {
      props: {
        data: {
          query: "",
          entityType: "",
          results: []
        },
        form: {
          query: "c",
          entityType: "candidate",
          validationMessage: "query.q: String should have at least 2 characters"
        }
      }
    });

    expect(invalidRendered.body).toContain('id="search-query"');
    expect(invalidRendered.body).toContain('aria-invalid="true"');
    expect(invalidRendered.body).toContain('aria-describedby="search-validation-message"');
    expect(invalidRendered.body).toContain('<p id="search-validation-message" class="search__validation" role="alert">');

    const cleanRendered = render(SearchPage, {
      props: {
        data: {
          query: "civ",
          entityType: "org",
          results: []
        }
      }
    });

    expect(cleanRendered.body).not.toContain('aria-invalid="true"');
    expect(cleanRendered.body).not.toContain('aria-describedby="search-validation-message"');
    expect(cleanRendered.body).not.toContain('id="search-validation-message"');
  });

  it("renders /search inline validation from page data when form is null", () => {
    const rendered = render(SearchPage, {
      props: {
        data: {
          query: "c",
          entityType: "candidate",
          results: [],
          validationMessage: "query.q: String should have at least 2 characters"
        } as any,
        form: null
      }
    });

    expect(rendered.head).toContain('<title>c (0 results) | Search | Civibus</title>');
    expect(rendered.body).toContain('value="c"');
    expect(rendered.body).toMatch(/<option value="candidate"[^>]*selected[^>]*>/);
    expect(rendered.body).toContain("query.q: String should have at least 2 characters");
    expect(rendered.body).toContain("Search could not run. Fix validation issues and try again.");
  });

  // --- Loading skeleton SSR contract (Stage 1 red-phase tests) ---

  it("renders aria-busy on the search results region when isSubmitting is true", () => {
    currentPageUrl = new URL("https://preview.internal:5173/search?q=jane");
    const rendered = render(SearchPage, {
      props: {
        data: {
          query: "jane",
          entityType: "",
          results: []
        },
        isSubmitting: true
      }
    });

    const resultsRegionOpeningTag = rendered.body.match(
      /<[^>]*data-testid="search-results-region"[^>]*>/
    )?.[0];

    expect(resultsRegionOpeningTag).toBeDefined();
    expect(resultsRegionOpeningTag).toContain('data-testid="search-results-region"');
    expect(resultsRegionOpeningTag).toContain('aria-busy="true"');
  });

  it("renders a skeleton-panel element when isSubmitting is true", () => {
    currentPageUrl = new URL("https://preview.internal:5173/search?q=jane");
    const rendered = render(SearchPage, {
      props: {
        data: {
          query: "jane",
          entityType: "",
          results: []
        },
        isSubmitting: true
      }
    });

    const resultsRegionMarkup = getSearchResultsRegionMarkup(rendered.body);
    expect(resultsRegionMarkup).toContain("skeleton-panel");
  });

  it("does not render stale result cards when isSubmitting is true", () => {
    currentPageUrl = new URL("https://preview.internal:5173/search?q=jane");
    const rendered = render(SearchPage, {
      props: {
        data: {
          query: "jane",
          entityType: "",
          results: [
            {
              entity_type: "person",
              entity_id: "11111111-1111-4111-8111-111111111111",
              name: "Jane Smith"
            }
          ]
        },
        isSubmitting: true
      }
    });

    expect(rendered.body).not.toContain('class="card search__result"');
  });

  it("renders result cards without aria-busy or skeleton-panel when not submitting", () => {
    currentPageUrl = new URL("https://preview.internal:5173/search?q=jane");
    const rendered = render(SearchPage, {
      props: {
        data: {
          query: "jane",
          entityType: "",
          results: [
            {
              entity_type: "person",
              entity_id: "11111111-1111-4111-8111-111111111111",
              name: "Jane Smith"
            }
          ]
        }
      }
    });

    expect(rendered.body).toContain('class="card search__result"');
    expect(rendered.body).not.toContain('aria-busy="true"');
    expect(rendered.body).not.toContain("skeleton-panel");
  });

  // --- Five-state SSR regression matrix (Stage 3) ---

  describe("five-state SSR matrix", () => {
    it("empty state: renders guidance and browse links with a non-busy results region", () => {
      const rendered = render(SearchPage, {
        props: {
          data: {
            query: "",
            entityType: "",
            results: []
          }
        }
      });

      expect(rendered.head).toContain("<title>Search | Civibus</title>");
      expect(rendered.body).toContain("Search supports");
      expect(rendered.body).toContain('aria-label="Browse by record type"');
      expect(rendered.body).toContain('href="/search?entity_type=person"');
      expect(rendered.body).toContain("Enter at least 2 characters to search.");

      const resultsRegion = getSearchResultsRegionMarkup(rendered.body);
      expect(resultsRegion).toContain('aria-busy="false"');
      expect(resultsRegion).not.toContain("skeleton-panel");
      expect(resultsRegion).not.toContain('class="card search__result"');
    });

    it("results state: renders result cards in a non-busy region with no skeleton markup", () => {
      currentPageUrl = new URL("https://preview.internal:5173/search?q=jane");
      const rendered = render(SearchPage, {
        props: {
          data: {
            query: "jane",
            entityType: "",
            results: [
              {
                entity_type: "person",
                entity_id: "11111111-1111-4111-8111-111111111111",
                name: "Jane Smith"
              },
              {
                entity_type: "org",
                entity_id: "22222222-2222-4222-8222-222222222222",
                name: "Jane Corp"
              }
            ]
          }
        }
      });

      expect(rendered.head).toContain("jane (2 results) | Search | Civibus");
      expect(rendered.body).toContain("2 results found.");
      expect(rendered.body).toContain("Jane Smith");
      expect(rendered.body).toContain("Jane Corp");

      const resultsRegion = getSearchResultsRegionMarkup(rendered.body);
      expect(resultsRegion).toContain('aria-busy="false"');
      expect(resultsRegion).not.toContain("skeleton-panel");
      expect(resultsRegion).toContain('class="card search__result"');
    });

    it("zero-results state: renders no-results status with no stale cards or skeleton", () => {
      currentPageUrl = new URL("https://preview.internal:5173/search?q=xyznonexistent");
      const rendered = render(SearchPage, {
        props: {
          data: {
            query: "xyznonexistent",
            entityType: "person",
            results: []
          }
        }
      });

      expect(rendered.head).toContain("xyznonexistent (0 results) | Search | Civibus");
      expect(rendered.body).toContain("No matching records found.");

      const resultsRegion = getSearchResultsRegionMarkup(rendered.body);
      expect(resultsRegion).toContain('aria-busy="false"');
      expect(resultsRegion).not.toContain("skeleton-panel");
      expect(resultsRegion).not.toContain('class="card search__result"');
    });

    it("validation-error state: renders inline validation copy with no stale cards or skeleton", () => {
      const rendered = render(SearchPage, {
        props: {
          data: {
            query: "civ",
            entityType: "org",
            results: [
              {
                entity_type: "org",
                entity_id: "22222222-2222-4222-8222-222222222222",
                name: "Civibus Org"
              }
            ]
          },
          form: {
            query: "c",
            entityType: "candidate",
            validationMessage: "query.q: String should have at least 2 characters"
          }
        }
      });

      expect(rendered.body).toContain("query.q: String should have at least 2 characters");
      expect(rendered.body).toContain("Search could not run. Fix validation issues and try again.");
      expect(rendered.body).toContain('value="c"');
      expect(rendered.body).toMatch(/<option value="candidate"[^>]*selected[^>]*>/);
      expect(rendered.body).not.toMatch(/<option value="org"[^>]*selected[^>]*>/);

      const resultsRegion = getSearchResultsRegionMarkup(rendered.body);
      expect(resultsRegion).toContain('aria-busy="false"');
      expect(resultsRegion).not.toContain("skeleton-panel");
      expect(resultsRegion).not.toContain('class="card search__result"');
    });

    it("pending state: aria-busy, skeleton-panel, and stale-card suppression in the results region", () => {
      currentPageUrl = new URL("https://preview.internal:5173/search?q=jane");
      const rendered = render(SearchPage, {
        props: {
          data: {
            query: "jane",
            entityType: "person",
            results: [
              {
                entity_type: "person",
                entity_id: "11111111-1111-4111-8111-111111111111",
                name: "Jane Smith"
              }
            ]
          },
          isSubmitting: true
        }
      });

      expect(rendered.body).toContain("Searching...");

      const resultsRegion = getSearchResultsRegionMarkup(rendered.body);
      expect(resultsRegion).toContain('aria-busy="true"');
      expect(resultsRegion).toContain("skeleton-panel");
      expect(resultsRegion).not.toContain('class="card search__result"');
    });
  });
});
