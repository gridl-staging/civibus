/** Fetch helpers for landing-map and state-detail routes. */
import type { ApiClient } from "./client";
import {
  buildRegionalChildrenPath,
  buildRegionalResolvePath,
  buildRegionalSearchPath,
  COUNTRY_GEOMETRY_PATH,
  isRegionalNavigationNode,
  parseRegionalNavigationList,
  type GeometryFeatureCollection,
  type RegionalChildKind,
  type RegionalNavigationListResult,
  type RegionalNavigationNode,
  type RegionalResolveParams
} from "./state-pages-contract";

export async function fetchCountryGeometry(
  apiClient: ApiClient
): Promise<GeometryFeatureCollection> {
  return apiClient.requestJson<GeometryFeatureCollection>(COUNTRY_GEOMETRY_PATH);
}

export async function fetchRegionalNavigationNode(
  apiClient: ApiClient,
  params: RegionalResolveParams
): Promise<RegionalNavigationNode> {
  const value = await apiClient.requestJson<unknown>(buildRegionalResolvePath(params));
  if (!isRegionalNavigationNode(value)) {
    throw new Error("Regional navigation response did not contain one safe canonical node.");
  }
  return value;
}

export async function fetchRegionalChildren(
  apiClient: ApiClient,
  stateCode: string,
  kind: RegionalChildKind
): Promise<RegionalNavigationListResult> {
  const value = await apiClient.requestJson<unknown>(buildRegionalChildrenPath(stateCode, kind));
  return parseRegionalNavigationList(value);
}

export async function fetchRegionalNavigationSearch(
  apiClient: ApiClient,
  query: string
): Promise<RegionalNavigationListResult> {
  const value = await apiClient.requestJson<unknown>(buildRegionalSearchPath(query));
  return parseRegionalNavigationList(value);
}
