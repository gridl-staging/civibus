import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "svelte/server";
import { buildWashingtonNode } from "$lib/regional-navigation/test-fixtures";
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
          offset: 0,
          hasNext: false,
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
    expect(rendered.body).toContain('href="/search?entity_type=region"');
    expect(rendered.body).toContain(
      'placeholder="Search people, organizations, committees, candidates, offices, or contests"'
    );
    expect(rendered.body).toContain('value="candidate"');
    expect(rendered.body).toContain('value="region"');
    expect(rendered.body).not.toContain("Candidate is intentionally excluded from this filter");
  });

  it("renders /search inline validation state from submitted action form data", () => {
    const rendered = render(SearchPage, {
      props: {
        data: {
          query: "",
          entityType: "",
          offset: 0,
          hasNext: false,
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

  it("labels regional route kinds and discloses intentionally omitted locality routes", () => {
    const rendered = render(SearchPage, {
      props: {
        data: {
          query: "Washington",
          entityType: "",
          offset: 0,
          hasNext: false,
          results: [],
          regionalResults: [buildWashingtonNode()],
          regionalIncompleteNodeKinds: [
            "county",
            "municipality",
            "school_district",
            "special_district"
          ],
          regionalHasUnsafeOmissions: true
        }
      }
    });

    expect(rendered.body).toContain('id="regional-search-results">Regions');
    expect(rendered.body).toContain('href="/state/WA">Washington</a>');
    expect(rendered.body).toContain('<span class="search__badge">State</span>');
    expect(rendered.body).toContain("Finance available · authority translation refused");
    expect(rendered.body).not.toMatch(/\$[0-9]/);
    expect(rendered.body).not.toContain("Top candidates");
    expect(rendered.body.match(/role="status"/g)).toHaveLength(1);
    expect(rendered.body).toContain("No matching record results found.");
    expect(rendered.body).toContain("1 regional route shown separately from record results.");
    expect(rendered.body).toContain(
      "Explicit routes may be omitted for county, municipality, school district, special district subjects."
    );
  });

  it("keeps Washington source failure explicit without presenting a zero", () => {
    const rendered = render(SearchPage, {
      props: {
        data: {
          query: "Washington",
          entityType: "region",
          offset: 0,
          hasNext: false,
          results: [],
          regionalResults: [buildWashingtonNode("unavailable")]
        }
      }
    });

    expect(rendered.body).toContain('href="/state/WA">Washington</a>');
    expect(rendered.body).toContain("Finance unavailable · authority translation refused");
    expect(rendered.body).not.toContain("Reopening state coverage");
    expect(rendered.body).not.toMatch(/\$[0-9]/);
  });

  it("does not claim complete zero results when an exact municipality route may be omitted", () => {
    const rendered = render(SearchPage, {
      props: {
        data: {
          query: "San Francisco",
          entityType: "region",
          offset: 0,
          hasNext: false,
          results: [],
          regionalResults: [],
          regionalIncompleteNodeKinds: [
            "county",
            "municipality",
            "school_district",
            "special_district"
          ],
          regionalHasUnsafeOmissions: true
        }
      }
    });

    expect(rendered.body.match(/role="status"/g)).toHaveLength(1);
    expect(rendered.body).toContain("Regional route search is incomplete.");
    expect(rendered.body).toContain("school district, special district subjects");
    expect(rendered.body).not.toContain("No matching record results found.");
    expect(rendered.body).not.toContain("No matching records found.");
  });

  it("marks the query input invalid only when inline validation is present", () => {
    const invalidRendered = render(SearchPage, {
      props: {
        data: {
          query: "",
          entityType: "",
          offset: 0,
          hasNext: false,
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
          offset: 0,
          hasNext: false,
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
          offset: 0,
          hasNext: false,
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
          offset: 0,
          hasNext: false,
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
          offset: 0,
          hasNext: false,
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
          offset: 0,
          hasNext: false,
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
          offset: 0,
          hasNext: false,
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

  it("renders pagination inside the results region when the result set spans pages", () => {
    currentPageUrl = new URL("https://preview.internal:5173/search?q=civ&offset=20");
    const rendered = render(SearchPage, {
      props: {
        data: {
          query: "civ",
          entityType: "",
          offset: 20,
          hasNext: true,
          results: [
            {
              entity_type: "org",
              entity_id: "22222222-2222-4222-8222-222222222222",
              name: "Paged Org"
            }
          ]
        }
      }
    });

    const resultsRegion = getSearchResultsRegionMarkup(rendered.body);
    expect(resultsRegion).toContain('aria-label="Search results pagination"');
    expect(resultsRegion).toContain("Showing 21–21");
    // Previous returns to canonical page one (no offset); Next steps one page.
    expect(resultsRegion).toContain('href="/search?q=civ"');
    expect(resultsRegion).toContain('href="/search?q=civ&amp;offset=40"');
  });

  it("keeps a fully filtered middle page truthful and recoverable for assistive technology", () => {
    currentPageUrl = new URL("https://preview.internal:5173/search?q=civ&offset=20");
    const rendered = render(SearchPage, {
      props: {
        data: {
          query: "civ",
          entityType: "",
          offset: 20,
          hasNext: true,
          hasUnrenderableResults: true,
          results: []
        }
      }
    });

    expect(rendered.head).toContain("civ (0 results shown) | Search | Civibus");
    expect(rendered.head).toContain(
      '0 results shown for &quot;civ&quot;; some matching records could not be displayed.'
    );
    expect(rendered.body).toContain(
      '<p class="search__status" data-testid="search-status" role="status" aria-live="polite">Matching records were found, but none could be displayed.'
    );

    const resultsRegion = getSearchResultsRegionMarkup(rendered.body);
    expect(resultsRegion).toContain('aria-label="Search results pagination"');
    expect(resultsRegion).toContain("0 displayable results on this page");
    expect(resultsRegion).not.toContain("Showing 0–0");
    expect(resultsRegion).toContain('href="/search?q=civ"');
    expect(resultsRegion).toContain('href="/search?q=civ&amp;offset=40"');
    expect(resultsRegion).not.toContain('class="card search__result"');
  });

  it("renders an unsafe-offset response as inline validation without rounded navigation", () => {
    const validationMessage =
      "The requested search page is too large to navigate safely. Submit the search to return to the first page.";
    const rendered = render(SearchPage, {
      props: {
        data: {
          query: "civ",
          entityType: "org",
          offset: 0,
          hasNext: false,
          results: [],
          hasUnavailableResultPage: true,
          validationMessage
        }
      }
    });

    expect(rendered.head).toContain('<title>civ | Search | Civibus</title>');
    expect(rendered.head).toContain(
      '<meta name="description" content="The requested results page for &quot;civ&quot; could not be displayed."'
    );
    expect(rendered.head).not.toContain("0 results");
    expect(rendered.body).toContain(validationMessage);
    expect(rendered.body).toContain(
      "The requested results page could not be displayed. Submit the search to return to the first page."
    );
    expect(rendered.body).not.toContain("No matching records found.");

    const queryInput = rendered.body.match(/<input[^>]*id="search-query"[^>]*>/)?.[0];
    expect(queryInput).toBeDefined();
    expect(queryInput).not.toContain('aria-invalid="true"');
    expect(queryInput).not.toContain('aria-describedby="search-validation-message"');

    const resultsRegion = getSearchResultsRegionMarkup(rendered.body);
    expect(resultsRegion).not.toContain('class="card search__result"');
    expect(resultsRegion).not.toContain('aria-label="Search results pagination"');
    expect(resultsRegion).not.toContain("Showing ");
    expect(resultsRegion).not.toContain(">Previous</a>");
    expect(resultsRegion).not.toContain(">Next</a>");
  });

  it("renders no pagination when everything fits one page", () => {
    currentPageUrl = new URL("https://preview.internal:5173/search?q=jane");
    const rendered = render(SearchPage, {
      props: {
        data: {
          query: "jane",
          entityType: "",
          offset: 0,
          hasNext: false,
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

    expect(rendered.body).not.toContain('aria-label="Search results pagination"');
  });

  // --- Five-state SSR regression matrix (Stage 3) ---

  describe("five-state SSR matrix", () => {
    it("empty state: renders guidance and browse links with a non-busy results region", () => {
      const rendered = render(SearchPage, {
        props: {
          data: {
            query: "",
            entityType: "",
            offset: 0,
            hasNext: false,
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
            offset: 0,
            hasNext: false,
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
            offset: 0,
            hasNext: false,
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

    it("unavailable-results state: reports matches without rendering unsafe links", () => {
      currentPageUrl = new URL("https://preview.internal:5173/search?q=civ");
      const rendered = render(SearchPage, {
        props: {
          data: {
            query: "civ",
            entityType: "",
            offset: 0,
            hasNext: false,
            hasUnrenderableResults: true,
            results: []
          }
        }
      });

      expect(rendered.body).toContain(
        '<p class="search__status" data-testid="search-status" role="status" aria-live="polite">Matching records were found, but none could be displayed.'
      );
      expect(rendered.body).not.toContain("No matching records found.");
      expect(rendered.head).toContain("civ (0 results shown) | Search | Civibus");
      expect(rendered.head).toContain(
        '0 results shown for &quot;civ&quot;; some matching records could not be displayed.'
      );

      const resultsRegion = getSearchResultsRegionMarkup(rendered.body);
      expect(resultsRegion).not.toContain('class="card search__result"');
      expect(resultsRegion).not.toContain('href="/candidate/H0NC01001"');
    });

    it("partial-results state: qualifies the card count in the live status", () => {
      currentPageUrl = new URL("https://preview.internal:5173/search?q=civ");
      const rendered = render(SearchPage, {
        props: {
          data: {
            query: "civ",
            entityType: "",
            offset: 0,
            hasNext: false,
            hasUnrenderableResults: true,
            results: [
              {
                entity_type: "org",
                entity_id: "22222222-2222-4222-8222-222222222222",
                name: "Civibus Org"
              }
            ]
          }
        }
      });

      expect(rendered.body).toContain(
        '<p class="search__status" data-testid="search-status" role="status" aria-live="polite">1 result shown. Some matching records could not be displayed.'
      );
      expect(rendered.body).not.toContain("1 result found.");
      expect(rendered.head).toContain("civ (1 result shown) | Search | Civibus");

      const resultsRegion = getSearchResultsRegionMarkup(rendered.body);
      expect(resultsRegion).toContain(
        'href="/org/22222222-2222-4222-8222-222222222222">Civibus Org</a>'
      );
    });

    it("validation-error state: renders inline validation copy with no stale cards or skeleton", () => {
      const rendered = render(SearchPage, {
        props: {
          data: {
            query: "civ",
            entityType: "org",
            offset: 0,
            hasNext: false,
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
            offset: 0,
            hasNext: false,
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
