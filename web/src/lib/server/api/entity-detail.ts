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
  personFinanceSections: Promise<PersonCandidateFinanceSection[]>;
  personContributionInsights: Promise<PersonContributionInsights>;
  personTopDonors: Promise<RankedTransactionParty[]>;
  personTopEmployers: Promise<PersonTopEmployerRow[]>;
};

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
