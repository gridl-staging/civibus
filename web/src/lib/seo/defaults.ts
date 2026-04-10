/** Shared SEO defaults and trusted-origin helpers. */
import { APP_SHELL } from "$lib/config/app";
import { buildCanonicalUrl } from "./canonical";

export const DEFAULT_TWITTER_CARD = "summary_large_image";
export const DEFAULT_OG_IMAGE_PATH = "/og-default.png";

export type SeoDefaults = Readonly<{
  siteName: string;
  twitterCard: typeof DEFAULT_TWITTER_CARD;
  socialImagePath: typeof DEFAULT_OG_IMAGE_PATH;
}>;

const SEO_DEFAULTS = Object.freeze({
  siteName: APP_SHELL.branding.name,
  twitterCard: DEFAULT_TWITTER_CARD,
  socialImagePath: DEFAULT_OG_IMAGE_PATH
}) satisfies SeoDefaults;

export function getSeoDefaults(): SeoDefaults {
  return SEO_DEFAULTS;
}

/** Accepts only absolute HTTP(S) origins for canonical URL generation. */
export function getTrustedPublicOrigin(publicOrigin: string | undefined): string | null {
  if (!publicOrigin || publicOrigin.trim() === "") {
    return null;
  }

  try {
    const parsedOrigin = new URL(publicOrigin);
    if (parsedOrigin.protocol !== "http:" && parsedOrigin.protocol !== "https:") {
      return null;
    }

    return parsedOrigin.origin;
  } catch {
    return null;
  }
}

function isSiteRelativeAssetPath(assetPath: string): boolean {
  return assetPath.startsWith("/") && !assetPath.startsWith("//");
}

export function buildTrustedCanonicalUrl(
  pageUrl: URL,
  publicOrigin: string | undefined
): string | null {
  const trustedPublicOrigin = getTrustedPublicOrigin(publicOrigin);
  return trustedPublicOrigin === null ? null : buildCanonicalUrl(pageUrl, trustedPublicOrigin);
}

export function buildAbsoluteAssetUrl(
  pageUrl: URL,
  publicOrigin: string | undefined,
  assetPath: string
): string | null {
  const canonicalPageUrl = buildTrustedCanonicalUrl(pageUrl, publicOrigin);
  if (canonicalPageUrl === null || !isSiteRelativeAssetPath(assetPath)) {
    return null;
  }

  return new URL(assetPath, canonicalPageUrl).href;
}

export function buildSocialImageUrl(
  pageUrl: URL,
  publicOrigin: string | undefined,
  imagePath?: string | null
): string | null {
  const resolvedImagePath = imagePath === undefined ? getSeoDefaults().socialImagePath : imagePath;
  return resolvedImagePath === null
    ? null
    : buildAbsoluteAssetUrl(pageUrl, publicOrigin, resolvedImagePath);
}

export function buildDefaultSocialImageUrl(
  pageUrl: URL,
  publicOrigin: string | undefined
): string | null {
  return buildSocialImageUrl(pageUrl, publicOrigin);
}
