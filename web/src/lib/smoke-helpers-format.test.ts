import { describe, expect, it } from "vitest";

import { formatCapturedBrowserValue } from "../../tests/smoke/smoke-helpers";

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
