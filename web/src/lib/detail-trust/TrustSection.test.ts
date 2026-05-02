import { describe, expect, it } from "vitest";
import { render } from "svelte/server";
import TrustSection from "./TrustSection.svelte";

const EXPECTED_INDIANA_FRESHNESS_NOTE =
  "Indiana bulk campaign finance data refreshes less often than weekly; this view may be up to 30 days stale.";

describe("TrustSection", () => {
  it("renders the Indiana freshness note as an additional warning line", () => {
    const rendered = render(TrustSection, {
      props: {
        trustSection: {
          rows: [],
          lastPulledSummary: "Last pulled: today (2026-03-21)",
          freshnessSeverity: "fresh",
          emptyMessage: "No source records are available for this detail yet.",
          advisoryMessage: "Review source records before publication.",
          freshnessNote: EXPECTED_INDIANA_FRESHNESS_NOTE
        }
      }
    });

    expect(rendered.body).toContain("Data is current.");
    expect(rendered.body).toContain(EXPECTED_INDIANA_FRESHNESS_NOTE);
  });

  it("omits the additional freshness warning line when no jurisdiction note applies", () => {
    const rendered = render(TrustSection, {
      props: {
        trustSection: {
          rows: [],
          lastPulledSummary: "Last pulled: today (2026-03-21)",
          freshnessSeverity: "fresh",
          emptyMessage: "No source records are available for this detail yet.",
          advisoryMessage: "Review source records before publication.",
          freshnessNote: null
        }
      }
    });

    expect(rendered.body).not.toContain(EXPECTED_INDIANA_FRESHNESS_NOTE);
  });
});
