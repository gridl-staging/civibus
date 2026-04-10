import { withApiResponseErrorHandling } from "$lib/server/api/error";
import { fetchCandidacyDetail } from "$lib/server/api/civic-detail";
import type { PageServerLoad } from "./$types";

export const load: PageServerLoad = ({ params, locals }) =>
  withApiResponseErrorHandling(
    () => fetchCandidacyDetail(locals.api, { id: params.id }),
    "Backend candidacy detail request failed."
  );
