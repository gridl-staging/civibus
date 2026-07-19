import { describe, expect, it } from "vitest";

import {
  assertCampaignFinanceKeyMetricsTextReady,
  assertNoBackendFailureText,
  expectActionToVisibleContentWithinBudget,
  formatCapturedBrowserValue,
  parseRenderedMoneyLabel
} from "../../tests/smoke/smoke-helpers";

describe("smoke helper browser error formatting", () => {
  it("serializes non-Error rejection reasons instead of collapsing them to Object", () => {
    expect(formatCapturedBrowserValue({ message: "Internal Error" })).toBe(
      '{"message":"Internal Error"}'
    );
  });

  it("keeps Error messages concise", () => {
    expect(formatCapturedBrowserValue(new Error("chart failed"))).toBe("chart failed");
  });
});

describe("parseRenderedMoneyLabel", () => {
  it.each([
    ["$60.4M", 60_400_000],
    ["$1.2B", 1_200_000_000],
    ["$950K", 950_000],
    ["$1,234", 1_234],
    ["$1,234.56", 1_234.56],
    ["$0", 0]
  ])("parses %s as exact display dollars", (label, expectedDollars) => {
    expect(parseRenderedMoneyLabel(label)).toBe(expectedDollars);
  });

  it.each(["", "not money", "$NaN", "$Infinity", "$1T", "60.4M", "$-1K"])(
    "throws for invalid rendered money label %s",
    (label) => {
      expect(() => parseRenderedMoneyLabel(label)).toThrow(/rendered money/i);
    }
  );
});

describe("assertNoBackendFailureText", () => {
  it("rejects handled campaign-finance backend failure fallback content", () => {
    expect(() =>
      assertNoBackendFailureText("Key metrics\nCommittee metrics are temporarily unavailable.")
    ).toThrow(/backend failure/i);
  });

  it("allows healthy rendered metrics content", () => {
    expect(() =>
      assertNoBackendFailureText("Key metrics\nTotal raised\n$60.4M\nOfficial FEC committee summary")
    ).not.toThrow();
  });
});

describe("assertCampaignFinanceKeyMetricsTextReady", () => {
  it("rejects the handled fallback that shares the Key metrics heading", () => {
    expect(() =>
      assertCampaignFinanceKeyMetricsTextReady(
        "Key metrics\nCommittee metrics are temporarily unavailable."
      )
    ).toThrow(/backend failure/i);
  });

  it("rejects an empty metrics shell without loaded totals", () => {
    expect(() => assertCampaignFinanceKeyMetricsTextReady("Key metrics")).toThrow(/loaded totals/i);
  });

  it("rejects a metrics shell with labels but no loaded money value", () => {
    expect(() => assertCampaignFinanceKeyMetricsTextReady("Key metrics\nTotal raised")).toThrow(
      /money value/i
    );
  });

  it("allows rendered campaign-finance totals", () => {
    expect(() =>
      assertCampaignFinanceKeyMetricsTextReady(
        "Key metrics\nTotal raised\n$60.4M\nOfficial FEC committee summary"
      )
    ).not.toThrow();
  });
});

describe("expectActionToVisibleContentWithinBudget", () => {
  it("measures visible-content readiness before the action's later settlement work", async () => {
    let actionSettled = false;

    const elapsedMs = await expectActionToVisibleContentWithinBudget({
      label: "delayed navigation completion",
      budgetMs: 50,
      action: async () => {
        await new Promise<void>((resolve) => {
          setTimeout(() => {
            actionSettled = true;
            resolve();
          }, 100);
        });
      },
      visibleContent: async () => {
        await Promise.resolve();
      }
    });

    expect(elapsedMs).toBeLessThan(50);
    expect(actionSettled).toBe(true);
  });
});
