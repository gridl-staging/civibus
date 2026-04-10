import { buildCommitteeHref } from "$lib/campaign-finance-detail/contract";
import { loadCampaignFinanceDetailPage } from "$lib/campaign-finance-detail/page-load";
import { resolveCommitteeDetailRoute } from "$lib/campaign-finance-detail/detail-route";
import { fetchCommitteeDetailBundle } from "$lib/server/api/campaign-finance-detail";
import type { PageServerLoad } from "./$types";

/** Loads committee detail routes with slug collision handling and canonical redirects. */
export const load: PageServerLoad = ({ params, locals }) =>
  loadCampaignFinanceDetailPage({
    apiClient: locals.api,
    routeId: params.id,
    fallbackMessage: "Backend committee detail request failed.",
    resolveRoute: resolveCommitteeDetailRoute,
    fetchBundle: fetchCommitteeDetailBundle,
    buildCanonicalHref: buildCommitteeHref
  });
