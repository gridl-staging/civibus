import { describe, expect, it } from "vitest";
import {
  buildComparisonSegments,
  hasNoComparisonData,
  lightenColor,
  sharedScaleWidthPct
} from "./comparison-transforms";

describe("charts/comparison-transforms helpers", () => {
  it("returns the raw shared-scale width ratio without display rounding", () => {
    expect(sharedScaleWidthPct(100_000, 300_000)).toBe(1 / 3);
  });

  it("preserves fixed legacy segment order and absolute tooltip text", () => {
    const result = buildComparisonSegments({
      total: 100_000,
      segments: [
        { id: "other", label: "Other Donations", value: 75_000, color: "#0f766e" },
        { id: "self", label: "Self-Funded", value: 25_000, color: "#6fada8" },
        { id: "unknown", label: "Unknown", value: 5_000, color: "#94a3b8" }
      ],
      segmentOrder: ["Self-Funded", "Other Donations"]
    });

    expect(result).toMatchObject({
      kind: "ready",
      total: 100_000,
      segments: [
        {
          id: "self",
          label: "Self-Funded",
          value: 25_000,
          widthPct: 0.25,
          percentage: 25,
          tooltipText: "$25,000.00 (25.0%)"
        },
        {
          id: "other",
          label: "Other Donations",
          value: 75_000,
          widthPct: 0.75,
          percentage: 75,
          tooltipText: "$75,000.00 (75.0%)"
        },
        {
          id: "unknown",
          label: "Unknown",
          value: 5_000,
          widthPct: 0.05,
          percentage: 5,
          tooltipText: "$5,000.00 (5.0%)"
        }
      ]
    });
  });

  it("matches the legacy self-funded color lightening formula", () => {
    // Legacy 0.4 lightening ratio: 15,118,110 -> 111,173,168.
    expect(lightenColor("#0f766e")).toBe("#6fada8");
  });

  it("returns an explicit no-data marker without NaN display values", () => {
    const result = buildComparisonSegments({
      total: 0,
      segments: [{ id: "self", label: "Self-Funded", value: 0, color: "#6fada8" }],
      segmentOrder: ["Self-Funded", "Other Donations"]
    });

    expect(result).toEqual({
      kind: "no-data",
      message: "No comparison data is available.",
      total: 0,
      segments: [
        {
          id: "self",
          label: "Self-Funded",
          value: 0,
          color: "#6fada8",
          widthPct: 0,
          percentage: 0,
          tooltipText: "$0.00 (0.0%)"
        }
      ]
    });
    expect(hasNoComparisonData(result)).toBe(true);

    for (const segment of result.segments) {
      expect(Number.isNaN(segment.widthPct)).toBe(false);
      expect(Number.isNaN(segment.percentage)).toBe(false);
      expect(segment.tooltipText).not.toContain("NaN");
    }
  });
});
