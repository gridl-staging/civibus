import { readFileSync } from "node:fs";
import { render } from "svelte/server";
import { describe, expect, it, vi } from "vitest";
import type { CompareColumn, ResolvedPersonMoneyBundle } from "./+page.server";
import ComparePage from "./+page.svelte";
import type { ActionData } from "./$types";

let currentPageUrl = new URL("https://preview.internal:5173/compare?people=ada,ben&notice=max-4");

vi.mock("$env/dynamic/public", () => ({
  env: {
    PUBLIC_ORIGIN: "https://civibus.test"
  }
}));

vi.mock("$app/stores", () => ({
  navigating: {
    subscribe(run: (value: null) => void): () => void {
      run(null);
      return () => {};
    }
  },
  page: {
    subscribe(run: (value: { url: URL }) => void): () => void {
      run({ url: currentPageUrl });
      return () => {};
    }
  }
}));

function resolved<T>(value: T): Promise<T> {
  return Promise.resolve(value);
}

function buildColumn(personId: string, name: string): CompareColumn {
  return {
    personId,
    person: {
      entityType: "person",
      detail: {
        id: personId,
        canonical_name: name,
        name_variants: [],
        first_name: name.split(" ")[0] ?? null,
        middle_name: null,
        last_name: name.split(" ").slice(1).join(" ") || null,
        suffix: null,
        occupation: null,
        education: null,
        date_of_birth: null,
        year_of_birth: null,
        bio_text: null,
        bio_source_url: null,
        bio_license: null,
        bio_pulled_at: null,
        identifiers: {},
        primary_address_id: null,
        er_cluster_id: null,
        er_confidence: null,
        portrait: null,
        sources: []
      }
    },
    money: resolved({} as ResolvedPersonMoneyBundle)
  };
}

describe("/compare page", () => {
  it("renders clean compare SEO, breadcrumb, notices, chips, add-search controls, and per-column skeletons", () => {
    currentPageUrl = new URL("https://preview.internal:5173/compare?people=ada,ben&notice=max-4");
    const rendered = render(ComparePage, {
      props: {
        data: {
          columns: [buildColumn("ada", "Ada North"), buildColumn("ben", "Ben South")],
          notices: ["max-4"],
          canonicalComparison: {
            people: "ada,ben",
            href: "/compare?people=ada,ben"
          },
          prompt: null
        }
      }
    });

    expect(rendered.head).toContain("<title>Compare Officeholders | Civibus</title>");
    expect(rendered.head).toContain('<meta name="robots" content="noindex"');
    expect(rendered.head).toContain(
      '<link rel="canonical" href="https://civibus.test/compare?people=ada,ben"'
    );
    expect(rendered.head).not.toContain("notice=max-4");
    expect(rendered.body).toContain('aria-label="Breadcrumb"');
    expect(rendered.body).toContain("Home");
    expect(rendered.body).toContain("Compare");
    expect(rendered.body).toContain("Only the first four officeholders can be compared at once.");
    expect(rendered.body).toContain('href="/person/ada"');
    expect(rendered.body).toContain('href="/person/ben"');
    expect(rendered.body).toContain('href="/compare?people=ben"');
    expect(rendered.body).toContain('action="/compare?people=ada,ben&amp;/addSearch"');
    expect(rendered.body).toContain('aria-label="Compare column for Ada North"');
    expect(rendered.body).toContain('aria-label="Compare column for Ben South"');
    expect(rendered.body.match(/aria-label="Campaign finance column loading"/g)).toHaveLength(2);
  });

  it("renders one-person prompt, inline validation, and suggestion links without mutating the current comparison URL", () => {
    currentPageUrl = new URL("https://preview.internal:5173/compare?people=ada");
    const form = {
      query: "bea",
      suggestions: [
        {
          entity_type: "person",
          entity_id: "bea",
          name: "Bea East"
        }
      ],
      validationMessage: "Use at least two characters."
    } as ActionData;
    const rendered = render(ComparePage, {
      props: {
        data: {
          columns: [buildColumn("ada", "Ada North")],
          notices: [],
          canonicalComparison: null,
          prompt: { kind: "add-officeholder" }
        },
        form
      }
    });

    expect(rendered.head).toContain('<link rel="canonical" href="https://civibus.test/compare"');
    expect(rendered.body).toContain("Choose at least two officeholders to compare campaign finance.");
    expect(rendered.body).toContain("Use at least two characters.");
    expect(rendered.body).toContain('action="/compare?people=ada&amp;/addSearch"');
    expect(rendered.body).toContain('href="/compare?people=ada,bea"');
    expect(rendered.body).not.toContain('href="/compare?people=bea"');
  });

  it("does not render stale add-search suggestion links when four columns are already selected", () => {
    currentPageUrl = new URL("https://preview.internal:5173/compare?people=ada,bea,cal,dan");
    const form = {
      query: "eve",
      suggestions: [
        {
          entity_type: "person",
          entity_id: "eve",
          name: "Eve West"
        }
      ]
    } as ActionData;
    const rendered = render(ComparePage, {
      props: {
        data: {
          columns: [
            buildColumn("ada", "Ada North"),
            buildColumn("bea", "Bea East"),
            buildColumn("cal", "Cal South"),
            buildColumn("dan", "Dan West")
          ],
          notices: [],
          canonicalComparison: {
            people: "ada,bea,cal,dan",
            href: "/compare?people=ada,bea,cal,dan"
          },
          prompt: null
        },
        form
      }
    });

    expect(rendered.body).toContain("Remove an officeholder before adding another comparison column.");
    expect(rendered.body).not.toContain("Eve West");
    expect(rendered.body).not.toContain('href="/compare?people=ada,bea,cal,dan,eve"');
  });

  it("passes one shared chart domain and caption to every column's chart rows", () => {
    // The settled grid lives behind {#await}, which svelte/server renders in its
    // pending branch, so the wiring is asserted here and the rendered shared scale
    // is covered by the compare browser probes.
    const source = readFileSync(new URL("./+page.svelte", import.meta.url), "utf8");

    for (const scaleKey of ["monthlyContributions", "sizeBucketDollars", "outsideSpending"]) {
      expect(source).toContain(`scaleMax={presentation.chartScales.${scaleKey}.max}`);
      expect(source).toContain(
        `Shared scale maximum: {presentation.chartScales.${scaleKey}.maxLabel}`
      );
    }
  });

  it("keeps the compare page on one settled-grid path instead of independent per-column scales", () => {
    const source = readFileSync(new URL("./+page.svelte", import.meta.url), "utf8");
    const allSettledIndex = source.indexOf("Promise.allSettled(data.columns.map(({ money }) => money))");
    const presentationIndex = source.indexOf("buildComparePresentation(data.columns, outcomes)");

    expect(allSettledIndex).toBeGreaterThan(-1);
    expect(presentationIndex).toBeGreaterThan(allSettledIndex);
    expect(source).not.toContain("Promise.all(data.columns");
  });
});
