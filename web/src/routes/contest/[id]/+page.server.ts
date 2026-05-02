import { withApiResponseErrorHandling } from "$lib/server/api/error";
import { fetchContestDetail } from "$lib/server/api/civic-detail";
import { fetchContestCandidateFinanceByPersonId } from "$lib/server/api/campaign-finance-detail";
import {
  createGeometryByLevelRecord,
  fetchOptionalCivicGeometry,
  toCivicGeometryLevel
} from "$lib/server/api/civic-geometry";
import type { PageServerLoad } from "./$types";

export const load: PageServerLoad = ({ params, locals }) =>
  withApiResponseErrorHandling(async () => {
    const contest = await fetchContestDetail(locals.api, { id: params.id });
    const level = toCivicGeometryLevel(contest.electoral_division_type);
    const stateCode = contest.electoral_division_state?.toUpperCase() ?? null;
    const geometryByLevel = createGeometryByLevelRecord();

    if (level !== null && stateCode !== null) {
      geometryByLevel[level] = await fetchOptionalCivicGeometry(locals.api, {
        level,
        state: stateCode
      });
    }

    const contestCandidateFinanceByPersonId =
      contest.candidacies.length === 0
        ? {}
        : await fetchContestCandidateFinanceByPersonId(locals.api, {
            candidacies: contest.candidacies.map((candidacy) => ({
              personId: candidacy.person_id
            }))
          });

    return { contest, geometryByLevel, contestCandidateFinanceByPersonId };
  }, "Backend contest detail request failed.");
