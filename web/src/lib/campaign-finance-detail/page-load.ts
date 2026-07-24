import { redirect } from "@sveltejs/kit";
import { withApiResponseErrorHandling } from "$lib/server/api/error";
import { encodeRoutePathSegment } from "$lib/entity-detail/contract";
import type { ApiClient } from "$lib/server/api/client";

type CanonicalRouteResolution = {
  routeKind: "canonical-detail";
  canonicalId: string;
  routeIdType: "uuid" | "slug";
};

type SlugCollisionRouteResolution<TMatch> = {
  routeKind: "slug-collision";
  slug: string;
  matches: TMatch[];
};

type DetailRouteResolution<TMatch> =
  | CanonicalRouteResolution
  | SlugCollisionRouteResolution<TMatch>;

type CanonicalSlugDetail = {
  id: string;
  slug: string;
  slug_is_unique: boolean;
};

type DetailBundle<TDetail extends CanonicalSlugDetail> = {
  detail: TDetail;
};

type DetailRequest = {
  id: string;
};

type DetailPageLoadOptions<
  TMatch,
  TDetail extends CanonicalSlugDetail,
  TBundle extends DetailBundle<TDetail>
> = {
  apiClient: ApiClient;
  routeId: string;
  fallbackMessage: string;
  resolveRoute: (
    apiClient: ApiClient,
    routeId: string
  ) => Promise<DetailRouteResolution<TMatch>>;
  fetchBundle: (apiClient: ApiClient, request: DetailRequest) => Promise<TBundle>;
  buildCanonicalHref: (detail: TDetail) => string;
};

function buildCurrentDetailHref(canonicalHref: string, routeId: string): string {
  const routeSegment = canonicalHref.split("/")[1];
  return `/${routeSegment}/${encodeRoutePathSegment(routeId)}`;
}

/**
 * Shared detail-page loader for campaign-finance routes that support UUID ids,
 * slug lookups, slug-collision chooser states, and canonical slug redirects.
 */
export async function loadCampaignFinanceDetailPage<
  TMatch,
  TDetail extends CanonicalSlugDetail,
  TBundle extends DetailBundle<TDetail>
>(
  options: DetailPageLoadOptions<TMatch, TDetail, TBundle>
): Promise<DetailRouteResolution<TMatch> | ({ routeKind: "canonical-detail" } & TBundle)> {
  const { apiClient, routeId, fallbackMessage, resolveRoute, fetchBundle, buildCanonicalHref } =
    options;

  return withApiResponseErrorHandling(async () => {
    const routeResolution = await resolveRoute(apiClient, routeId);

    if (routeResolution.routeKind === "slug-collision") {
      return routeResolution;
    }

    const data = await fetchBundle(apiClient, {
      id: routeResolution.canonicalId
    });
    const canonicalHref = buildCanonicalHref(data.detail);
    const currentHref = buildCurrentDetailHref(canonicalHref, routeId);

    if (canonicalHref !== currentHref) {
      throw redirect(308, canonicalHref);
    }

    return {
      routeKind: "canonical-detail",
      ...data
    };
  }, fallbackMessage);
}
