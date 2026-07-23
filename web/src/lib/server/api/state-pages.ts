/** Fetch helpers for landing-map and state-detail routes. */
import type { ApiClient } from "./client";
import {
  COUNTRY_GEOMETRY_PATH,
  type GeometryFeatureCollection
} from "./state-pages-contract";

export async function fetchCountryGeometry(
  apiClient: ApiClient
): Promise<GeometryFeatureCollection> {
  return apiClient.requestJson<GeometryFeatureCollection>(COUNTRY_GEOMETRY_PATH);
}
