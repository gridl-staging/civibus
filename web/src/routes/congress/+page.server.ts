import { fetchCongressMembers, fetchCongressMoneySummaries } from "$lib/server/api/civic-detail";
import { withApiResponseErrorHandling } from "$lib/server/api/error";
import type { PageServerLoad } from "./$types";

export const load: PageServerLoad = ({ locals }) =>
  withApiResponseErrorHandling(async () => {
    const [members, moneySummaryResult] = await Promise.all([
      fetchCongressMembers(locals.api),
      fetchCongressMoneySummaries(locals.api)
        .then((moneySummaries) => ({ moneySummaries, moneySummariesUnavailable: false }))
        .catch(() => ({ moneySummaries: [], moneySummariesUnavailable: true }))
    ]);

    return { members, ...moneySummaryResult };
  }, "Backend Congress member request failed.");
