import { withApiResponseErrorHandling } from "$lib/server/api/error";
import { fetchOfficeholdingDetail } from "$lib/server/api/civic-detail";
import type { PageServerLoad } from "./$types";

export const load: PageServerLoad = ({ params, locals }) =>
  withApiResponseErrorHandling(
    () => fetchOfficeholdingDetail(locals.api, { id: params.id }),
    "Backend officeholding detail request failed."
  );
