import { describe, expect, it } from "vitest";
import { buildCanonicalUrl } from "./canonical";

/** Minimal URL-like object matching the subset of URL consumed by buildCanonicalUrl. */
function fakePageUrl(href: string): URL {
  return new URL(href);
}

describe("buildCanonicalUrl", () => {
  it("uses publicOrigin as the base when provided", () => {
    const pageUrl = fakePageUrl("https://internal.host:3000/candidate/abc");
    expect(buildCanonicalUrl(pageUrl, "https://civibus.us")).toBe(
      "https://civibus.us/candidate/abc"
    );
  });

  it("falls back to pageUrl.origin when publicOrigin is undefined", () => {
    const pageUrl = fakePageUrl("https://fallback.host/committee/xyz");
    expect(buildCanonicalUrl(pageUrl, undefined)).toBe("https://fallback.host/committee/xyz");
  });

  it("falls back to pageUrl.origin when publicOrigin is empty string", () => {
    const pageUrl = fakePageUrl("https://fallback.host/person/123");
    expect(buildCanonicalUrl(pageUrl, "")).toBe("https://fallback.host/person/123");
  });

  it("strips query strings from the canonical URL", () => {
    const pageUrl = fakePageUrl("https://host.local/methodology?tab=about&ref=nav");
    expect(buildCanonicalUrl(pageUrl, "https://civibus.us")).toBe(
      "https://civibus.us/methodology"
    );
  });

  it("strips hash fragments from the canonical URL", () => {
    const pageUrl = fakePageUrl("https://host.local/person/abc#section-2");
    expect(buildCanonicalUrl(pageUrl, "https://civibus.us")).toBe(
      "https://civibus.us/person/abc"
    );
  });

  it("strips both query and hash simultaneously", () => {
    const pageUrl = fakePageUrl("https://host.local/org/def?q=test#top");
    expect(buildCanonicalUrl(pageUrl, "https://civibus.us")).toBe("https://civibus.us/org/def");
  });

  it("produces a clean root URL for the homepage", () => {
    const pageUrl = fakePageUrl("https://host.local/?utm=abc");
    expect(buildCanonicalUrl(pageUrl, "https://civibus.us")).toBe("https://civibus.us/");
  });

  it("preserves encoded path segments without double-encoding", () => {
    const pageUrl = fakePageUrl("https://host.local/candidate/john%20doe");
    expect(buildCanonicalUrl(pageUrl, "https://civibus.us")).toBe(
      "https://civibus.us/candidate/john%20doe"
    );
  });
});
