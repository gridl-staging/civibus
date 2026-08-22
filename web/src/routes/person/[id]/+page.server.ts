import {
  fetchEntityDetailBundle
} from "$lib/server/api/entity-detail";
import { PersonPayloadContractError } from "$lib/entity-detail/contract";
import { withApiResponseErrorHandling } from "$lib/server/api/error";
import { loadPersonMoneyBundle } from "$lib/server/api/person-money-bundle";
import type { PersonCandidateFinanceSection } from "$lib/server/api/campaign-finance-detail";
import { error } from "@sveltejs/kit";
import type { PageServerLoad } from "./$types";

const INVALID_CYCLE_ERROR = {
  message: "Invalid cycle query parameter.",
  detail: "The cycle query parameter must be a single four-digit election cycle."
};

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
  const [summary, ieSummary, ieTransactions, donorVendorTransactions] = await Promise.allSettled([
    section.summary,
    section.ieSummary,
    section.ieTransactions,
    section.donorVendorTransactions
  ]);

  return {
    ...section,
    summary: fulfilledValueOrOriginal(summary, section.summary),
    ieSummary: fulfilledValueOrOriginal(ieSummary, section.ieSummary),
    ieTransactions: fulfilledValueOrOriginal(ieTransactions, section.ieTransactions),
    donorVendorTransactions: fulfilledValueOrOriginal(
      donorVendorTransactions,
      section.donorVendorTransactions
    )
  };
}

async function resolvePersonFinanceSections(
  sections: Promise<PersonCandidateFinanceSection[]>
): Promise<PersonCandidateFinanceSection[]> {
  return Promise.all((await sections).map(resolvePersonFinanceSection));
}

/**
 * Fetches the canonical person detail bundle, adapting the contract guard's
 * typed `PersonPayloadContractError` into a 502-class route error. A malformed
 * *core* person payload must never escape as a raw SvelteKit 500. Backend
 * `ApiResponseError`s (404/422) pass through to the outer route error handler.
 */
async function fetchPersonDetailBundleOrTypedError(
  apiClient: Parameters<typeof fetchEntityDetailBundle>[0],
  id: string
): ReturnType<typeof fetchEntityDetailBundle> {
  try {
    return await fetchEntityDetailBundle(apiClient, { entityType: "person", id });
  } catch (cause) {
    if (cause instanceof PersonPayloadContractError) {
      throw error(cause.status, cause.routeErrorBody);
    }
    throw cause;
  }
}

export const load: PageServerLoad = ({ params, locals, url }) =>
  withApiResponseErrorHandling(
    async () => {
      const requestedCycle = parseSelectedCycle(url.searchParams);
      const bundle = await fetchPersonDetailBundleOrTypedError(locals.api, params.id);
      const moneyBundle = requestedCycle === undefined
        ? loadPersonMoneyBundle(locals.api, params.id, {
            fallbackWhenBackendSelectedInsightsUnavailable: true
          })
        : await loadPersonMoneyBundle(locals.api, params.id, requestedCycle);
      const personMoneyHeadline = await moneyBundle.personMoneyHeadline;
      const [personFinanceSectionsOutcome] = await Promise.allSettled([
        resolvePersonFinanceSections(moneyBundle.personFinanceSections)
      ]);
      const personFinanceSections = personFinanceSectionsOutcome.status === "fulfilled"
        ? Promise.resolve(personFinanceSectionsOutcome.value)
        : moneyBundle.personFinanceSections;
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
