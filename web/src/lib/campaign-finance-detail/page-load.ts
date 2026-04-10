import { redirect } from "@sveltejs/kit";
import { withApiResponseErrorHandling } from "$lib/server/api/error";
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

    if (routeResolution.routeIdType === "uuid" && data.detail.slug_is_unique && data.detail.slug !== "") {
      throw redirect(308, buildCanonicalHref(data.detail));
    }

    return {
      routeKind: "canonical-detail",
      ...data
    };
  }, fallbackMessage);
}
