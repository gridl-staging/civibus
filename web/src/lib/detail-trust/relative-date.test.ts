import { describe, expect, it, vi } from "vitest";
import { formatRelativePullDate, formatAbsolutePullDate } from "./relative-date";

describe("formatRelativePullDate", () => {
  it("returns today when pull date and now are on the same UTC day", () => {
    expect(formatRelativePullDate("2026-03-23T00:01:00Z", new Date("2026-03-23T23:59:59Z"))).toBe("today");
  });

  it("returns a singular day label for one elapsed day", () => {
    expect(formatRelativePullDate("2026-03-22T23:59:59Z", new Date("2026-03-23T00:00:00Z"))).toBe("1 day ago");
  });

  it("returns a plural day label for multiple elapsed days", () => {
    expect(formatRelativePullDate("2026-03-19T08:30:00Z", new Date("2026-03-23T09:00:00Z"))).toBe("4 days ago");
  });

  it("uses the system clock when now is not provided", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-03-23T09:00:00Z"));

    try {
      expect(formatRelativePullDate("2026-03-21T23:59:59Z")).toBe("2 days ago");
    } finally {
      vi.useRealTimers();
    }
  });

  it("handles large day gaps", () => {
    expect(formatRelativePullDate("2025-03-23T12:00:00Z", new Date("2026-03-23T12:00:00Z"))).toBe("365 days ago");
  });

  it("handles future dates with singular day label", () => {
    expect(formatRelativePullDate("2026-03-24T12:00:00Z", new Date("2026-03-23T12:00:00Z"))).toBe("in 1 day");
  });

  it("handles future dates with plural day label", () => {
    expect(formatRelativePullDate("2026-03-26T12:00:00Z", new Date("2026-03-23T12:00:00Z"))).toBe("in 3 days");
  });

  it("treats same UTC day as today even when wall-clock hours differ widely", () => {
    expect(formatRelativePullDate("2026-03-23T00:00:01Z", new Date("2026-03-23T23:59:58Z"))).toBe("today");
  });

  it("throws on unparseable pull date", () => {
    expect(() => formatRelativePullDate("not-a-date", new Date("2026-03-23T12:00:00Z"))).toThrow(TypeError);
  });
});

describe("formatAbsolutePullDate", () => {
  it("returns YYYY-MM-DD from a UTC timestamp", () => {
    expect(formatAbsolutePullDate("2026-03-20T14:30:00Z")).toBe("2026-03-20");
  });

  it("respects UTC date for timezone-offset timestamps", () => {
    // 2026-03-19T23:30:00-05:00 = 2026-03-20T04:30:00Z
    expect(formatAbsolutePullDate("2026-03-19T23:30:00-05:00")).toBe("2026-03-20");
  });

  it("zero-pads single-digit months and days", () => {
    expect(formatAbsolutePullDate("2026-01-05T00:00:00Z")).toBe("2026-01-05");
  });

  it("throws on unparseable pull date", () => {
    expect(() => formatAbsolutePullDate("garbage")).toThrow(TypeError);
  });
});
