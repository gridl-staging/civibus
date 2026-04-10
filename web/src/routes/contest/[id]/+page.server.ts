import { withApiResponseErrorHandling } from "$lib/server/api/error";
import { fetchContestDetail } from "$lib/server/api/civic-detail";
import type { PageServerLoad } from "./$types";

export const load: PageServerLoad = ({ params, locals }) =>
  withApiResponseErrorHandling(
    () => fetchContestDetail(locals.api, { id: params.id }),
    "Backend contest detail request failed."
  );
