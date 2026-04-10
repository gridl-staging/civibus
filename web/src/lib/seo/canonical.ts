/**
 * Builds an absolute canonical URL from the current page URL and an optional
 * trusted public origin (PUBLIC_ORIGIN env var). Query strings and hash
 * fragments are stripped so canonical / og:url tags are always clean.
 *
 * When publicOrigin is provided and non-empty, it overrides the page URL's
 * origin — this ensures canonical URLs point to the production domain even
 * when served behind a reverse proxy or on a dev port.
 */
export function buildCanonicalUrl(pageUrl: URL, publicOrigin: string | undefined): string {
  const base = publicOrigin || pageUrl.origin;
  return new URL(pageUrl.pathname, base).href;
}
