import { withApiResponseErrorHandling } from "$lib/server/api/error";
import { fetchParcelDetail } from "$lib/server/api/property-detail";
import type { PageServerLoad } from "./$types";

export const load: PageServerLoad = ({ params, locals }) =>
  withApiResponseErrorHandling(
    () => fetchParcelDetail(locals.api, { id: params.id }),
    "Backend property detail request failed."
  );
