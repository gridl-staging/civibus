import { describe, expect, it } from "vitest";
import {
  STATE_COVERAGE_TIER_VALUES,
  STATE_SUPPORT_STATUS_VALUES
} from "$lib/server/api/state-pages-contract";
import { smokeFixtures } from "../../tests/smoke/fixture-data";

describe("landing map smoke fixture contract", () => {
  it("uses only backend support_status enum values", () => {
    for (const summary of smokeFixtures.landingMap.summaries) {
      expect(STATE_SUPPORT_STATUS_VALUES).toContain(summary.support_status);
    }
  });

  it("keeps warning support_status rows non-navigable", () => {
    const warningRows = smokeFixtures.landingMap.summaries.filter(
      (summary) => summary.support_status === "warning"
    );

    expect(warningRows.length).toBeGreaterThan(0);

    for (const summary of warningRows) {
      expect(summary.supported).toBe(false);
    }
  });

  it("uses only backend coverage_tier enum values or null", () => {
    for (const summary of smokeFixtures.landingMap.summaries) {
      if (summary.coverage_tier === null) {
        expect(summary.coverage_tier).toBeNull();
        continue;
      }
      expect(STATE_COVERAGE_TIER_VALUES).toContain(summary.coverage_tier);
    }
  });
});
