import type {
  PersonContributionInsights,
  PersonTopEmployerRow,
  RankedTransactionParty
} from "$lib/campaign-finance-detail/contract";
import type { PersonCandidateFinanceSection } from "$lib/server/api/campaign-finance-detail";
import { ApiResponseError, type ApiClient } from "$lib/server/api/client";
import {
  fetchEntityDetailBundle,
  type EntityDetailBundle,
  type PersonDetailPageExtensions
} from "$lib/server/api/entity-detail";
import { withApiResponseErrorHandling } from "$lib/server/api/error";
import { loadPersonMoneyBundle } from "$lib/server/api/person-money-bundle";
import { getApiErrorDisplayMessage, throwApiResponseError } from "$lib/server/api/error";
import { fetchSearchResults } from "$lib/server/api/search";
import { filterRenderableSearchResults } from "$lib/search/contract";
import { fail, redirect } from "@sveltejs/kit";
import type { Actions, PageServerLoad } from "./$types";
import {
  buildCompareUrl,
  mergeCompareNotices,
  normalizePeopleQuery,
  type CompareNotice
} from "./people-query";

export type ResolvedPersonMoneyBundle = {
  personFinanceSections: PersonCandidateFinanceSection[];
  personContributionInsights: PersonContributionInsights;
  personTopDonors: RankedTransactionParty[];
  personTopEmployers: PersonTopEmployerRow[];
};

export type CompareColumn = {
  personId: string;
  person: EntityDetailBundle;
  money: Promise<ResolvedPersonMoneyBundle>;
};

function readFormValueAsString(formData: FormData, key: string): string {
  const rawValue = formData.get(key);
  return typeof rawValue === "string" ? rawValue : "";
}

function getSearchValidationMessage(errorBody: unknown): string {
  if (typeof errorBody === "string") {
    return errorBody;
  }

  if (errorBody && typeof errorBody === "object") {
    return getApiErrorDisplayMessage(errorBody as App.Error);
  }

  return "The search request could not be validated. Review your query and try again.";
}

function guardUnhandledRejection(promise: Promise<unknown>): void {
  void promise.catch(() => {});
}

/**
 */
async function fetchKnownPerson(
  apiClient: ApiClient,
  personId: string
): Promise<{ personId: string; person: EntityDetailBundle } | null> {
  try {
    const person = await fetchEntityDetailBundle(apiClient, {
      entityType: "person",
      id: personId
    });
    return { personId, person };
  } catch (cause) {
    if (cause instanceof ApiResponseError && cause.status === 404) {
      return null;
    }
    throw cause;
  }
}

/**
 */
function resolveMoneyBundle(
  bundle: PersonDetailPageExtensions
): Promise<ResolvedPersonMoneyBundle> {
  return Promise.all([
    bundle.personFinanceSections,
    bundle.personContributionInsights,
    bundle.personTopDonors,
    bundle.personTopEmployers
  ]).then(
    ([
      personFinanceSections,
      personContributionInsights,
      personTopDonors,
      personTopEmployers
    ]) => ({
      personFinanceSections,
      personContributionInsights,
      personTopDonors,
      personTopEmployers
    })
  );
}

function createCompareColumn(
  apiClient: ApiClient,
  knownPerson: { personId: string; person: EntityDetailBundle }
): CompareColumn {
  const bundle = loadPersonMoneyBundle(apiClient, knownPerson.personId);
  const money = resolveMoneyBundle(bundle);
  guardUnhandledRejection(money);

  return { ...knownPerson, money };
}

function collectNotices(
  queryNotices: readonly CompareNotice[],
  wasCapped: boolean,
  unknownPeopleWereDropped: boolean
): CompareNotice[] {
  const additions: CompareNotice[] = [];
  if (wasCapped) {
    additions.push("max-4");
  }
  if (unknownPeopleWereDropped) {
    additions.push("unknown-people-dropped");
  }
  return mergeCompareNotices(queryNotices, additions);
}

export const load = (({ locals, url }) =>
  withApiResponseErrorHandling(async () => {
    const peopleQuery = normalizePeopleQuery(url.searchParams);
    const resolvedPeople = await Promise.all(
      peopleQuery.peopleIds.map((personId) => fetchKnownPerson(locals.api, personId))
    );
    const knownPeople = resolvedPeople.filter(
      (person): person is NonNullable<typeof person> => person !== null
    );
    const knownPersonIds = knownPeople.map(({ personId }) => personId);
    const notices = collectNotices(
      peopleQuery.notices,
      peopleQuery.wasCapped,
      knownPeople.length !== resolvedPeople.length
    );

    if (peopleQuery.hadPopulatedInput && !peopleQuery.isCanonicalFor(knownPersonIds)) {
      throw redirect(301, buildCompareUrl(knownPersonIds, notices));
    }

    const columns = knownPeople.map((knownPerson) => createCompareColumn(locals.api, knownPerson));
    const hasCanonicalComparison = knownPersonIds.length >= 2;

    return {
      columns,
      notices,
      canonicalComparison: hasCanonicalComparison
        ? {
            people: knownPersonIds.join(","),
            href: buildCompareUrl(knownPersonIds)
          }
        : null,
      prompt: hasCanonicalComparison ? null : { kind: "add-officeholder" as const }
    };
  }, "Backend compare request failed.")) satisfies PageServerLoad;

export const actions: Actions = {
  addSearch: async ({ request, locals }) => {
    const formData = await request.formData();
    const query = readFormValueAsString(formData, "q");

    try {
      const results = await fetchSearchResults(locals.api, {
        q: query,
        entityType: "person"
      });

      return {
        query,
        suggestions: filterRenderableSearchResults(results).filter(
          (result) => result.entity_type === "person"
        )
      };
    } catch (cause) {
      if (cause instanceof ApiResponseError && cause.status === 422) {
        return fail(422, {
          query,
          suggestions: [],
          validationMessage: getSearchValidationMessage(cause.body)
        });
      }

      if (cause instanceof ApiResponseError) {
        throwApiResponseError(cause, "Backend compare search request failed.");
      }

      throw cause;
    }
  }
};
