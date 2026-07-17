import { fetchCongressMembers, fetchCongressMoneySummaries } from "$lib/server/api/civic-detail";
import { withApiResponseErrorHandling } from "$lib/server/api/error";
import type { CongressMemberMoneySummary } from "$lib/civic-detail/contract";
import type { PageServerLoad } from "./$types";

export const load: PageServerLoad = ({ locals }) =>
  withApiResponseErrorHandling(async () => {
    const members = await fetchCongressMembers(locals.api);
    let moneySummaries: CongressMemberMoneySummary[] = [];

    try {
      moneySummaries = await fetchCongressMoneySummaries(locals.api);
    } catch {
      moneySummaries = [];
    }

    return { members, moneySummaries };
  }, "Backend Congress member request failed.");
