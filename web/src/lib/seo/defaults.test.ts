import { describe, expect, it } from "vitest";
import { APP_SHELL } from "$lib/config/app";
import {
  DEFAULT_OG_IMAGE_PATH,
  DEFAULT_TWITTER_CARD,
  buildAbsoluteAssetUrl,
  buildSocialImageUrl,
  getSeoDefaults
} from "./defaults";

function fakePageUrl(href: string): URL {
  return new URL(href);
}

describe("getSeoDefaults", () => {
  it("uses APP_SHELL.branding.name as the single site-name source", () => {
    const defaults = getSeoDefaults();
    expect(defaults.siteName).toBe(APP_SHELL.branding.name);
  });

  it("returns the expected shared fallback values", () => {
    const defaults = getSeoDefaults();
    expect(defaults.twitterCard).toBe(DEFAULT_TWITTER_CARD);
    expect(defaults.socialImagePath).toBe(DEFAULT_OG_IMAGE_PATH);
  });

  it("returns a frozen shared defaults object", () => {
    const defaults = getSeoDefaults();
    expect(Object.isFrozen(defaults)).toBe(true);
  });
});

describe("buildAbsoluteAssetUrl", () => {
  it("joins the fallback social image path to an absolute public origin URL", () => {
    const pageUrl = fakePageUrl("https://internal.host:5173/candidate/abc?tab=summary");
    expect(buildAbsoluteAssetUrl(pageUrl, "https://civibus.us", DEFAULT_OG_IMAGE_PATH)).toBe(
      "https://civibus.us/og-default.png"
    );
  });

  it("returns null when no trusted public origin is configured", () => {
    const pageUrl = fakePageUrl("https://preview.internal:5173/candidate/abc?tab=summary");
    expect(buildAbsoluteAssetUrl(pageUrl, undefined, DEFAULT_OG_IMAGE_PATH)).toBeNull();
  });

  it("rejects absolute or scheme-relative asset paths", () => {
    const pageUrl = fakePageUrl("https://internal.host:5173/candidate/abc?tab=summary");
    expect(buildAbsoluteAssetUrl(pageUrl, "https://civibus.us", "https://evil.test/og.png")).toBeNull();
    expect(buildAbsoluteAssetUrl(pageUrl, "https://civibus.us", "//evil.test/og.png")).toBeNull();
  });
});

describe("buildSocialImageUrl", () => {
  it("uses the shared fallback asset when no image path is provided", () => {
    const pageUrl = fakePageUrl("https://internal.host:5173/candidate/abc?tab=summary");
    expect(buildSocialImageUrl(pageUrl, "https://civibus.us")).toBe("https://civibus.us/og-default.png");
  });

  it("returns null when a caller explicitly suppresses the social image", () => {
    const pageUrl = fakePageUrl("https://internal.host:5173/candidate/abc?tab=summary");
    expect(buildSocialImageUrl(pageUrl, "https://civibus.us", null)).toBeNull();
  });

  it("returns null when the public origin is not trusted", () => {
    const pageUrl = fakePageUrl("https://preview.internal:5173/candidate/abc?tab=summary");
    expect(buildSocialImageUrl(pageUrl, undefined)).toBeNull();
  });
});
