/** Fetch helpers for entity detail pages and their parallel supporting resources. */
import {
  assertPersonPayloadHasRequiredBioKeys,
  buildEntityDetailPath,
  type EntityDetailResponse,
  type Stage4EntityType
} from "$lib/entity-detail/contract";
import type {
  PersonContributionInsights,
  PersonTopEmployerRow,
  RankedTransactionParty
} from "$lib/campaign-finance-detail/contract";
import type { PersonMoneyAtGlanceSummary } from "$lib/entity-detail/person-campaign-finance-presentation";
import type { PersonCandidateFinanceSection } from "./campaign-finance-detail";
import type { ApiClient } from "./client";

export type EntityDetailRequest = {
  entityType: Stage4EntityType;
  id: string;
};

export type EntityDetailBundle = {
  entityType: Stage4EntityType;
  detail: EntityDetailResponse;
};

export type PersonDetailPageExtensions = {
  personMoneyHeadline: PersonMoneyHeadlineState | Promise<PersonMoneyHeadlineState>;
  personFinanceSections: Promise<PersonCandidateFinanceSection[]>;
  personContributionInsights: PersonContributionInsights | Promise<PersonContributionInsights>;
  personTopDonors: RankedTransactionParty[] | Promise<RankedTransactionParty[]>;
  personTopEmployers: PersonTopEmployerRow[] | Promise<PersonTopEmployerRow[]>;
};

/**
 * Person Money at a glance states.
 *
 * `not_loaded` is distinct from every other arm and must stay distinct: the backend
 * answers 200 with zero-valued money strings when it has no authoritative
 * selected-cycle evidence, and the only thing separating that from a real $0 is
 * `coverage.activity_state`. Collapsing `not_loaded` into `loaded` publishes
 * "Total receipts $0.00" as a fact we never established. See
 * `docs/reference/screen_specs/person_detail.md` ("Money at a glance") and the shared
 * coverage-discriminator matrix in `docs/reference/screen_specs/candidate_detail.md`.
 */
export type PersonMoneyHeadlineState =
  | { kind: "loaded"; summary: PersonMoneyAtGlanceSummary }
  | { kind: "no_linked_candidate"; message: string }
  // Carries the aggregate summary even though no figure from it may be shown.
  // The cycle switcher is built from its available_cycles, and a cycle with no
  // loaded evidence is precisely the page a reader most needs to leave.
  | {
      kind: "not_loaded";
      message: string;
      selectedCycle: number;
      summary: PersonMoneyAtGlanceSummary;
    }
  | { kind: "missing_summary"; message: string; selectedCycle: number }
  | { kind: "temporarily_unavailable"; message: string; selectedCycle: number };

export type EntityDetailPageBundle = EntityDetailBundle &
  Partial<PersonDetailPageExtensions>;

type EntityPathBuilder = (entityType: Stage4EntityType, id: string) => string;

function fetchEntityResource<T>(
  apiClient: ApiClient,
  request: EntityDetailRequest,
  buildPath: EntityPathBuilder
): Promise<T> {
  return apiClient.requestJson<T>(buildPath(request.entityType, request.id));
}

export async function fetchEntityDetail(
  apiClient: ApiClient,
  request: EntityDetailRequest
): Promise<EntityDetailResponse> {
  const detail = await fetchEntityResource<EntityDetailResponse>(apiClient, request, buildEntityDetailPath);

  if (request.entityType === "person") {
    assertPersonPayloadHasRequiredBioKeys(detail);
  }

  return detail;
}

/** Fetches the canonical detail payload for the public person/org profile contract. */
export async function fetchEntityDetailBundle(
  apiClient: ApiClient,
  request: EntityDetailRequest
): Promise<EntityDetailBundle> {
  const detail = await fetchEntityDetail(apiClient, request);

  return {
    entityType: request.entityType,
    detail
  };
}
