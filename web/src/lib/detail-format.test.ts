import { describe, it, expect } from "vitest";
import { formatDisplayValue, formatBoolean } from "$lib/detail-format";

describe("formatDisplayValue", () => {
  it("returns the string as-is for string values", () => {
    expect(formatDisplayValue("hello")).toBe("hello");
  });

  it("converts numbers to strings", () => {
    expect(formatDisplayValue(42)).toBe("42");
  });

  it("returns em-dash for null", () => {
    expect(formatDisplayValue(null)).toBe("—");
  });

  it("returns em-dash for undefined", () => {
    expect(formatDisplayValue(undefined)).toBe("—");
  });

  it("returns '0' for zero (not em-dash)", () => {
    expect(formatDisplayValue(0)).toBe("0");
  });

  it("returns empty string for empty string (not em-dash)", () => {
    expect(formatDisplayValue("")).toBe("");
  });
});

describe("formatBoolean", () => {
  it("returns 'Yes' for true", () => {
    expect(formatBoolean(true)).toBe("Yes");
  });

  it("returns 'No' for false", () => {
    expect(formatBoolean(false)).toBe("No");
  });

  it("returns em-dash for null", () => {
    expect(formatBoolean(null)).toBe("—");
  });

  it("returns em-dash for undefined", () => {
    expect(formatBoolean(undefined)).toBe("—");
  });
});
