import type {
  CoverageRegistryResponse,
  DataSourceMetadataResponse
} from "$lib/metadata/contract";
import type { ApiClient } from "./client";
import { describe, expect, it, vi } from "vitest";

const {
  buildCoverageRegistryPathMock,
  buildDataSourcesPathMock
} = vi.hoisted(() => ({
  buildCoverageRegistryPathMock: vi.fn(() => "/v1/coverage/registry"),
  buildDataSourcesPathMock: vi.fn(() => "/v1/data-sources")
}));

vi.mock("$lib/metadata/contract", async () => {
  const actual = await vi.importActual<typeof import("$lib/metadata/contract")>(
    "$lib/metadata/contract"
  );

  return {
    ...actual,
    buildCoverageRegistryPath: buildCoverageRegistryPathMock,
    buildDataSourcesPath: buildDataSourcesPathMock
  };
});

import {
  fetchCoverageRegistry,
  fetchDataSourcesMetadata
} from "./metadata";

function createApiClient(
  requestJson: ApiClient["requestJson"]
): ApiClient {
  return {
    requestJson
  };
}

describe("metadata api wrapper", () => {
  it("uses the metadata contract coverage builder and response type for /v1/coverage/registry", async () => {
    const payload: CoverageRegistryResponse[] = [
      {
        domain: "campaign_finance",
        jurisdiction: "state/nc",
        data_source_count: 2,
        latest_data_source_pull_at: "2026-04-29T12:00:00Z",
        latest_source_pull_date: "2026-04-28T12:00:00Z"
      }
    ];
    const requestJson = vi.fn().mockResolvedValue(payload);

    const response = await fetchCoverageRegistry(createApiClient(requestJson));

    expect(buildCoverageRegistryPathMock).toHaveBeenCalledTimes(1);
    expect(requestJson).toHaveBeenCalledWith("/v1/coverage/registry");
    expect(response).toEqual(payload);
  });

  it("uses the metadata contract data-sources builder and response type for /v1/data-sources", async () => {
    const payload: DataSourceMetadataResponse[] = [
      {
        data_source_id: "11111111-1111-4111-8111-111111111111",
        domain: "campaign_finance",
        jurisdiction: "state/nc",
        name: "NC Disclosure",
        source_url: "https://example.org/source",
        update_frequency: "daily",
        last_pull_at: "2026-04-29T12:00:00Z",
        last_pull_status: "success",
        record_count: 10,
        latest_source_record_id: "22222222-2222-4222-8222-222222222222",
        latest_source_record_key: "record-1",
        latest_source_record_url: "https://example.org/record-1",
        latest_source_pull_date: "2026-04-28T12:00:00Z"
      }
    ];
    const requestJson = vi.fn().mockResolvedValue(payload);

    const response = await fetchDataSourcesMetadata(createApiClient(requestJson));

    expect(buildDataSourcesPathMock).toHaveBeenCalledTimes(1);
    expect(requestJson).toHaveBeenCalledWith("/v1/data-sources");
    expect(response).toEqual(payload);
  });
});
