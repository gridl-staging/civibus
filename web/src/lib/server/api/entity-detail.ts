/** Fetch helpers for entity detail pages and their parallel supporting resources. */
import {
  assertPersonPayloadHasRequiredBioKeys,
  buildEntityDetailPath,
  buildEntityErMatchesPath,
  buildEntityGraphRelationshipsPath,
  type EntityDetailResponse,
  type EntityGraphRelationshipsResponse,
  type ErMatchDecision,
  type Stage4EntityType
} from "$lib/entity-detail/contract";
import {
  buildCandidacyDetailPath,
  buildOfficeholdingDetailPath,
  type CandidacyDetailResponse,
  type OfficeholdingDetailResponse
} from "$lib/civic-detail/contract";
import type { PersonCandidateFinanceSection } from "./campaign-finance-detail";
import { ApiResponseError } from "./client";
import type { ApiClient } from "./client";

export type EntityDetailRequest = {
  entityType: Stage4EntityType;
  id: string;
};

export type EntityDetailBundle = {
  entityType: Stage4EntityType;
  detail: EntityDetailResponse;
  matches: Promise<ErMatchDecision[]>;
  relationships: Promise<EntityGraphRelationshipsResponse>;
};

export type PersonDetailPageExtensions = {
  personCivicHistory: Promise<PersonCivicHistorySections>;
  personFinanceSections: Promise<PersonCandidateFinanceSection[]>;
};

export type EntityDetailPageBundle = EntityDetailBundle &
  Partial<PersonDetailPageExtensions>;

export type PersonCivicHistorySections = {
  officeholdings: OfficeholdingDetailResponse[];
  candidacies: CandidacyDetailResponse[];
  officeholdingLabelsById: Record<string, string>;
  officeLabelsById: Record<string, string>;
  candidacyLabelsById: Record<string, string>;
  contestLabelsById: Record<string, string>;
};

type EntityPathBuilder = (entityType: Stage4EntityType, id: string) => string;

function fetchEntityResource<T>(
  apiClient: ApiClient,
  request: EntityDetailRequest,
  buildPath: EntityPathBuilder
): Promise<T> {
  return apiClient.requestJson<T>(buildPath(request.entityType, request.id));
}

function guardUnhandledRejection(promise: Promise<unknown>): void {
  void promise.catch(() => {});
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

export async function fetchEntityMatches(
  apiClient: ApiClient,
  request: EntityDetailRequest
): Promise<ErMatchDecision[]> {
  return fetchEntityResource(apiClient, request, buildEntityErMatchesPath);
}

export async function fetchEntityRelationships(
  apiClient: ApiClient,
  request: EntityDetailRequest
): Promise<EntityGraphRelationshipsResponse> {
  return fetchEntityResource(apiClient, request, buildEntityGraphRelationshipsPath);
}

function extractUniqueNeighborIds(
  relationships: EntityGraphRelationshipsResponse,
  entityType: "officeholding" | "candidacy"
): string[] {
  const seen = new Set<string>();
  const ids: string[] = [];
  for (const neighbor of relationships.neighbors) {
    if (neighbor.entity_type !== entityType) {
      continue;
    }
    if (seen.has(neighbor.entity_id)) {
      continue;
    }
    seen.add(neighbor.entity_id);
    ids.push(neighbor.entity_id);
  }
  return ids;
}

function buildNeighborLabelLookup(
  relationships: EntityGraphRelationshipsResponse,
  entityType: "officeholding" | "office" | "candidacy" | "contest"
): Record<string, string> {
  const labelsById: Record<string, string> = {};
  for (const neighbor of relationships.neighbors) {
    if (neighbor.entity_type !== entityType || neighbor.name === null) {
      continue;
    }
    const normalized = neighbor.name.trim();
    if (normalized === "") {
      continue;
    }
    labelsById[neighbor.entity_id] = normalized;
  }
  return labelsById;
}

async function fetchOptionalNeighborDetail<T>(
  operation: () => Promise<T>
): Promise<T | null> {
  try {
    return await operation();
  } catch (error) {
    if (error instanceof ApiResponseError && error.status === 404) {
      return null;
    }
    throw error;
  }
}

/** Resolves detailed civic rows linked to a person via graph neighbors. */
export async function fetchPersonCivicHistorySections(
  apiClient: ApiClient,
  relationships: EntityGraphRelationshipsResponse
): Promise<PersonCivicHistorySections> {
  const officeholdingIds = extractUniqueNeighborIds(relationships, "officeholding");
  const candidacyIds = extractUniqueNeighborIds(relationships, "candidacy");

  const officeholdingsPromise = Promise.all(
    officeholdingIds.map((officeholdingId) =>
      fetchOptionalNeighborDetail(() =>
        apiClient.requestJson<OfficeholdingDetailResponse>(buildOfficeholdingDetailPath(officeholdingId))
      )
    )
  );
  const candidaciesPromise = Promise.all(
    candidacyIds.map((candidacyId) =>
      fetchOptionalNeighborDetail(() =>
        apiClient.requestJson<CandidacyDetailResponse>(buildCandidacyDetailPath(candidacyId))
      )
    )
  );

  const [officeholdingResults, candidacyResults] = await Promise.all([
    officeholdingsPromise,
    candidaciesPromise
  ]);
  const officeholdings = officeholdingResults.filter(
    (officeholding): officeholding is OfficeholdingDetailResponse => officeholding !== null
  );
  const candidacies = candidacyResults.filter(
    (candidacy): candidacy is CandidacyDetailResponse => candidacy !== null
  );
  return {
    officeholdings,
    candidacies,
    officeholdingLabelsById: buildNeighborLabelLookup(relationships, "officeholding"),
    officeLabelsById: buildNeighborLabelLookup(relationships, "office"),
    candidacyLabelsById: buildNeighborLabelLookup(relationships, "candidacy"),
    contestLabelsById: buildNeighborLabelLookup(relationships, "contest")
  };
}

/** Starts matches and relationships in parallel while awaiting the canonical detail first. */
export async function fetchEntityDetailBundle(
  apiClient: ApiClient,
  request: EntityDetailRequest
): Promise<EntityDetailBundle> {
  const detailPromise = fetchEntityDetail(apiClient, request);
  const matchesPromise = fetchEntityMatches(apiClient, request);
  const relationshipsPromise = fetchEntityRelationships(apiClient, request);
  guardUnhandledRejection(matchesPromise);
  guardUnhandledRejection(relationshipsPromise);

  try {
    const detail = await detailPromise;

    return {
      entityType: request.entityType,
      detail,
      matches: matchesPromise,
      relationships: relationshipsPromise
    };
  } catch (error) {
    void Promise.allSettled([matchesPromise, relationshipsPromise]);
    throw error;
  }
}
