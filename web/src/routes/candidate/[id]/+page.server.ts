import { buildCandidateHref } from "$lib/campaign-finance-detail/contract";
import { loadCampaignFinanceDetailPage } from "$lib/campaign-finance-detail/page-load";
import { resolveCandidateDetailRoute } from "$lib/campaign-finance-detail/detail-route";
import { fetchCandidateDetailBundle } from "$lib/server/api/campaign-finance-detail";
import type { PageServerLoad } from "./$types";

/** Loads candidate detail routes with slug collision handling and canonical redirects. */
export const load: PageServerLoad = ({ params, locals }) =>
  loadCampaignFinanceDetailPage({
    apiClient: locals.api,
    routeId: params.id,
    fallbackMessage: "Backend candidate detail request failed.",
    resolveRoute: resolveCandidateDetailRoute,
    fetchBundle: fetchCandidateDetailBundle,
    buildCanonicalHref: buildCandidateHref
  });
