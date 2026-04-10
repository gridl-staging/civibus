/** Resolves campaign-finance route params into canonical detail ids or slug chooser states. */
import type { ApiClient } from "$lib/server/api/client";
import {
  fetchCandidatesBySlug,
  fetchCommitteesBySlug
} from "$lib/server/api/campaign-finance-detail";
import type { CandidateListItem, CommitteeListItem } from "$lib/campaign-finance-detail/contract";
import { error } from "@sveltejs/kit";

const UUID_36_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

type SlugMatchItem = CandidateListItem | CommitteeListItem;

type CanonicalDetailRouteResolution = {
  routeKind: "canonical-detail";
  canonicalId: string;
  routeIdType: "uuid" | "slug";
};

type SlugCollisionRouteResolution<TMatch extends SlugMatchItem> = {
  routeKind: "slug-collision";
  slug: string;
  matches: TMatch[];
};

export type CandidateDetailRouteResolution =
  | CanonicalDetailRouteResolution
  | SlugCollisionRouteResolution<CandidateListItem>;

export type CommitteeDetailRouteResolution =
  | CanonicalDetailRouteResolution
  | SlugCollisionRouteResolution<CommitteeListItem>;

function isUuidRouteId(routeId: string): boolean {
  return UUID_36_PATTERN.test(routeId);
}

function sortSlugMatches<TMatch extends SlugMatchItem>(matches: readonly TMatch[]): TMatch[] {
  return [...matches].sort((left, right) => {
    const nameOrder = left.name.localeCompare(right.name, "en", {
      sensitivity: "base"
    });

    if (nameOrder !== 0) {
      return nameOrder;
    }

    return left.id.localeCompare(right.id);
  });
}

/** Resolves UUID ids directly and slug ids through backend collision-aware lookup endpoints. */
async function resolveDetailRoute<TMatch extends SlugMatchItem>(params: {
  apiClient: ApiClient;
  routeId: string;
  label: "Candidate" | "Committee";
  fetchBySlug: (apiClient: ApiClient, slug: string) => Promise<TMatch[]>;
}): Promise<CanonicalDetailRouteResolution | SlugCollisionRouteResolution<TMatch>> {
  const { apiClient, routeId, label, fetchBySlug } = params;

  if (isUuidRouteId(routeId)) {
    return {
      routeKind: "canonical-detail",
      canonicalId: routeId,
      routeIdType: "uuid"
    };
  }

  const matches = await fetchBySlug(apiClient, routeId);

  if (matches.length === 0) {
    const slugNotFoundMessage = `${label} slug not found: ${routeId}`;
    throw error(404, {
      message: slugNotFoundMessage,
      detail: slugNotFoundMessage
    });
  }

  if (matches.length === 1) {
    return {
      routeKind: "canonical-detail",
      canonicalId: matches[0].id,
      routeIdType: "slug"
    };
  }

  return {
    routeKind: "slug-collision",
    slug: routeId,
    matches: sortSlugMatches(matches)
  };
}

export function resolveCandidateDetailRoute(
  apiClient: ApiClient,
  routeId: string
): Promise<CandidateDetailRouteResolution> {
  return resolveDetailRoute({
    apiClient,
    routeId,
    label: "Candidate",
    fetchBySlug: (client, slug) => fetchCandidatesBySlug(client, { slug })
  });
}

export function resolveCommitteeDetailRoute(
  apiClient: ApiClient,
  routeId: string
): Promise<CommitteeDetailRouteResolution> {
  return resolveDetailRoute({
    apiClient,
    routeId,
    label: "Committee",
    fetchBySlug: (client, slug) => fetchCommitteesBySlug(client, { slug })
  });
}
