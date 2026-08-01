import {
  fetchEntityDetailBundle
} from "$lib/server/api/entity-detail";
import { withApiResponseErrorHandling } from "$lib/server/api/error";
import { loadPersonMoneyBundle } from "$lib/server/api/person-money-bundle";
import type { PersonCandidateFinanceSection } from "$lib/server/api/campaign-finance-detail";
import { error } from "@sveltejs/kit";
import type { PageServerLoad } from "./$types";

const INVALID_CYCLE_ERROR = {
  message: "Invalid cycle query parameter.",
  detail: "The cycle query parameter must be a single four-digit election cycle."
};

/**
 */
function parseSelectedCycle(searchParams: URLSearchParams): number | undefined {
  const cycleValues = searchParams.getAll("cycle");
  if (cycleValues.length === 0) {
    return undefined;
  }

  if (cycleValues.length !== 1) {
    throw error(400, INVALID_CYCLE_ERROR);
  }

  const rawCycle = cycleValues[0].trim();
  if (!/^\d{4}$/.test(rawCycle)) {
    throw error(400, INVALID_CYCLE_ERROR);
  }

  return Number(rawCycle);
}

function fulfilledValueOrOriginal<T>(
  outcome: PromiseSettledResult<T>,
  original: T | Promise<T>
): T | Promise<T> {
  return outcome.status === "fulfilled" ? outcome.value : original;
}

async function resolvePersonFinanceSection(
  section: PersonCandidateFinanceSection
): Promise<PersonCandidateFinanceSection> {
  const [summary, ieSummary, ieTransactions, donorVendorTransactions] = await Promise.all([
    section.summary,
    section.ieSummary,
    section.ieTransactions,
    section.donorVendorTransactions
  ]);

  return {
    ...section,
    summary,
    ieSummary,
    ieTransactions,
    donorVendorTransactions
  };
}

async function resolvePersonFinanceSections(
  sections: Promise<PersonCandidateFinanceSection[]>
): Promise<PersonCandidateFinanceSection[]> {
  return Promise.all((await sections).map(resolvePersonFinanceSection));
}

/**
 */
export const load: PageServerLoad = ({ params, locals, url }) =>
  withApiResponseErrorHandling(
    async () => {
      const requestedCycle = parseSelectedCycle(url.searchParams);
      const bundle = await fetchEntityDetailBundle(locals.api, {
        entityType: "person",
        id: params.id
      });
      const moneyBundle = requestedCycle === undefined
        ? loadPersonMoneyBundle(locals.api, params.id, {
            fallbackWhenBackendSelectedInsightsUnavailable: true
          })
        : await loadPersonMoneyBundle(locals.api, params.id, requestedCycle);
      const personMoneyHeadline = await moneyBundle.personMoneyHeadline;
      const personFinanceSections = Promise.resolve(
        await resolvePersonFinanceSections(moneyBundle.personFinanceSections)
      );
      if (requestedCycle === undefined) {
        return {
          ...bundle,
          ...moneyBundle,
          personMoneyHeadline,
          personFinanceSections
        };
      }

      const [contributionInsightsOutcome, topDonorsOutcome, topEmployersOutcome] =
        await Promise.allSettled([
          moneyBundle.personContributionInsights,
          moneyBundle.personTopDonors,
          moneyBundle.personTopEmployers
        ]);

      return {
        ...bundle,
        ...moneyBundle,
        personMoneyHeadline,
        personFinanceSections,
        personContributionInsights: fulfilledValueOrOriginal(
          contributionInsightsOutcome,
          moneyBundle.personContributionInsights
        ),
        personTopDonors: fulfilledValueOrOriginal(
          topDonorsOutcome,
          moneyBundle.personTopDonors
        ),
        personTopEmployers: fulfilledValueOrOriginal(
          topEmployersOutcome,
          moneyBundle.personTopEmployers
        )
      };
    },
    "Backend person detail request failed."
  );
