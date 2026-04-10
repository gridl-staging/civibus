import { withApiResponseErrorHandling } from "$lib/server/api/error";
import { fetchOfficeDetail } from "$lib/server/api/civic-detail";
import type { PageServerLoad } from "./$types";

export const load: PageServerLoad = ({ params, locals }) =>
  withApiResponseErrorHandling(
    () => fetchOfficeDetail(locals.api, { id: params.id }),
    "Backend office detail request failed."
  );
