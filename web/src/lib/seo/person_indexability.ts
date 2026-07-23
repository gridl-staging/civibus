export type PersonRouteIndexability = Readonly<{
  hasSsrRichContent: boolean;
  isIndexable: boolean;
  robots: "noindex" | null;
}>;

export const PERSON_ROUTE_HAS_SSR_RICH_CONTENT = true;

export const PERSON_ROUTE_INDEXABILITY = Object.freeze({
  hasSsrRichContent: PERSON_ROUTE_HAS_SSR_RICH_CONTENT,
  isIndexable: PERSON_ROUTE_HAS_SSR_RICH_CONTENT,
  robots: PERSON_ROUTE_HAS_SSR_RICH_CONTENT ? null : "noindex"
}) satisfies PersonRouteIndexability;
