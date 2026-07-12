import { fetchCongressMembers } from "$lib/server/api/civic-detail";
import { withApiResponseErrorHandling } from "$lib/server/api/error";
import type { PageServerLoad } from "./$types";

export const load: PageServerLoad = ({ locals }) =>
  withApiResponseErrorHandling(async () => {
    const members = await fetchCongressMembers(locals.api);

    return { members };
  }, "Backend Congress member request failed.");
