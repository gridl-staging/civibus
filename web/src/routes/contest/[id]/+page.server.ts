import { withApiResponseErrorHandling } from "$lib/server/api/error";
import { fetchContestDetail } from "$lib/server/api/civic-detail";
import { fetchContestCandidateFinanceByPersonId } from "$lib/server/api/campaign-finance-detail";
import {
  createGeometryByLevelRecord,
  fetchOptionalCivicGeometry,
  toCivicGeometryLevel
} from "$lib/server/api/civic-geometry";
import type { PageServerLoad } from "./$types";

function parseSelectedCycleParam(value: string | null): number | undefined {
  if (value === null || value.trim() === "") {
    return undefined;
  }

  const parsed = Number(value);
  return Number.isInteger(parsed) ? parsed : undefined;
}

/**
 */
function parseElectionYearCycle(electionDate: string | null | undefined): number | undefined {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(electionDate ?? "");
  if (match === null) {
    return undefined;
  }

  const [, year, month, day] = match;
  const parsedDate = new Date(`${year}-${month}-${day}T00:00:00Z`);
  if (
    Number.isNaN(parsedDate.getTime()) ||
    parsedDate.getUTCFullYear() !== Number(year) ||
    parsedDate.getUTCMonth() + 1 !== Number(month) ||
    parsedDate.getUTCDate() !== Number(day)
  ) {
    return undefined;
  }

  return Number(year);
}

/**
 */
export const load: PageServerLoad = ({ params, locals, url }) =>
  withApiResponseErrorHandling(async () => {
    const contest = await fetchContestDetail(locals.api, { id: params.id });
    const selectedCycle =
      parseSelectedCycleParam(url.searchParams.get("cycle")) ??
      parseElectionYearCycle(contest.election_date);
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
            })),
            cycle: selectedCycle
          });

    return {
      contest,
      geometryByLevel,
      contestCandidateFinanceByPersonId,
      contestSelectedCycle: selectedCycle ?? null
    };
  }, "Backend contest detail request failed.");
