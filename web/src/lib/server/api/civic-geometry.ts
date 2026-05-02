import type { CivicGeometryLevel } from "$lib/config/app";
import { ApiResponseError } from "./client";
import type { ApiClient } from "./client";

export type CivicGeometryRequest = {
  level: CivicGeometryLevel;
  state: string;
};

export type CivicGeometryFeatureProperties = {
  id: string;
  name: string;
  division_type: string;
  state: string;
  district_number: string | null;
  boundary_year: number | null;
};

export type CivicGeometry = {
  type: string;
  coordinates?: unknown;
  geometries?: CivicGeometry[];
  [key: string]: unknown;
};

export type CivicGeometryFeature = {
  type: "Feature";
  geometry: CivicGeometry;
  properties: CivicGeometryFeatureProperties;
};

export type CivicGeometryFeatureCollection = {
  type: "FeatureCollection";
  features: CivicGeometryFeature[];
};

function buildCivicGeometryPath(request: CivicGeometryRequest): string {
  const searchParams = new URLSearchParams();
  searchParams.set("level", request.level);
  searchParams.set("state", request.state.toUpperCase());
  return `/v1/civics/geometry?${searchParams.toString()}`;
}

export function createEmptyFeatureCollection(): CivicGeometryFeatureCollection {
  return {
    type: "FeatureCollection",
    features: []
  };
}

export function toCivicGeometryLevel(
  divisionType: string | null | undefined
): CivicGeometryLevel | null {
  if (divisionType === "statewide") {
    return "state";
  }
  if (divisionType === "county" || divisionType === "congressional_district") {
    return divisionType;
  }
  return null;
}

export function createGeometryByLevelRecord(): Record<CivicGeometryLevel, CivicGeometryFeatureCollection> {
  return {
    state: createEmptyFeatureCollection(),
    county: createEmptyFeatureCollection(),
    congressional_district: createEmptyFeatureCollection()
  };
}

export async function fetchCivicGeometry(
  apiClient: ApiClient,
  request: CivicGeometryRequest
): Promise<CivicGeometryFeatureCollection> {
  return apiClient.requestJson<CivicGeometryFeatureCollection>(buildCivicGeometryPath(request));
}

export async function fetchOptionalCivicGeometry(
  apiClient: ApiClient,
  request: CivicGeometryRequest
): Promise<CivicGeometryFeatureCollection> {
  try {
    return await fetchCivicGeometry(apiClient, request);
  } catch (error) {
    if (error instanceof ApiResponseError && error.status === 404) {
      return createEmptyFeatureCollection();
    }
    throw error;
  }
}
