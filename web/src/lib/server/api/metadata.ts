import {
  buildCoverageRegistryPath,
  buildDataSourcesPath,
  type CoverageRegistryResponse,
  type DataSourceMetadataResponse
} from "$lib/metadata/contract";
import type { ApiClient } from "./client";

export async function fetchCoverageRegistry(
  apiClient: ApiClient
): Promise<CoverageRegistryResponse[]> {
  return apiClient.requestJson<CoverageRegistryResponse[]>(buildCoverageRegistryPath());
}

export async function fetchDataSourcesMetadata(
  apiClient: ApiClient
): Promise<DataSourceMetadataResponse[]> {
  return apiClient.requestJson<DataSourceMetadataResponse[]>(buildDataSourcesPath());
}
