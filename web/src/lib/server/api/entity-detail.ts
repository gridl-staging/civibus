/** Fetch helpers for entity detail pages and their parallel supporting resources. */
import {
  buildEntityDetailPath,
  buildEntityErMatchesPath,
  buildEntityGraphRelationshipsPath,
  type EntityDetailResponse,
  type EntityGraphRelationshipsResponse,
  type ErMatchDecision,
  type Stage4EntityType
} from "$lib/entity-detail/contract";
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
  return fetchEntityResource(apiClient, request, buildEntityDetailPath);
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
